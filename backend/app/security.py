from __future__ import annotations

import hmac
import secrets
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from jose import JWTError, jwt

from app.config import get_settings

settings = get_settings()
_hasher = PasswordHasher()


def hash_password(raw: str) -> str:
    return _hasher.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, raw)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


def generate_temp_password(length: int = 16) -> str:
    return secrets.token_urlsafe(length)


# Хеш заведомо недостижимого пароля: считается один раз на старте и служит
# только для выравнивания времени ответа (см. burn_password_time).
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(32))


def burn_password_time(raw: str) -> None:
    """Потратить столько же времени, сколько стоила бы проверка пароля.

    Логин при неизвестном username возвращался мгновенно, а при известном --
    после argon2, то есть на порядок медленнее. Разница во времени ответа
    выдавала существующие учётки, и лимит 5/мин её не закрывал: он ограничивает
    подбор ПАРОЛЯ, а перебор ЛОГИНОВ по таймингу шёл мимо него.
    """
    verify_password(raw, _DUMMY_HASH)


def _create_token(subject: str, ttl_seconds: int, token_type: str, extra: dict | None = None) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "type": token_type,
        "iat": now,
        "exp": now + timedelta(seconds=ttl_seconds),
        "jti": secrets.token_hex(16),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(player_id: int) -> str:
    return _create_token(str(player_id), settings.jwt_access_ttl_seconds, "access")


def create_refresh_token(player_id: int) -> str:
    return _create_token(str(player_id), settings.jwt_refresh_ttl_seconds, "refresh")


def decode_token(token: str, expected_type: str) -> dict:
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    if payload.get("type") != expected_type:
        raise JWTError("unexpected token type")
    return payload


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def csrf_tokens_match(cookie_value: str | None, header_value: str | None) -> bool:
    if not cookie_value or not header_value:
        return False
    return hmac.compare_digest(cookie_value, header_value)


def bot_token_matches(provided: str | None) -> bool:
    if not provided:
        return False
    return hmac.compare_digest(provided, settings.bot_service_token)
