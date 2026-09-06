"""Регистрация нового игрока: шесть шагов в одном сообщении.

Шаги идут строго по порядку и живут в одном экране, который перерисовывается
на каждом ответе. Раньше каждый шаг присылал новое сообщение со своей
reply-клавиатурой, и человек мог вернуться к любому прошлому шагу, нажав
кнопку выше по истории, -- отсюда и «залипшие» кнопки, и наполовину
заполненные анкеты.

Единственный способ выйти из середины регистрации -- «Начать заново»: без
профиля в системе показывать главное меню нечего.
"""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app import commands, texts
from app.api_client import ApiClient, ApiError, ConflictError
from app.keyboards.inline import (
    affiliation_keyboard,
    main_menu_keyboard,
    preferred_roles_keyboard,
    restart_registration_keyboard,
    salutation_keyboard,
)
from app.keyboards.reply import request_contact_keyboard
from app.states import RegistrationStates
from app.ui import (
    consume_input,
    drop_screen,
    edit_screen,
    hide_reply_keyboard,
    open_screen,
    screen_message,
)
from app.utils import validate_full_name, validate_nickname

router = Router(name="registration")

STEP_SALUTATION = "Шаг 2 из 6. Как к вам обращаться?"
STEP_FULL_NAME = (
    "Шаг 3 из 6. Введите ФИО полностью — Фамилия Имя Отчество.\n\n"
    "Оно нужно для заказа пропусков, поэтому должно совпадать с документом."
)
STEP_AFFILIATION = "Шаг 4 из 6. Нужен ли вам пропуск на факультет?"
STEP_ROLES = (
    "Шаг 5 из 6. За кого вы хотите играть? Можно выбрать оба варианта.\n\n"
    "От этого зависит, на какие места в играх вас будет пускать запись."
)
STEP_NICKNAME = (
    "Шаг 6 из 6. Придумайте никнейм — он будет виден в составах игр и в рейтинге.\n\n"
    "От 3 до 32 букв, без цифр и знаков."
)


@router.callback_query(F.data == "nr:restart")
async def restart_registration(callback: CallbackQuery, state: FSMContext) -> None:
    message = screen_message(callback)
    if message is None:
        await callback.answer("Начните заново командой /start.", show_alert=True)
        return
    await state.clear()
    await edit_screen(callback, state, "Начинаем заново.")
    await drop_screen(state)
    await message.answer(
        "Шаг 1 из 6. Поделитесь номером телефона кнопкой ниже.",
        reply_markup=request_contact_keyboard(),
    )
    await state.set_state(RegistrationStates.waiting_for_contact)


@router.message(RegistrationStates.waiting_for_contact, F.contact)
async def contact_received(message: Message, state: FSMContext) -> None:
    if message.contact.user_id and message.contact.user_id != message.from_user.id:
        await message.answer(
            "Это чужой контакт. Нажмите кнопку ниже, чтобы отправить свой номер.",
            reply_markup=request_contact_keyboard(),
        )
        return

    await state.update_data(phone=message.contact.phone_number)
    await state.set_state(RegistrationStates.filling_details)
    # Клавиатуру запроса контакта убираем сразу: она одноразовая по смыслу, а
    # висела до конца регистрации и предлагала отправить номер ещё раз.
    # Карточку контакта из чата тоже убираем -- в ней виден номер телефона,
    # и висеть в истории ей незачем.
    await hide_reply_keyboard(message)
    await consume_input(message)
    await open_screen(message, state, STEP_SALUTATION, salutation_keyboard("nr"))


@router.message(RegistrationStates.waiting_for_contact)
async def contact_required(message: Message) -> None:
    await message.answer(
        "Нужен номер телефона — отправьте его кнопкой «Поделиться номером телефона».",
        reply_markup=request_contact_keyboard(),
    )


@router.callback_query(RegistrationStates.filling_details, F.data.startswith("nr:salutation:"))
async def salutation_chosen(callback: CallbackQuery, state: FSMContext) -> None:
    salutation = callback.data.split(":")[2]
    if salutation not in texts.SALUTATIONS:
        await callback.answer("Неизвестный вариант.", show_alert=True)
        return
    await state.update_data(salutation=salutation)
    await edit_screen(callback, state, STEP_FULL_NAME, restart_registration_keyboard())


@router.message(RegistrationStates.filling_details)
async def full_name_received(message: Message, state: FSMContext) -> None:
    """Текст на шагах 2-5 -- это всегда ФИО: остальные три шага отвечают
    кнопками. Если ФИО уже введено, значит человек пишет не туда -- показываем
    ему тот шаг, на котором он на самом деле стоит."""
    await consume_input(message)
    data = await state.get_data()
    if not data.get("salutation"):
        await open_screen(message, state, STEP_SALUTATION, salutation_keyboard("nr"))
        return
    if data.get("full_name"):
        if not data.get("affiliation"):
            await open_screen(message, state, STEP_AFFILIATION, affiliation_keyboard("nr"))
        else:
            await open_screen(
                message,
                state,
                STEP_ROLES,
                preferred_roles_keyboard(
                    "nr", can_play=bool(data.get("can_play")), can_staff=bool(data.get("can_staff"))
                ),
            )
        return

    full_name = validate_full_name(message.text or "")
    if not full_name:
        await open_screen(
            message,
            state,
            "ФИО должно состоять ровно из трёх слов на русском языке "
            "(Фамилия Имя Отчество), только буквы.\n\n" + STEP_FULL_NAME,
            restart_registration_keyboard(),
        )
        return

    await state.update_data(full_name=full_name, can_play=False, can_staff=False)
    await open_screen(message, state, STEP_AFFILIATION, affiliation_keyboard("nr"))


