"""Профиль игрока: карточка, редактирование и повторная заявка.

Это же место закрывает и «анкету для сайта» -- возраст, любимую роль, опыт,
рассказ о себе и фотографию.

Экран всегда один и тот же, он перерисовывается по шагам (карточка -> список
полей -> ввод значения -> карточка). Раньше редактирование профиля жило на
reply-клавиатурах, и после сохранения на экране оставались кнопки полей,
которые уже ничего не редактировали.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app import texts
from app.api_client import ApiClient, ApiError, ConflictError
from app.handlers.common import require_profile
from app.keyboards.inline import (
    affiliation_keyboard,
    cancel_input_keyboard,
    favorite_role_keyboard,
    preferred_roles_keyboard,
    profile_fields_keyboard,
    profile_keyboard,
    profile_value_keyboard,
    salutation_keyboard,
)
from app.states import ProfileStates
from app.ui import consume_input, edit_screen, open_screen
from app.utils import (
    NICKNAME_MAX_LENGTH,
    NICKNAME_MIN_LENGTH,
    validate_full_name,
    validate_nickname,
)

router = Router(name="profile")

# Поля, которые вводятся текстом: подсказка + сообщение об ошибке разбора.
TEXT_FIELDS: dict[str, tuple[str, str]] = {
    "full_name": (
        "Введите ФИО полностью — Фамилия Имя Отчество.",
        "Нужны ровно три слова на русском языке, только буквы.",
    ),
    "nickname": (
        f"Введите новый никнейм — от {NICKNAME_MIN_LENGTH} до {NICKNAME_MAX_LENGTH} "
        "букв, можно с пробелами, без цифр и знаков.",
        f"Никнейм — от {NICKNAME_MIN_LENGTH} до {NICKNAME_MAX_LENGTH} символов, "
        "только буквы и пробелы между ними.",
    ),
    "age": ("Сколько вам лет?", "Возраст — это число от 5 до 100."),
    "experience": (
        "Расскажите об игровом опыте — сколько играете, где, какие турниры.",
        "Слишком длинно: не больше 2000 символов.",
    ),
    "bio": (
        "Пара слов о себе для страницы на сайте.",
        "Слишком длинно: не больше 4000 символов.",
    ),
}


PHOTO_PROMPT = "Пришлите фотографию для страницы на сайте — картинкой, а не файлом."


def moderation_note(user: dict) -> str:
    """Предупреждение перед вводом. Каждое поле этого раздела -- и текстовые,
    и фото -- у подтверждённого игрока проходит проверку админа (бэкенд,
    profile_change_service.MODERATED_FIELDS). Молча принять значение и не
    показать его в профиле означало бы выглядеть сломанным."""
    if user.get("confirmation_status") != "confirmed":
        return ""
    return "\n\n⏳ Изменение вступит в силу после проверки администратора."


def _pending_note(user: dict, field: str) -> str:
    """Приписка «ждёт проверки» к полю, которое игрок уже поправил.

    Без неё экран выглядит так, будто правка не сохранилась: значение в
    профиле остаётся прежним до решения админа, и человек отправляет её
    второй и третий раз."""
    changes = user.get("pending_changes") or {}
    if field not in changes:
        return ""
    value = changes[field]
    return f"\n   ⏳ на проверке: {value if value else 'очистить поле'}"


def _profile_text(user: dict, stats: dict | None) -> str:
    status = user.get("confirmation_status") or "confirmed"
    lines = [
        "👤 Профиль",
        "",
        f"Статус: {texts.CONFIRMATION_STATUS.get(status, status)}",
    ]
    if status == "rejected" and user.get("rejection_reason"):
        lines.append(f"Причина: {user['rejection_reason']}")
    if status == "pending":
        lines.append("Записываться на игры можно уже сейчас.")

    lines += [
        "",
        f"• Обращение: {texts.SALUTATIONS.get(user.get('salutation') or '', '—').lstrip('🤵👒 ')}",
        f"• ФИО: {user.get('full_name') or '—'}{_pending_note(user, 'full_name')}",
        f"• Проход: {texts.AFFILIATION_SHORT.get(user.get('affiliation') or '', '—')}",
        f"• Роли: {texts.preferred_roles_text(bool(user.get('can_play')), bool(user.get('can_staff')))}",
        f"• Никнейм: {user['nickname']}{_pending_note(user, 'nickname')}",
        f"• Телефон: {user.get('phone') or '—'}",
        "",
        "Анкета для сайта:",
        f"• Возраст: {user.get('age') or '—'}{_pending_note(user, 'age')}",
        f"• Любимая роль: {texts.FAVORITE_ROLES.get(user.get('favorite_role') or '', '—')}",
        f"• Опыт: {user.get('experience') or '—'}{_pending_note(user, 'experience')}",
        f"• О себе: {user.get('bio') or '—'}{_pending_note(user, 'bio')}",
        f"• Фото: {'загружено' if user.get('photo_url') else '—'}"
        + ("\n   ⏳ новое фото на проверке" if "photo_url" in (user.get("pending_changes") or {}) else ""),
        "",
        _stats_line(stats),
    ]
    if user.get("pending_changes"):
        lines += ["", "⏳ Правки ждут проверки администратора. До неё действуют прежние значения."]
    return "\n".join(lines)


def _stats_line(stats: dict | None) -> str:
    """Очень краткая сводка -- одна строка. Подробности живут на сайте, и
    тащить их в чат смысла нет."""
    if not stats or not stats.get("total_games"):
        return "📊 Сыгранных игр пока нет."
    parts = [f"игр {stats['total_games']}", f"побед {stats['wins']}"]
    if stats.get("win_rate") is not None:
        parts.append(f"{round(stats['win_rate'] * 100)}%")
    if stats.get("rating") is not None:
        rank = f" (#{stats['rank']})" if stats.get("rank") else ""
        parts.append(f"рейтинг {round(float(stats['rating']))}{rank}")
    return "📊 " + " · ".join(parts)


async def _load_card(api: ApiClient, tg_id: int) -> tuple[dict, str] | None:
    user = await api.get_profile(tg_id)
    if user is None:
        return None
    try:
        stats = await api.my_stats(tg_id)
    except ApiError:
        # Статистика -- украшение карточки, а не её смысл: недоступный агрегат
        # не должен мешать человеку открыть профиль и поправить ФИО.
        stats = None
    return user, _profile_text(user, stats)


async def _show_card(callback: CallbackQuery, state: FSMContext, api: ApiClient, *, alert: str | None = None) -> None:
    card = await _load_card(api, callback.from_user.id)
    if card is None:
        await callback.answer("Профиль не найден, начните с /start.", show_alert=True)
        return
    user, text = card
    await state.set_state(None)
    await edit_screen(
        callback,
        state,
        text,
        profile_keyboard(can_resubmit=user.get("confirmation_status") == "rejected"),
        alert=alert,
    )


@router.message(Command("profile"))
async def open_profile(message: Message, state: FSMContext, api: ApiClient) -> None:
    await consume_input(message)
    if not await require_profile(message, state, api):
        return
    await state.set_state(None)
    card = await _load_card(api, message.from_user.id)
    if card is None:
        return
    user, text = card
    await open_screen(
        message, state, text, profile_keyboard(can_resubmit=user.get("confirmation_status") == "rejected")
    )


@router.callback_query(F.data == "pf:menu")
async def back_to_card(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    await _show_card(callback, state, api)


@router.callback_query(F.data == "pf:edit")
async def choose_field(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(None)
    await edit_screen(callback, state, "Что изменить?", profile_fields_keyboard())


@router.callback_query(F.data.startswith("pf:field:"))
async def open_field(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    field = callback.data.split(":")[2]
    user = await api.get_profile(callback.from_user.id)
    if user is None:
        await callback.answer("Профиль не найден, начните с /start.", show_alert=True)
        return

    if field == "salutation":
        await edit_screen(
            callback, state, "Как к вам обращаться?",
            profile_value_keyboard(field, salutation_keyboard("pf")),
        )
        return
    if field == "affiliation":
        await edit_screen(
            callback, state, "Нужен ли вам пропуск на факультет?",
            profile_value_keyboard(field, affiliation_keyboard("pf")),
        )
        return
    if field == "favorite_role":
        await edit_screen(
            callback, state, "Какая роль нравится больше всего?",
            profile_value_keyboard(field, favorite_role_keyboard("pf")),
        )
        return
    if field == "roles":
        await state.update_data(
            pf_can_play=bool(user.get("can_play")), pf_can_staff=bool(user.get("can_staff"))
        )
        await edit_screen(
            callback, state, "За кого вы готовы играть?",
            profile_value_keyboard(
                field,
                preferred_roles_keyboard(
                    "pf", can_play=bool(user.get("can_play")), can_staff=bool(user.get("can_staff"))
                ),
            ),
        )
        return

    if field == "photo":
        await state.set_state(ProfileStates.waiting_for_photo)
        await edit_screen(
            callback, state, PHOTO_PROMPT + moderation_note(user), cancel_input_keyboard("pf:edit")
        )
        return

    prompt = TEXT_FIELDS.get(field)
    if prompt is None:
        await callback.answer("Это поле нельзя изменить в боте.", show_alert=True)
        return
    await state.set_state(ProfileStates.waiting_for_value)
    await state.update_data(profile_field=field)
    await edit_screen(callback, state, prompt[0] + moderation_note(user), cancel_input_keyboard("pf:edit"))


@router.callback_query(F.data.startswith("pf:salutation:"))
@router.callback_query(F.data.startswith("pf:affiliation:"))
@router.callback_query(F.data.startswith("pf:favorite_role:"))
async def save_choice(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    _, field, value = callback.data.split(":", 2)
    try:
        await api.update_profile(callback.from_user.id, **{field: value})
    except ApiError as exc:
        await callback.answer(exc.message, show_alert=True)
        return
    await _show_card(callback, state, api, alert="Сохранено ✅")


@router.callback_query(F.data.startswith("pf:toggle:"))
async def toggle_role(callback: CallbackQuery, state: FSMContext) -> None:
    role = callback.data.split(":")[2]
    data = await state.get_data()
    can_play, can_staff = bool(data.get("pf_can_play")), bool(data.get("pf_can_staff"))
    if role == "player":
        can_play = not can_play
    elif role == "staff":
        can_staff = not can_staff
    else:
        await callback.answer()
        return
    await state.update_data(pf_can_play=can_play, pf_can_staff=can_staff)
    await edit_screen(
        callback,
        state,
        "За кого вы готовы играть?",
        profile_value_keyboard("roles", preferred_roles_keyboard("pf", can_play=can_play, can_staff=can_staff)),
    )


@router.callback_query(F.data == "pf:save")
async def save_roles(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    data = await state.get_data()
    can_play, can_staff = bool(data.get("pf_can_play")), bool(data.get("pf_can_staff"))
    if not (can_play or can_staff):
        await callback.answer("Оставьте хотя бы один вариант.", show_alert=True)
        return
    try:
        await api.update_profile(callback.from_user.id, can_play=can_play, can_staff=can_staff)
    except ApiError as exc:
        await callback.answer(exc.message, show_alert=True)
        return
    await _show_card(callback, state, api, alert="Сохранено ✅")


@router.callback_query(F.data.startswith("pf:clear:"))
async def clear_field(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    field = callback.data.split(":")[2]
    try:
        await api.update_profile(callback.from_user.id, **{field: None})
    except ApiError as exc:
        await callback.answer(exc.message, show_alert=True)
        return
    await _show_card(callback, state, api, alert="Поле очищено")


@router.callback_query(F.data == "pf:resubmit")
async def resubmit(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    try:
        await api.resubmit_profile(callback.from_user.id)
    except ConflictError as exc:
        await callback.answer(exc.message, show_alert=True)
        return
    except ApiError as exc:
        await callback.answer(exc.message, show_alert=True)
        return
    await _show_card(callback, state, api, alert="Заявка снова на проверке ⏳")


@router.message(ProfileStates.waiting_for_value)
async def save_text_value(message: Message, state: FSMContext, api: ApiClient) -> None:
    await consume_input(message)
    data = await state.get_data()
    field = data.get("profile_field")
    prompt = TEXT_FIELDS.get(field or "")
    if prompt is None:
        await state.set_state(None)
        await open_screen(message, state, "Поле не выбрано.", profile_fields_keyboard())
        return

    value = _parse(field, message.text or "")
    if value is None:
        await open_screen(message, state, f"{prompt[1]}\n\n{prompt[0]}", cancel_input_keyboard("pf:edit"))
        return

    try:
        updated = await api.update_profile(message.from_user.id, **{field: value})
    except ConflictError as exc:
        await open_screen(message, state, f"{exc.message}\n\n{prompt[0]}", cancel_input_keyboard("pf:edit"))
        return
    except ApiError as exc:
        await open_screen(message, state, f"Не удалось сохранить: {exc.message}", profile_fields_keyboard())
        return

    # Текстовые поля подтверждённого игрока сохраняются не сразу: они уходят
    # админу на проверку, и обещать «сохранено» в этом случае нельзя.
    queued = field in (updated.get("pending_changes") or {})
    headline = (
        "⏳ Отправлено на проверку администратору.\nПока действует прежнее значение."
        if queued
        else "Сохранено ✅"
    )
    await _show_card_after_input(message, state, api, headline)


@router.message(ProfileStates.waiting_for_photo, F.photo)
async def save_photo(message: Message, state: FSMContext, api: ApiClient) -> None:
    """Аватарка из чата.

    Берём самый крупный из присланных Telegram размеров: мельче он сожмёт
    сам, а на сайте фото стоит в карточке игрока крупным планом. Скачиваем ДО
    consume_input -- сообщение с вложением после удаления уже не наше."""
    buffer = await message.bot.download(message.photo[-1].file_id)
    await consume_input(message)
    try:
        result = await api.upload_photo(message.from_user.id, buffer.read())
    except ApiError as exc:
        await open_screen(
            message, state, f"Не удалось сохранить: {exc.message}\n\n{PHOTO_PROMPT}",
            cancel_input_keyboard("pf:edit"),
        )
        return
    # У подтверждённого игрока фото ждёт админа наравне с ФИО и ником, и
    # обещать «обновлено» в этом случае нельзя: на сайте пока прежнее.
    headline = (
        "⏳ Фото отправлено на проверку администратору.\nПока на сайте прежнее."
        if result.get("pending")
        else "Фото обновлено ✅"
    )
    await _show_card_after_input(message, state, api, headline)


@router.message(ProfileStates.waiting_for_photo)
async def reject_non_photo(message: Message, state: FSMContext) -> None:
    """Всё, что не картинка: текст, стикер, документ (в том числе картинка,
    отправленная «как файл» -- у неё нет message.photo). Без этой ветки такое
    сообщение молча проваливалось мимо всех фильтров, и экран не менялся."""
    await consume_input(message)
    await open_screen(
        message,
        state,
        f"Это не похоже на фотографию.\n\n{PHOTO_PROMPT}",
        cancel_input_keyboard("pf:edit"),
    )


async def _show_card_after_input(
    message: Message, state: FSMContext, api: ApiClient, headline: str
) -> None:
    """Вернуть человека в карточку профиля после ручного ввода."""
    await state.set_state(None)
    card = await _load_card(api, message.from_user.id)
    if card is None:
        return
    user, text = card
    await open_screen(
        message,
        state,
        f"{headline}\n\n{text}",
        profile_keyboard(can_resubmit=user.get("confirmation_status") == "rejected"),
    )


def _parse(field: str, raw: str) -> str | int | None:
    text = (raw or "").strip()
    if field == "full_name":
        return validate_full_name(text)
    if field == "nickname":
        # Длина проверяется внутри validate_nickname -- одна граница на бота.
        return validate_nickname(text)
    if field == "age":
        return int(text) if text.isdigit() and 5 <= int(text) <= 100 else None
    if field == "experience":
        return text if 0 < len(text) <= 2000 else None
    if field == "bio":
        return text if 0 < len(text) <= 4000 else None
    return None
