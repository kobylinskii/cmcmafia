from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from jose import JWTError
from sqlalchemy.orm import Session

from app import models, security
from app.database import get_db

ACCESS_COOKIE = "access_token"
CSRF_COOKIE = "csrf_token"
CSRF_HEADER = "X-CSRF-Token"


def get_current_site_user(request: Request, db: Session = Depends(get_db)) -> models.Player:
    token = request.cookies.get(ACCESS_COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Не авторизовано")
    try:
        payload = security.decode_token(token, "access")
    except JWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный или истёкший токен") from exc

    player = db.get(models.Player, int(payload["sub"]))
    if player is None or not player.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Пользователь не найден")
    return player


def require_csrf(request: Request) -> None:
    """Double-submit проверка для любого изменяющего запроса из браузера.

    Вынесена из require_site_admin: смена пароля доступна любому владельцу
    сайт-логина, а не только админу, но защищать её от CSRF нужно ровно так же.
    """
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    cookie_csrf = request.cookies.get(CSRF_COOKIE)
    header_csrf = request.headers.get(CSRF_HEADER)
    if not security.csrf_tokens_match(cookie_csrf, header_csrf):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Неверный CSRF-токен")


def require_site_admin(request: Request, user: models.Player = Depends(get_current_site_user)) -> models.Player:
    if not user.is_site_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Требуются права администратора сайта")
    require_csrf(request)
    return user


def require_bot_service(request: Request) -> None:
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.removeprefix("Bearer ").strip() if auth_header.startswith("Bearer ") else None
    if not security.bot_token_matches(token):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный сервисный токен бота")


def get_bot_actor(
    telegram_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_bot_service),
) -> models.Player:
    player = db.query(models.Player).filter(models.Player.telegram_id == telegram_id).one_or_none()
    if player is None or not player.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Игрок не найден")
    return player


def require_bot_admin_actor(actor: models.Player = Depends(get_bot_actor)) -> models.Player:
    if not actor.is_bot_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Требуются права администратора бота")
    return actor
