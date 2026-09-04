from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.api_client import ApiClient, ConflictError
from app.keyboards.inline import preferred_roles_select_keyboard
from app.keyboards.reply import (
    affiliation_keyboard,
    main_keyboard,
    request_contact_keyboard,
    salutation_keyboard,
)
from app.states import RegistrationStates
from app.utils import validate_full_name, validate_nickname

router = Router(name="registration")


@router.message(RegistrationStates.waiting_for_contact, ~F.contact)
async def contact_required_handler(message: Message) -> None:
    await message.answer(
        "Пожалуйста, используйте кнопку «Поделиться номером телефона». 📱",
        reply_markup=request_contact_keyboard(),
    )


@router.message(RegistrationStates.waiting_for_contact, F.contact)
async def contact_handler(message: Message, state: FSMContext) -> None:
    if message.contact.user_id and message.contact.user_id != message.from_user.id:
        await message.answer("Необходимо отправить свой номер телефона.")
        return

    await state.update_data(phone=message.contact.phone_number)
    await state.set_state(RegistrationStates.waiting_for_salutation)
    await message.answer(
        "Отлично! Как к вам обращаться?",
        reply_markup=salutation_keyboard(),
    )


@router.message(RegistrationStates.waiting_for_salutation)
async def salutation_handler(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip().lower()
    salutation_map = {
        "господин": "господин",
        "🤵 господин": "господин",
        "госпожа": "госпожа",
        "👒 госпожа": "госпожа",
    }
    salutation = salutation_map.get(text)
    if not salutation:
        await message.answer("Выберите обращение кнопкой: «Господин» или «Госпожа».")
        return

    await state.update_data(salutation=salutation)
    await state.set_state(RegistrationStates.waiting_for_full_name)
    await message.answer("Отлично! Теперь введите ваше ФИО.")


@router.message(RegistrationStates.waiting_for_full_name)
async def full_name_handler(message: Message, state: FSMContext) -> None:
    full_name = validate_full_name(message.text or "")
    if not full_name:
        await message.answer(
            "ФИО должно состоять ровно из 3 слов на русском языке (Фамилия Имя Отчество), "
            "только буквы, без цифр, латиницы и лишних символов. Попробуйте ещё раз."
        )
        return

    await state.update_data(full_name=full_name)
    await state.set_state(RegistrationStates.waiting_for_affiliation)
    await message.answer(
        "Укажите, пожалуйста, ваш статус по проходу:",
        reply_markup=affiliation_keyboard(),
    )


@router.message(RegistrationStates.waiting_for_affiliation)
async def affiliation_handler(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    affiliation_map = {
        "С ВМК": "vmk",
        "🎓 С ВМК": "vmk",
        "Из МГУ, пропуск не нужен": "mgu_no_pass",
        "🏛️ Из МГУ, пропуск не нужен": "mgu_no_pass",
        "Вне МГУ, нужен пропуск": "outside_need_pass",
        "🪪 Вне МГУ, нужен пропуск": "outside_need_pass",
    }
    affiliation = affiliation_map.get(text)
    if not affiliation:
        await message.answer(
            "Выберите один из вариантов кнопками:\n"
            "• С ВМК\n"
            "• Из МГУ, пропуск не нужен\n"
            "• Вне МГУ, нужен пропуск"
        )
        return

    await state.update_data(affiliation=affiliation, pref_can_play=False, pref_can_staff=False)
    await state.set_state(RegistrationStates.waiting_for_preferred_roles)
    await message.answer(
        "За какие роли хотите играть? Можно выбрать один или оба варианта, затем нажмите «Готово».",
        reply_markup=preferred_roles_select_keyboard(can_play=False, can_staff=False),
    )


@router.callback_query(RegistrationStates.waiting_for_preferred_roles, F.data.startswith("prefrole_toggle:"))
async def toggle_preferred_role(callback: CallbackQuery, state: FSMContext) -> None:
    role = callback.data.split(":")[1]
    data = await state.get_data()
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


@router.callback_query(RegistrationStates.waiting_for_preferred_roles, F.data == "prefrole_confirm")
async def confirm_preferred_roles(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    can_play = bool(data.get("pref_can_play", False))
    can_staff = bool(data.get("pref_can_staff", False))
    if not (can_play or can_staff):
        await callback.answer("Выберите хотя бы одну роль.", show_alert=True)
        return

    await state.update_data(can_play=can_play, can_staff=can_staff)
    await state.set_state(RegistrationStates.waiting_for_nickname)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass
    await callback.message.answer("Супер! Теперь придумайте и введите свой уникальный никнейм ✍️")
    await callback.answer()


@router.message(RegistrationStates.waiting_for_nickname)
async def nickname_handler(message: Message, state: FSMContext, api: ApiClient) -> None:
    nickname = validate_nickname(message.text or "")

    if not nickname or len(nickname) < 3 or len(nickname) > 32:
        await message.answer(
            "Никнейм должен содержать от 3 до 32 символов, только русские или латинские буквы, "
            "без цифр и других символов. Попробуйте ещё раз."
        )
        return

    data = await state.get_data()
    phone = data.get("phone")
    salutation = data.get("salutation")
    full_name = data.get("full_name")
    affiliation = data.get("affiliation")
    can_play = bool(data.get("can_play"))
    can_staff = bool(data.get("can_staff"))
    if not phone:
        await message.answer("Что-то пошло не так. Начните заново: /start")
        await state.clear()
        return
    if salutation not in {"господин", "госпожа"}:
        await message.answer("Обращение не выбрано. Начните заново: /start")
        await state.clear()
        return
    if not full_name:
        await message.answer("ФИО не найдено. Начните заново: /start")
        await state.clear()
        return
    if affiliation not in {"vmk", "mgu_no_pass", "outside_need_pass"}:
        await message.answer("Статус прохода не выбран. Начните заново: /start")
        await state.clear()
        return
    if not (can_play or can_staff):
        await message.answer("Не выбраны роли для игр. Начните заново: /start")
        await state.clear()
        return

    try:
        user = await api.register_player(
            telegram_id=message.from_user.id,
            telegram_username=message.from_user.username,
            phone=phone,
            nickname=nickname,
            salutation=salutation,
            full_name=full_name,
            affiliation=affiliation,
            can_play=can_play,
            can_staff=can_staff,
        )
    except ConflictError:
        await message.answer("Такой никнейм уже занят, либо вы уже регистрировались. Введите другой ник.")
        return

    await state.clear()
    is_admin = user["is_bot_admin"]
    await message.answer(
        f"Регистрация завершена! 🎉 Добро пожаловать, {salutation} {nickname}.",
        reply_markup=main_keyboard(is_admin=is_admin),
    )
    if is_admin:
        await message.answer("🛠️ Вы переведены в статус администратора.")
