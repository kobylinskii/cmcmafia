"""Команды в синей кнопке «Меню» рядом с полем ввода.

Появились вместе с отказом от нижней клавиатуры: раздел надо как-то открывать
и с пустого чата, а команда -- единственный способ сделать это, ничего не
оставив в истории (Telegram показывает их отдельным списком, а не сообщением).

Админский /admin выдаётся точечно, скоупом на конкретный чат: в общем списке
он путал бы игроков, у которых прав нет и не будет.
"""

from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

logger = logging.getLogger(__name__)

COMMON_COMMANDS: list[BotCommand] = [
    BotCommand(command="menu", description="🏠 Главное меню"),
    BotCommand(command="games", description="📝 Запись на игры"),
    BotCommand(command="my", description="📋 Мои регистрации"),
    BotCommand(command="profile", description="👤 Профиль"),
    BotCommand(command="help", description="❓ Что умеет бот"),
]

ADMIN_COMMAND = BotCommand(command="admin", description="🛠️ Админ-меню")


async def setup_default_commands(bot: Bot) -> None:
    await bot.set_my_commands(COMMON_COMMANDS, scope=BotCommandScopeDefault())


async def sync_chat_commands(bot: Bot, chat_id: int, *, is_admin: bool) -> None:
    """Подогнать список команд под права конкретного человека.

    Вызывается на /start: права могли и появиться, и пропасть, а список команд
    Telegram кэширует у клиента до следующей установки.
    """
    commands = COMMON_COMMANDS + ([ADMIN_COMMAND] if is_admin else [])
    try:
        await bot.set_my_commands(commands, scope=BotCommandScopeChat(chat_id=chat_id))
    except Exception:
        # Список команд -- удобство, а не условие работы бота: упасть на нём
        # значит не пустить человека в /start вообще.
        logger.info("Не удалось обновить команды для чата %s", chat_id, exc_info=True)
