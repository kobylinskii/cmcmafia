from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.api_client import ApiClient
from app.keyboards.reply import admin_menu_keyboard, main_keyboard, request_contact_keyboard
from app.states import AdminStates, RegistrationStates

router = Router(name="common")


@router.message(Command("start"))
async def start_handler(message: Message, state: FSMContext, api: ApiClient) -> None:
    tg_id = message.from_user.id
    await state.clear()

    user = await api.get_profile(tg_id, telegram_username=message.from_user.username)
    if user:
        is_admin = user["is_bot_admin"]
        await message.answer(
            "Вы уже зарегистрированы ✅ Используйте меню ниже.",
            reply_markup=main_keyboard(is_admin=is_admin),
        )
        return

    await message.answer(
        "Добро пожаловать в бота записи на игры Мафии! 🎭\n"
        "Для начала зарегистрируйтесь — поделитесь своим номером телефона.",
        reply_markup=request_contact_keyboard(),
    )
    await state.set_state(RegistrationStates.waiting_for_contact)


@router.message(F.text.in_({"Назад", "↩️ Назад"}))
async def back_to_main_handler(message: Message, state: FSMContext, api: ApiClient) -> None:
    current_state = await state.get_state()
    await state.clear()
    user = await api.get_profile(message.from_user.id)
    is_admin = bool(user and user["is_bot_admin"])
    if current_state and current_state.startswith(f"{AdminStates.__name__}:") and is_admin:
        await message.answer("Админ-меню 🛠️", reply_markup=admin_menu_keyboard())
        return
    await message.answer("Главное меню 🧭", reply_markup=main_keyboard(is_admin=is_admin))


@router.message()
async def fallback_handler(message: Message) -> None:
    await message.answer("Используйте меню или команду /start.")
