import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    bot_token: str
    api_base_url: str
    bot_service_token: str


def load_config() -> Config:
    load_dotenv()
    bot_token = os.getenv("BOT_TOKEN", "").strip()
    api_base_url = os.getenv("API_BASE_URL", "").strip()
    bot_service_token = os.getenv("BOT_SERVICE_TOKEN", "").strip()

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
    )
