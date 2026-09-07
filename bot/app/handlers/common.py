"""Вход в бота и главный экран.

Роутер подключается ПОСЛЕДНИМ: в нём живёт catch-all, который иначе перехватил
бы ввод текста в чужих состояниях.

Главное меню теперь инлайновое и живёт в том же единственном экране, что и все
разделы: нижняя reply-клавиатура на каждое нажатие слала в чат текст с
названием раздела, и история диалога состояла в основном из «👤 Профиль» и
«📋 Мои регистрации», написанных самим человеком.
"""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app import commands
from app.api_client import ApiClient
from app.keyboards.inline import main_menu_keyboard, menu_only_keyboard
from app.keyboards.reply import request_contact_keyboard
from app.states import RegistrationStates
from app.ui import consume_input, edit_screen, hide_reply_keyboard, open_screen

router = Router(name="common")

GREETING = (
    "Бот клуба спортивной мафии ВМК. 🎭\n\n"
    "Запись на игры, свои регистрации, профиль для сайта.\n"
    "Чтобы начать, поделитесь номером телефона кнопкой ниже."
)

HELP_TEXT = (
    "Что умеет бот:\n\n"
    "📝 Запись на игры — формат, день, игра. На собранный стол запись ставит "
    "в резерв; освободится место — бот запишет и напишет.\n"
    "📋 Мои регистрации — состав игры и отмена записи.\n"
    "👤 Профиль — ваши данные, анкета для сайта, статистика.\n\n"
    "Кнопки ниже или команды: /menu, /games, /my, /profile."
)


def status_note(user: dict) -> str:
    """Строка о модерации для главного экрана.

    Показывается только пока решение не принято или заявка отклонена:
    подтверждённому игроку напоминать не о чем.
    """
    status = user.get("confirmation_status")
    if status == "pending":
        return (
            "\n\n⏳ Заявка на проверке у администратора. "
            "Записываться на игры уже можно; в рейтинге на сайте появитесь после подтверждения."
        )
    if status == "rejected":
        reason = user.get("rejection_reason") or "без указания причины"
        return (
            f"\n\n⛔ Заявка отклонена: {reason}\n"
            "Поправьте данные в профиле и отправьте на повторную проверку."
        )
    return ""


def menu_text(user: dict) -> str:
    return f"🎭 Клуб спортивной мафии\n\nС возвращением, {user['nickname']}!{status_note(user)}"


async def require_profile(message: Message, state: FSMContext, api: ApiClient) -> dict | None:
    """Профиль действующего пользователя либо приглашение завести его."""
    user = await api.get_profile(message.from_user.id)
    if user is None:
        await message.answer(GREETING, reply_markup=request_contact_keyboard())
        await state.set_state(RegistrationStates.waiting_for_contact)
        return None
    return user


async def show_menu(message: Message, state: FSMContext, api: ApiClient) -> None:
    user = await require_profile(message, state, api)
    if user is None:
        return
    await state.set_state(None)
    await open_screen(message, state, menu_text(user), main_menu_keyboard(is_admin=user["is_bot_admin"]))


@router.message(CommandStart())
async def start_handler(message: Message, state: FSMContext, api: ApiClient, bot: Bot) -> None:
    await state.clear()
    await consume_input(message)
    user = await api.get_profile(message.from_user.id, telegram_username=message.from_user.username)

    if user is None:
        await message.answer(GREETING, reply_markup=request_contact_keyboard())
        await state.set_state(RegistrationStates.waiting_for_contact)
        return

    # У всех, кто застал прошлую версию бота, внизу висит меню из четырёх
    # кнопок. Само оно не исчезнет: reply-клавиатура живёт, пока её явно не
    # снимут, и её кнопки продолжали бы слать текст в чат.
    await hide_reply_keyboard(message)
    await commands.sync_chat_commands(bot, message.chat.id, is_admin=user["is_bot_admin"])
    await open_screen(message, state, menu_text(user), main_menu_keyboard(is_admin=user["is_bot_admin"]))


@router.message(Command("menu"))
async def menu_command(message: Message, state: FSMContext, api: ApiClient) -> None:
    await consume_input(message)
    await show_menu(message, state, api)


@router.callback_query(F.data == "mn:menu")
async def back_to_menu(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    user = await api.get_profile(callback.from_user.id)
    if user is None:
        await callback.answer("Профиль не найден, начните с /start.", show_alert=True)
        return
    await state.set_state(None)
    await edit_screen(callback, state, menu_text(user), main_menu_keyboard(is_admin=user["is_bot_admin"]))


@router.message(Command("help"))
async def help_handler(message: Message, state: FSMContext) -> None:
    await consume_input(message)
    await open_screen(message, state, HELP_TEXT, menu_only_keyboard())


@router.message(F.text)
async def fallback_handler(message: Message, state: FSMContext, api: ApiClient) -> None:
    """Любой текст вне диалога.

    Раньше здесь была отбивка «используйте меню», после которой в чате
    оставались и сообщение человека, и ответ бота. Теперь набранное убирается,
    а человек просто получает главный экран -- ровно то, чего он и добивался.
    """
    await consume_input(message)
    await show_menu(message, state, api)
