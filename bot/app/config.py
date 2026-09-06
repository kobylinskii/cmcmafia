import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Путь к .env задан явно, а не через find_dotenv(). find_dotenv() ищет файл,
# поднимаясь от каталога ВЫЗЫВАЮЩЕГО кадра стека -- то есть от app/, а не от
# корня бота. Лежащий рядом app/.env перекрывал корневой bot/.env целиком, и
# бот молча ходил по адресу API из него: все команды, которым нужен API,
# падали с 502, а работали только те, что до API не доходят.
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


@dataclass(frozen=True)
class Config:
    bot_token: str
    api_base_url: str
    bot_service_token: str
    # Пустая строка -- осознанный выбор MemoryStorage: локальный запуск без
    # поднятого Redis остаётся возможным, просто незавершённые диалоги не
    # переживут рестарт (см. bot.py, где storage и собирается).
    redis_url: str
    # Как часто бот забирает у API решения админа по заявкам на вступление
    # (см. app/notifier.py).
    confirmation_poll_seconds: int


def load_config() -> Config:
    load_dotenv(ENV_PATH)
    bot_token = os.getenv("BOT_TOKEN", "").strip()
    api_base_url = os.getenv("API_BASE_URL", "").strip()
    bot_service_token = os.getenv("BOT_SERVICE_TOKEN", "").strip()
    redis_url = os.getenv("REDIS_URL", "").strip()
    poll_raw = os.getenv("CONFIRMATION_POLL_SECONDS", "60").strip()

    if not bot_token:
        raise RuntimeError("BOT_TOKEN не задан в .env")
    if not api_base_url:
        raise RuntimeError("API_BASE_URL не задан в .env")
    if not bot_service_token:
        raise RuntimeError("BOT_SERVICE_TOKEN не задан в .env")

    return Config(
        bot_token=bot_token,
        api_base_url=api_base_url,
        bot_service_token=bot_service_token,
        redis_url=redis_url,
        confirmation_poll_seconds=max(15, int(poll_raw) if poll_raw.isdigit() else 60),
    )
