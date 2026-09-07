"""Решения админа по заявкам и правкам профиля -- прямо в сообщении бота.

Раньше уведомление заканчивалось словами «проверить можно в админке сайта», и
проверка откладывалась до ближайшего компьютера: админ клуба живёт в
Telegram. Теперь под сообщением две кнопки, а отказ спрашивает причину тем же
диалогом -- причина обязательна, её игрок увидит вместо решения.

Экран раздела (`app/ui.py`) здесь ни при чём: уведомление -- отдельное
сообщение, приходящее само по себе, и правится оно на месте. Итог решения
дописывается в это же сообщение, а кнопки снимаются -- иначе в чате остаётся
рабочая кнопка на уже принятое решение.

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
from aiogram.types import CallbackQuery, Message

from app.api_client import ApiClient, ApiError
from app.keyboards.inline import moderation_cancel_keyboard, moderation_keyboard
from app.states import ModerationStates
from app.ui import consume_input, screen_message

logger = logging.getLogger(__name__)

router = Router(name="moderation")

ASK_REASON = (
    "Напишите причину отклонения одним сообщением — её увидит игрок.\n"
    "Без причины отказ выглядит как поломка."
)

KIND_REGISTRATION = "r"
KIND_CHANGE = "c"


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
    value = result.get("new_value") or "пусто"
    if reason is None:
        return f"✅ Применено: {who}, {field} → {value}"
    return f"⛔ Отклонено: {who}, {field} → {value}\nПричина: {reason}"


def _strip_tail(text: str) -> str:
    """Убрать приписку прошлого шага (вопрос о причине), оставив само уведомление."""
    return text.split(f"\n\n{ASK_REASON}")[0]


async def _finish(message: Message, text: str) -> None:
    """Дописать итог в уведомление и снять с него кнопки."""
    with suppress(TelegramBadRequest):
        await message.edit_text(f"{_strip_tail(message.text or '')}\n\n{text}")


@router.callback_query(F.data.startswith("md:ok:"))
async def approve(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    _, _, kind, raw_id = callback.data.split(":")
    message = screen_message(callback)
    if message is None:
        await callback.answer("Это сообщение слишком старое, решите на сайте.", show_alert=True)
        return
    try:
        result = await _decide(api, callback.from_user.id, kind, int(raw_id), None)
    except ApiError as exc:
        await callback.answer(exc.message, show_alert=True)
        # 409 -- «уже рассмотрено» (решил другой админ) или «ник занят».
        # Кнопки в этом сообщении больше ничего не сделают, и оставлять их
        # рабочими значит звать на второе такое же нажатие.
        if exc.status_code in (404, 409):
            await _finish(message, f"ℹ️ {exc.message}")
        return
    await state.set_state(None)
    await _finish(message, _verdict(kind, result, None))
    await callback.answer("Готово ✅")


@router.callback_query(F.data.startswith("md:no:"))
async def ask_reason(callback: CallbackQuery, state: FSMContext) -> None:
    _, _, kind, raw_id = callback.data.split(":")
    message = screen_message(callback)
    if message is None:
        await callback.answer("Это сообщение слишком старое, решите на сайте.", show_alert=True)
        return
    await state.set_state(ModerationStates.waiting_for_rejection_reason)
    # Куда потом дописать итог: причина приходит отдельным сообщением, и связи
    # с этим уведомлением у него нет никакой, кроме этой записи.
    await state.update_data(
        md_kind=kind,
        md_id=int(raw_id),
        md_chat_id=message.chat.id,
        md_message_id=message.message_id,
        md_text=_strip_tail(message.text or ""),
    )
    with suppress(TelegramBadRequest):
        await message.edit_text(
            f"{_strip_tail(message.text or '')}\n\n{ASK_REASON}",
            reply_markup=moderation_cancel_keyboard(kind, int(raw_id)),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("md:back:"))
async def cancel_reason(callback: CallbackQuery, state: FSMContext) -> None:
    _, _, kind, raw_id = callback.data.split(":")
    await state.set_state(None)
    message = screen_message(callback)
    if message is not None:
        with suppress(TelegramBadRequest):
            await message.edit_text(
                _strip_tail(message.text or ""),
                reply_markup=moderation_keyboard(kind, int(raw_id)),
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
        md_kind=None, md_id=None, md_chat_id=None, md_message_id=None, md_text=None
    )

    chat_id, message_id = data.get("md_chat_id"), data.get("md_message_id")
    if not chat_id or not message_id:
        await message.answer(verdict)
        return
    try:
        # Итог дописывается в то же уведомление, а кнопки снимаются: решать
        # второй раз нечем, и в чате не появляется отдельного сообщения.
        await message.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=f"{data.get('md_text') or ''}\n\n{verdict}".strip(),
        )
    except TelegramBadRequest:
        logger.info("Не удалось дописать итог в уведомление %s", message_id)
        await message.answer(verdict)
