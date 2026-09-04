import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import ErrorEvent

from app.api_client import ApiClient
from app.config import load_config
from app.handlers import setup_routers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Сообщения об ошибках Telegram, которые не являются багом бота и не требуют
# ни трейсбека в логах, ни какой-либо реакции: пользователь нажал на кнопку из
# уже устаревшего сообщения, либо повторно нажал кнопку, не изменившую контент.
BENIGN_TELEGRAM_ERRORS = (
    "query is too old",
    "message is not modified",
)


async def main() -> None:
    config = load_config()
    api = ApiClient(base_url=config.api_base_url, service_token=config.bot_service_token)
    bot = Bot(token=config.bot_token)
    dp = Dispatcher()

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

    logger.info("Bot started")
    try:
        await dp.start_polling(bot)
    finally:
        await api.close()
        logger.info("Bot stopped")


if __name__ == "__main__":
    asyncio.run(main())
