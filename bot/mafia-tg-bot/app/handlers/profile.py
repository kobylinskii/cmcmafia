from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.api_client import ApiClient, ConflictError
from app.keyboards.inline import preferred_roles_select_keyboard
from app.keyboards.reply import (
    affiliation_keyboard,
    main_keyboard,
    profile_edit_field_keyboard,
    salutation_keyboard,
)
from app.states import ProfileStates
from app.utils import validate_full_name, validate_nickname

router = Router(name="profile")

AFFILIATION_LABELS = {
    "vmk": "С ВМК",
    "mgu_no_pass": "Из МГУ, пропуск не нужен",
    "outside_need_pass": "Вне МГУ, нужен пропуск",
}


def _profile_text(user: dict) -> str:
    affiliation = AFFILIATION_LABELS.get(user.get("affiliation") or "", "-")
    role_parts: list[str] = []
    if user.get("can_play"):
        role_parts.append("игрок")
    if user.get("can_staff"):
        role_parts.append("ведущий/судья")
    preferred_roles = ", ".join(role_parts) if role_parts else "-"
    return (
        "Ваш профиль:\n"
        f"• Обращение: {user.get('salutation') or '-'}\n"
        f"• ФИО: {user.get('full_name') or '-'}\n"
        f"• Статус: {affiliation}\n"
        f"• Предпочтение по ролям: {preferred_roles}\n"
        f"• Никнейм: {user.get('nickname')}\n"
        f"• Телефон: {user.get('phone') or '-'}"
    )


@router.message(F.text.in_({"Редактировать профиль", "📝 Редактировать профиль"}))
async def profile_edit_start(message: Message, state: FSMContext, api: ApiClient) -> None:
    user = await api.get_profile(message.from_user.id)
    if not user:
        await message.answer("Сначала пройдите регистрацию через /start")
        return

    await state.set_state(ProfileStates.waiting_for_edit_field)
    await message.answer(
        f"{_profile_text(user)}\n\nЧто хотите изменить?",
        reply_markup=profile_edit_field_keyboard(),
    )


@router.message(ProfileStates.waiting_for_edit_field, ~F.text.in_({"Назад", "↩️ Назад"}))
async def profile_pick_field(message: Message, state: FSMContext, api: ApiClient) -> None:
    text = (message.text or "").strip()
    mapping = {
        "Обращение": "salutation",
        "🤵 Обращение": "salutation",
        "ФИО": "full_name",
        "🪪 ФИО": "full_name",
        "Статус по пропуску": "affiliation",
        "🎓 Статус по пропуску": "affiliation",
        "Роль": "preferred_roles",
        "🎭 Роль": "preferred_roles",
        "Никнейм": "nickname",
        "🏷️ Никнейм": "nickname",
    }
    field = mapping.get(text)
    if not field:
        await message.answer("Выберите поле кнопкой.")
        return

    await state.update_data(profile_edit_field=field)
    await state.set_state(ProfileStates.waiting_for_new_value)
    if field == "salutation":
        await message.answer("Выберите обращение:", reply_markup=salutation_keyboard())
    elif field == "affiliation":
        await message.answer(
            "Выберите актуальный статус:",
            reply_markup=affiliation_keyboard(),
        )
    elif field == "preferred_roles":
        user = await api.get_profile(message.from_user.id)
        can_play = bool(user and user.get("can_play"))
        can_staff = bool(user and user.get("can_staff"))
        await state.update_data(pref_can_play=can_play, pref_can_staff=can_staff)
        await message.answer(
            "Отметьте нужные роли и нажмите «Готово»:",
            reply_markup=preferred_roles_select_keyboard(can_play=can_play, can_staff=can_staff),
        )
    elif field == "full_name":
        await message.answer("Введите новое ФИО:")
    else:
        await message.answer("Введите новый никнейм:")


