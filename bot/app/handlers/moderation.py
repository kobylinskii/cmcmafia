"""Решения админа по заявкам и правкам профиля -- целиком в Telegram.

Раньше уведомление заканчивалось словами «проверить можно в админке сайта», и
проверка откладывалась до ближайшего компьютера: админ клуба живёт в
Telegram. Теперь под сообщением две кнопки, а отказ спрашивает причину тем же
диалогом -- причина обязательна, её игрок увидит вместо решения.

Мест, откуда принимается решение, два, и оба нужны:

* **уведомление** -- то, что бот прислал сам, как только заявка появилась.
  Отдельное сообщение, живущее само по себе: итог дописывается в него, а
  кнопки снимаются, иначе в чате остаётся рабочая кнопка на уже принятое
  решение. Экран раздела (`app/ui.py`) тут ни при чём.
* **раздел «🕓 На проверке»** в админ-меню -- полный список того, что ещё ждёт
  решения. Уведомление можно удалить из чата, и без списка заявка после этого
  не всплыла бы больше нигде (экрана модерации на сайте больше нет). Это
  обычный экран бота и живёт по правилам `ui.py`: список -> карточка ->
  список.

Различает их хвост `:q` в callback_data (`keyboards.inline.FROM_QUEUE`):
решение одно и то же, а возвращаться после него надо в разные места.

Уведомление уходит каждому админу своей копией. Решает кто-то один: у
остальных нажатие получает от бэкенда 409 «уже рассмотрено», и их копия
дописывается этим же текстом.
"""

from __future__ import annotations

import logging
from contextlib import suppress

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from app.api_client import ApiClient, ApiError
from app.keyboards.inline import (
    FROM_QUEUE,
    KIND_REGISTRATION,
    moderation_cancel_keyboard,
    moderation_keyboard,
    moderation_queue_keyboard,
)
from app.notifier import (
    PHOTO_FIELD,
    admin_profile_change_text,
    admin_registration_text,
    change_photo,
)
from app.states import ModerationStates
from app.ui import consume_input, edit_screen, open_photo_screen, open_screen, screen_message

logger = logging.getLogger(__name__)

router = Router(name="moderation")

ASK_REASON = (
    "Напишите причину отклонения одним сообщением — её увидит игрок.\n"
    "Без причины отказ выглядит как поломка."
)
QUEUE_EMPTY = "🕓 На проверке\n\nНичего не ждёт решения."
QUEUE_TITLE = "🕓 На проверке\n\nНажмите на строку, чтобы посмотреть и решить."


def _parse(data: str) -> tuple[str, int, bool]:
    """`md:<действие>:<вид>:<id>[:q]` -> (вид, id, пришли ли из списка)."""
    parts = data.split(":")
    return parts[2], int(parts[3]), parts[4:] == [FROM_QUEUE]


async def _decide(api: ApiClient, tg_id: int, kind: str, item_id: int, reason: str | None) -> dict:
    if kind == KIND_REGISTRATION:
        return await api.moderate_registration(tg_id, item_id, reason=reason)
    return await api.moderate_profile_change(tg_id, item_id, reason=reason)


def _verdict(kind: str, result: dict, reason: str | None) -> str:
    who = result.get("nickname") or "игрок"
    if kind == KIND_REGISTRATION:
        if reason is None:
            return f"✅ Заявка {who} подтверждена."
        return f"⛔ Заявка {who} отклонена: {reason}"
    field = result.get("field_label") or "поле"
    # У фото значение -- путь к файлу: в итоге решения от него никакого толку.
    value = "" if result.get("field") == PHOTO_FIELD else f" → {result.get('new_value') or 'пусто'}"
    if reason is None:
        return f"✅ Применено: {who}, {field}{value}"
    return f"⛔ Отклонено: {who}, {field}{value}\nПричина: {reason}"


def _strip_tail(text: str) -> str:
    """Убрать приписку прошлого шага (вопрос о причине), оставив само уведомление."""
    return text.split(f"\n\n{ASK_REASON}")[0]


def _body(message: Message) -> str:
    """Текст карточки. У правки фото карточка -- это картинка, и весь текст
    лежит в подписи: message.text у неё None."""
    return _strip_tail(message.text or message.caption or "")


