from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/mafia"

    # Railway (и Heroku, и Render) выдают DATABASE_URL со схемой `postgresql://`
    # или даже устаревшей `postgres://`. SQLAlchemy с драйвером psycopg3 требует
    # явного `postgresql+psycopg://`, иначе подхватывает несуществующий psycopg2
    # и падает на старте. Нормализуем схему здесь, чтобы переменную из плагина
    # БД можно было прокинуть в сервис как есть.
    @field_validator("database_url", mode="before")
    @classmethod
    def _normalize_db_scheme(cls, value: str) -> str:
        if not isinstance(value, str):
            return value
        for prefix in ("postgresql+psycopg://", "postgresql+psycopg2://", "sqlite"):
            if value.startswith(prefix):
                return value
        if value.startswith("postgres://"):
            return "postgresql+psycopg://" + value[len("postgres://") :]
        if value.startswith("postgresql://"):
            return "postgresql+psycopg://" + value[len("postgresql://") :]
        return value

    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_access_ttl_seconds: int = 15 * 60
    jwt_refresh_ttl_seconds: int = 7 * 24 * 60 * 60

    bot_service_token: str

    redis_url: str = "redis://localhost:6379/0"

    cors_origins: list[str] = ["http://localhost:3000"]

    media_root: str = "./media/players"
    max_photo_bytes: int = 5 * 1024 * 1024

    cookie_secure: bool = True
    cookie_domain: str | None = None
    # "lax" достаточно, когда сайт и API на одном registrable-домене
    # (site.ru + api.site.ru). Если фронт и бэкенд разнесены на разные домены
    # (например, два разных *.up.railway.app), браузер в межсайтовом запросе
    # отдаёт куку сессии только при samesite="none" (и обязательно secure=true).
    cookie_samesite: str = "lax"

    login_max_attempts: int = 5
    login_lockout_minutes: int = 15

    # Bootstrap-права бот-админа: значения должны совпадать с ADMIN_PHONE/SUPERADMIN_IDS
    # в .env бота (см. app/services/bootstrap_admin_service.py). Раньше эта проверка
    # жила в самом боте и писала в БД без какой-либо авторизации; чтобы то же
    # самопожалование прав не превратилось в дыру при переходе на API (см.
    # ARCHITECTURE.md, модель доверия бот-API), она перенесена сюда и применяется
    # только сервером при регистрации/входе игрока.
    # Простые строковые поля -- намеренно, чтобы не зависеть от того, как
    # pydantic-settings парсит комплексные типы (frozenset/list) из env: там
    # значение "999" или "999,1000" JSON-парсится по-разному в зависимости от
    # формата и легко ломается при однозначном айди без запятой.
    superadmin_telegram_ids_raw: str = ""
    bootstrap_admin_phone_raw: str = ""

    @property
    def superadmin_telegram_ids(self) -> frozenset[int]:
        return frozenset(
            int(part) for part in self.superadmin_telegram_ids_raw.split(",") if part.strip().lstrip("-").isdigit()
        )

    @property
    def bootstrap_admin_phone(self) -> str | None:
        digits = "".join(ch for ch in self.bootstrap_admin_phone_raw if ch.isdigit())
        return digits or None


@lru_cache
def get_settings() -> Settings:
    return Settings()