@router.callback_query(RegistrationStates.filling_details, F.data.startswith("nr:affiliation:"))
async def affiliation_chosen(callback: CallbackQuery, state: FSMContext) -> None:
    affiliation = callback.data.split(":")[2]
    if affiliation not in texts.AFFILIATIONS:
        await callback.answer("Неизвестный вариант.", show_alert=True)
        return
    await state.update_data(affiliation=affiliation)
    await edit_screen(
        callback, state, STEP_ROLES, preferred_roles_keyboard("nr", can_play=False, can_staff=False)
    )


@router.callback_query(RegistrationStates.filling_details, F.data.startswith("nr:toggle:"))
async def toggle_role(callback: CallbackQuery, state: FSMContext) -> None:
    role = callback.data.split(":")[2]
    data = await state.get_data()
    can_play, can_staff = bool(data.get("can_play")), bool(data.get("can_staff"))
    if role == "player":
        can_play = not can_play
    elif role == "staff":
        can_staff = not can_staff
    else:
        await callback.answer()
        return
    await state.update_data(can_play=can_play, can_staff=can_staff)
    await edit_screen(
        callback, state, STEP_ROLES, preferred_roles_keyboard("nr", can_play=can_play, can_staff=can_staff)
    )


@router.callback_query(RegistrationStates.filling_details, F.data == "nr:save")
async def roles_saved(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if not (data.get("can_play") or data.get("can_staff")):
        await callback.answer("Выберите хотя бы один вариант.", show_alert=True)
        return
    await state.set_state(RegistrationStates.waiting_for_nickname)
    await edit_screen(callback, state, STEP_NICKNAME, restart_registration_keyboard())


@router.message(RegistrationStates.waiting_for_nickname)
async def nickname_received(message: Message, state: FSMContext, api: ApiClient, bot: Bot) -> None:
    await consume_input(message)
    nickname = validate_nickname(message.text or "")
    if not nickname or not (3 <= len(nickname) <= 32):
        await open_screen(
            message,
            state,
            "Никнейм должен быть от 3 до 32 символов и состоять только из русских "
            "или латинских букв.\n\n" + STEP_NICKNAME,
            restart_registration_keyboard(),
        )
        return

    data = await state.get_data()
    missing = [key for key in ("phone", "salutation", "full_name", "affiliation") if not data.get(key)]
    if missing or not (data.get("can_play") or data.get("can_staff")):
        # Состояние могло разъехаться, если бот обновляли посреди диалога.
        await open_screen(
            message,
            state,
            "Часть данных потерялась. Давайте пройдём регистрацию заново.",
            restart_registration_keyboard(),
        )
        return

    try:
        user = await api.register_player(
            telegram_id=message.from_user.id,
            telegram_username=message.from_user.username,
            phone=data["phone"],
            nickname=nickname,
            salutation=data["salutation"],
            full_name=data["full_name"],
            affiliation=data["affiliation"],
            can_play=bool(data.get("can_play")),
            can_staff=bool(data.get("can_staff")),
        )
    except ConflictError as exc:
        # Конфликтов у регистрации три (ник, телефон, аккаунт), и раньше все
        # они показывались как «ник занят»: человек, у которого уже был
        # профиль, до бесконечности придумывал новые ники.
        if "ник" in exc.message.lower():
            await open_screen(message, state, f"{exc.message}. Попробуйте другой.\n\n" + STEP_NICKNAME)
            return
        await state.clear()
        await open_screen(message, state, f"{exc.message}.\n\nЕсли это ошибка — напишите администратору.")
        return
    except ApiError as exc:
        await open_screen(
            message, state, f"Не удалось завершить регистрацию: {exc.message}", restart_registration_keyboard()
        )
        return

    await state.clear()
    await commands.sync_chat_commands(bot, message.chat.id, is_admin=user["is_bot_admin"])
    admin_note = "\n\n🛠️ Вам выданы права администратора бота." if user["is_bot_admin"] else ""
    await open_screen(
        message,
        state,
        f"Готово, {nickname}! 🎉\n\n"
        "⏳ Заявка ушла администратору на проверку. Записываться на игры можно уже сейчас — "
        f"в рейтинге на сайте вы появитесь после подтверждения.{admin_note}",
        main_menu_keyboard(is_admin=user["is_bot_admin"]),
    )