async def _rewrite(message: Message, text: str, keyboard: InlineKeyboardMarkup | None = None) -> None:
    """Перерисовать карточку, чем бы она ни была. Подпись у фото правится
    отдельным методом -- edit_text на нём отвечает «нет текста для правки»."""
    if message.photo:
        await message.edit_caption(caption=text, reply_markup=keyboard)
    else:
        await message.edit_text(text, reply_markup=keyboard)


async def _finish(message: Message, text: str) -> None:
    """Дописать итог в уведомление и снять с него кнопки."""
    with suppress(TelegramBadRequest):
        await _rewrite(message, f"{_body(message)}\n\n{text}")


# ------------------------------------------------------------ «На проверке»
async def _queue_screen(api: ApiClient, tg_id: int) -> tuple[str, InlineKeyboardMarkup]:
    data = await api.moderation_queue(tg_id)
    registrations = data.get("registrations") or []
    changes = data.get("profile_changes") or []
    text = QUEUE_TITLE if (registrations or changes) else QUEUE_EMPTY
    return text, moderation_queue_keyboard(registrations, changes)


@router.callback_query(F.data == "md:queue")
async def show_queue(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    await state.set_state(None)
    try:
        text, keyboard = await _queue_screen(api, callback.from_user.id)
    except ApiError as exc:
        await callback.answer(exc.message, show_alert=True)
        return
    await edit_screen(callback, state, text, keyboard)


@router.callback_query(F.data.startswith("md:card:"))
async def show_card(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    """Карточка одной заявки или правки -- тот же текст, что и в уведомлении."""
    kind, item_id, _ = _parse(callback.data)
    try:
        data = await api.moderation_queue(callback.from_user.id)
    except ApiError as exc:
        await callback.answer(exc.message, show_alert=True)
        return

    if kind == KIND_REGISTRATION:
        item = next(
            (i for i in data.get("registrations") or [] if i["player_id"] == item_id), None
        )
        text = admin_registration_text(item) if item else None
    else:
        item = next(
            (i for i in data.get("profile_changes") or [] if i["change_id"] == item_id), None
        )
        text = admin_profile_change_text(item) if item else None

    if text is None:
        # Решил другой админ, пока экран висел: возвращаем к обновлённому списку.
        await show_queue(callback, state, api)
        await callback.answer("Это уже рассмотрели.", show_alert=True)
        return

    keyboard = moderation_keyboard(kind, item_id, from_queue=True)
    photo = await change_photo(api, item) if kind != KIND_REGISTRATION else None
    if photo is not None:
        # Смысл карточки правки фото -- увидеть фото. Экран при этом остаётся
        # один: open_photo_screen убирает текстовый и присылает картинку.
        message = screen_message(callback)
        if message is None:
            await callback.answer("Это сообщение слишком старое, откройте /admin.", show_alert=True)
            return
        await open_photo_screen(message, state, photo, text, keyboard)
        await callback.answer()
        return
    await edit_screen(callback, state, text, keyboard)


# ------------------------------------------------------------------ решение
@router.callback_query(F.data.startswith("md:ok:"))
async def approve(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    kind, item_id, from_queue = _parse(callback.data)
    message = screen_message(callback)
    if message is None:
        await callback.answer("Это сообщение слишком старое, откройте /admin.", show_alert=True)
        return
    try:
        result = await _decide(api, callback.from_user.id, kind, item_id, None)
    except ApiError as exc:
        # 409 -- «уже рассмотрено» (решил другой админ) или «ник занят».
        if from_queue:
            await show_queue(callback, state, api)
            await callback.answer(exc.message, show_alert=True)
            return
        await callback.answer(exc.message, show_alert=True)
        # Кнопки в этом уведомлении больше ничего не сделают, и оставлять их
        # рабочими значит звать на второе такое же нажатие.
        if exc.status_code in (404, 409):
            await _finish(message, f"ℹ️ {exc.message}")
        return

    await state.set_state(None)
    verdict = _verdict(kind, result, None)
    if from_queue:
        # Из списка возвращаемся в список: карточки этой заявки в нём больше
        # нет, и оставлять админа на мёртвом экране незачем.
        text, keyboard = await _queue_screen(api, callback.from_user.id)
        await edit_screen(callback, state, text, keyboard, alert=verdict)
        return
    await _finish(message, verdict)
    await callback.answer("Готово ✅")


@router.callback_query(F.data.startswith("md:no:"))
async def ask_reason(callback: CallbackQuery, state: FSMContext) -> None:
    kind, item_id, from_queue = _parse(callback.data)
    message = screen_message(callback)
    if message is None:
        await callback.answer("Это сообщение слишком старое, откройте /admin.", show_alert=True)
        return
    await state.set_state(ModerationStates.waiting_for_rejection_reason)
    # Куда потом дописать итог: причина приходит отдельным сообщением, и связи
    # с этим экраном у него нет никакой, кроме этой записи.
    await state.update_data(
        md_kind=kind,
        md_id=item_id,
        md_from_queue=from_queue,
        md_chat_id=message.chat.id,
        md_message_id=message.message_id,
        md_text=_body(message),
        # Итог дописывается уже без самого сообщения, по chat_id/message_id, --
        # а метод правки у картинки и у текста разный.
        md_is_photo=bool(message.photo),
    )
    with suppress(TelegramBadRequest):
        await _rewrite(
            message,
            f"{_body(message)}\n\n{ASK_REASON}",
            moderation_cancel_keyboard(kind, item_id, from_queue=from_queue),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("md:back:"))
async def cancel_reason(callback: CallbackQuery, state: FSMContext) -> None:
    kind, item_id, from_queue = _parse(callback.data)
    await state.set_state(None)
    message = screen_message(callback)
    if message is not None:
        with suppress(TelegramBadRequest):
            await _rewrite(
                message,
                _body(message),
                moderation_keyboard(kind, item_id, from_queue=from_queue),
            )
    await callback.answer()


@router.message(ModerationStates.waiting_for_rejection_reason)
async def reason_received(message: Message, state: FSMContext, api: ApiClient) -> None:
    await consume_input(message)
    data = await state.get_data()
    kind, item_id = data.get("md_kind"), data.get("md_id")
    if not kind or not item_id:
        await state.set_state(None)
        await message.answer("Причина потерялась, нажмите «Отклонить» ещё раз.")
        return

    reason = (message.text or "").strip()
    if not reason:
        await message.answer(ASK_REASON)
        return

    try:
        result = await _decide(api, message.from_user.id, kind, int(item_id), reason)
        verdict = _verdict(kind, result, reason)
    except ApiError as exc:
        verdict = f"ℹ️ {exc.message}"

    await state.set_state(None)
    await state.update_data(
        md_kind=None, md_id=None, md_from_queue=None, md_chat_id=None, md_message_id=None,
        md_text=None, md_is_photo=None,
    )

    chat_id, message_id = data.get("md_chat_id"), data.get("md_message_id")
    if not chat_id or not message_id:
        await message.answer(verdict)
        return

    if data.get("md_from_queue"):
        # Экран раздела возвращаем к списку -- как и после подтверждения.
        try:
            text, keyboard = await _queue_screen(api, message.from_user.id)
        except ApiError:
            text, keyboard = verdict, None
        else:
            text = f"{verdict}\n\n{text}"
        if data.get("md_is_photo"):
            # Карточку-картинку текстом не заменить: убираем её и присылаем
            # список заново -- ровно то, что делает open_screen.
            await open_screen(message, state, text, keyboard)
            return
    else:
        # Итог дописывается в само уведомление, кнопки снимаются: решать
        # второй раз нечем, и в чате не появляется отдельного сообщения.
        text, keyboard = f"{data.get('md_text') or ''}\n\n{verdict}".strip(), None

    try:
        if data.get("md_is_photo") and not data.get("md_from_queue"):
            await message.bot.edit_message_caption(
                chat_id=chat_id, message_id=message_id, caption=text, reply_markup=keyboard
            )
        else:
            await message.bot.edit_message_text(
                chat_id=chat_id, message_id=message_id, text=text, reply_markup=keyboard
            )
    except TelegramBadRequest:
        logger.info("Не удалось дописать итог в сообщение %s", message_id)
        await message.answer(verdict)
