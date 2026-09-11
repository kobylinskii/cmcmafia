import asyncio
import contextlib
import logging

import socket

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import ErrorEvent

from app import commands
from app.api_client import ApiClient
from app.config import Config, load_config
from app.handlers import setup_routers
from app.notifier import notifier_loop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Ошибки Telegram, которые не являются багом бота и не требуют ни трейсбека в
# логах, ни какой-либо реакции: пользователь нажал кнопку из уже устаревшего
# сообщения, либо повторно нажал кнопку, не изменившую содержимое экрана.
BENIGN_TELEGRAM_ERRORS = (
    "query is too old",
    "message is not modified",
    "message to delete not found",
    "message to edit not found",
)


def build_storage(config: Config):
    """FSM-хранилище.

    По умолчанию -- Redis: на MemoryStorage любая незавершённая регистрация
    молча терялась при каждом рестарте бота, а вместе с ней и ссылка на
    текущий экран, из-за чего в чате оставалось висеть сообщение с рабочими
    кнопками, которое бот больше не мог ни отредактировать, ни удалить.
    Пустой REDIS_URL -- осознанный выбор для локального запуска без Redis.
    """
    if not config.redis_url:
        logger.warning("REDIS_URL не задан: состояние диалогов не переживёт рестарт бота")
        return MemoryStorage()
    return RedisStorage.from_url(config.redis_url)


async def main() -> None:
    config = load_config()
    api = ApiClient(base_url=config.api_base_url, service_token=config.bot_service_token)
    # Только IPv6 -- это не предпочтение, а единственный рабочий путь.
    # api.telegram.org отдаёт и A, и AAAA, но IPv4-адрес (149.154.166.110) с
    # российского хостинга не отвечает вовсе: соединение висит до таймаута.
    # IPv6 при этом отвечает за 0.14 секунды.
    #
    # Без этой строки aiohttp честно пробует оба адреса, и каждый запрос к
    # Telegram начинается с ожидания мёртвого IPv4. При старте бот на этом
    # падал: set_my_commands не укладывался в таймаут, и контейнер уходил в
    # цикл перезапусков.
    #
    # Сам IPv6 в контейнере появляется из сети telegram6 (docker-compose.yml):
    # обычная docker-сеть его не даёт.
    session = AiohttpSession()
    session._connector_init["family"] = socket.AF_INET6
    bot = Bot(token=config.bot_token, session=session)
    dp = Dispatcher(storage=build_storage(config))

    dp["config"] = config
    dp["api"] = api

    setup_routers(dp)

    @dp.errors()
    async def handle_benign_telegram_errors(event: ErrorEvent) -> bool:
        exc = event.exception
        if isinstance(exc, TelegramBadRequest) and any(
            marker in str(exc).lower() for marker in BENIGN_TELEGRAM_ERRORS
        ):
            logger.debug("Игнорируем безобидную ошибку Telegram: %s", exc)
            return True
        raise exc

    # Нижнего меню у бота больше нет: разделы открываются инлайн-кнопками, а
    # с пустого чата -- вот этими командами (см. app/commands.py).
    await commands.setup_default_commands(bot)

    notifier = asyncio.create_task(
        notifier_loop(bot, api, interval_seconds=config.confirmation_poll_seconds)
    )
    logger.info("Bot started")
    try:
        await dp.start_polling(bot)
    finally:
        notifier.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await notifier
        await api.close()
        await bot.session.close()
        logger.info("Bot stopped")


if __name__ == "__main__":
    asyncio.run(main())