@router.message(ProfileStates.waiting_for_new_value, ~F.text.in_({"Назад", "↩️ Назад"}))
async def profile_save_value(message: Message, state: FSMContext, api: ApiClient) -> None:
    tg_id = message.from_user.id
    user = await api.get_profile(tg_id)
    if not user:
        await state.clear()
        await message.answer("Сначала пройдите регистрацию через /start")
        return

    data = await state.get_data()
    field = data.get("profile_edit_field")
    raw = (message.text or "").strip()
    if field not in {"salutation", "full_name", "affiliation", "nickname"}:
        await state.clear()
        await message.answer("Поле не выбрано. Начните заново.")
        return

    value = raw
    if field == "salutation":
        salutation_map = {
            "господин": "господин",
            "🤵 господин": "господин",
            "госпожа": "госпожа",
            "👒 госпожа": "госпожа",
        }
        value = salutation_map.get(raw.lower(), "")
        if not value:
            await message.answer("Выберите обращение кнопкой: «Господин» или «Госпожа».")
            return
    elif field == "full_name":
        value = validate_full_name(raw) or ""
        if not value:
            await message.answer(
                "ФИО должно состоять ровно из 3 слов на русском языке (Фамилия Имя Отчество), "
                "только буквы, без цифр, латиницы и лишних символов. Попробуйте ещё раз."
            )
            return
    elif field == "affiliation":
        affiliation_map = {
            "С ВМК": "vmk",
            "🎓 С ВМК": "vmk",
            "Из МГУ, пропуск не нужен": "mgu_no_pass",
            "🏛️ Из МГУ, пропуск не нужен": "mgu_no_pass",
            "Вне МГУ, нужен пропуск": "outside_need_pass",
            "🪪 Вне МГУ, нужен пропуск": "outside_need_pass",
        }
        value = affiliation_map.get(raw, "")
        if not value:
            await message.answer("Выберите статус одной из кнопок.")
            return
    elif field == "nickname":
        value = validate_nickname(raw) or ""
        if not value or len(value) < 3 or len(value) > 32:
            await message.answer(
                "Никнейм должен быть от 3 до 32 символов, только русские или латинские буквы, "
                "без цифр и других символов."
            )
            return

    try:
        refreshed = await api.update_profile(tg_id, **{field: value})
    except ConflictError:
        await message.answer("Такой никнейм уже занят. Введите другой.")
        return

    await state.clear()
    await message.answer(
        f"Профиль обновлён ✅\n\n{_profile_text(refreshed)}",
        reply_markup=main_keyboard(is_admin=refreshed["is_bot_admin"]),
    )


@router.callback_query(ProfileStates.waiting_for_new_value, F.data.startswith("prefrole_toggle:"))
async def profile_toggle_preferred_role(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if data.get("profile_edit_field") != "preferred_roles":
        await callback.answer()
        return
    role = callback.data.split(":")[1]
    can_play = bool(data.get("pref_can_play", False))
    can_staff = bool(data.get("pref_can_staff", False))
    if role == "player":
        can_play = not can_play
    elif role == "staff":
        can_staff = not can_staff
    else:
        await callback.answer()
        return
    await state.update_data(pref_can_play=can_play, pref_can_staff=can_staff)
    try:
        await callback.message.edit_reply_markup(
            reply_markup=preferred_roles_select_keyboard(can_play=can_play, can_staff=can_staff)
        )
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            raise
    await callback.answer()


@router.callback_query(ProfileStates.waiting_for_new_value, F.data == "prefrole_confirm")
async def profile_confirm_preferred_roles(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    data = await state.get_data()
    if data.get("profile_edit_field") != "preferred_roles":
        await callback.answer()
        return
    can_play = bool(data.get("pref_can_play", False))
    can_staff = bool(data.get("pref_can_staff", False))
    if not (can_play or can_staff):
        await callback.answer("Выберите хотя бы одну роль.", show_alert=True)
        return

    tg_id = callback.from_user.id
    user = await api.get_profile(tg_id)
    if not user:
        await callback.answer("Пользователь не найден.", show_alert=True)
        return
    refreshed = await api.update_profile(tg_id, can_play=can_play, can_staff=can_staff)
    await state.clear()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass
    await callback.message.answer(
        f"Профиль обновлён ✅\n\n{_profile_text(refreshed)}",
        reply_markup=main_keyboard(is_admin=refreshed["is_bot_admin"]),
    )
    await callback.answer()
