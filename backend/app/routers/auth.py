from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from jose import JWTError
from sqlalchemy.orm import Session

from app import models, security
from app.config import get_settings
from app.database import get_db
from app.deps import ACCESS_COOKIE, CSRF_COOKIE, get_current_site_user
from app.rate_limit import limiter
from app.schemas.auth import LoginIn, LoginOut

router = APIRouter(prefix="/api/auth", tags=["auth"])
settings = get_settings()

REFRESH_COOKIE = "refresh_token"


def _set_auth_cookies(response: Response, player_id: int) -> None:
    access = security.create_access_token(player_id)
    refresh = security.create_refresh_token(player_id)
    csrf = security.generate_csrf_token()

    common = dict(httponly=True, secure=settings.cookie_secure, samesite="strict", domain=settings.cookie_domain)
    response.set_cookie(ACCESS_COOKIE, access, max_age=settings.jwt_access_ttl_seconds, **common)
    response.set_cookie(REFRESH_COOKIE, refresh, max_age=settings.jwt_refresh_ttl_seconds, **common)
    response.set_cookie(
        CSRF_COOKIE,
        csrf,
        max_age=settings.jwt_refresh_ttl_seconds,
        httponly=False,
        secure=settings.cookie_secure,
        samesite="strict",
        domain=settings.cookie_domain,
    )


@router.post("/login", response_model=LoginOut)
@limiter.limit("5/minute")
def login(request: Request, response: Response, data: LoginIn, db: Session = Depends(get_db)) -> LoginOut:
    player = db.query(models.Player).filter(models.Player.site_username == data.username).one_or_none()

    generic_error = HTTPException(401, "Неверный логин или пароль")

    if player is None or not player.site_password_hash:
        raise generic_error

    if player.locked_until and player.locked_until > datetime.now(timezone.utc):
        raise HTTPException(423, "Аккаунт временно заблокирован из-за неудачных попыток входа")

    if not security.verify_password(data.password, player.site_password_hash):
        player.failed_login_attempts += 1
        if player.failed_login_attempts >= settings.login_max_attempts:
            player.locked_until = datetime.now(timezone.utc) + timedelta(minutes=settings.login_lockout_minutes)
            player.failed_login_attempts = 0
        db.commit()
        raise generic_error

    player.failed_login_attempts = 0
    player.locked_until = None
    player.last_login_at = datetime.now(timezone.utc)
    db.commit()

    _set_auth_cookies(response, player.id)
    return LoginOut(nickname=player.nickname, is_site_admin=player.is_site_admin)


@router.post("/refresh")
def refresh(request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise HTTPException(401, "Не авторизовано")
    try:
        payload = security.decode_token(token, "refresh")
    except JWTError as exc:
        raise HTTPException(401, "Неверный или истёкший токен") from exc

    player = db.get(models.Player, int(payload["sub"]))
    if player is None or not player.is_active:
        raise HTTPException(401, "Пользователь не найден")

    _set_auth_cookies(response, player.id)
    return {"ok": True}


@router.post("/logout")
def logout(response: Response, _: models.Player = Depends(get_current_site_user)) -> dict:
    for cookie in (ACCESS_COOKIE, REFRESH_COOKIE, CSRF_COOKIE):
        response.delete_cookie(cookie, domain=settings.cookie_domain)
    return {"ok": True}


@router.get("/me", response_model=LoginOut)
def me(user: models.Player = Depends(get_current_site_user)) -> LoginOut:
    return LoginOut(nickname=user.nickname, is_site_admin=user.is_site_admin)
