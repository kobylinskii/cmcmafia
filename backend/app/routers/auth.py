from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from jose import JWTError
from sqlalchemy.orm import Session

from app import models, security
from app.config import get_settings
from app.database import get_db
from app.deps import ACCESS_COOKIE, CSRF_COOKIE, get_current_site_user, require_csrf
from app.rate_limit import limiter
from app.schemas.auth import LoginIn, LoginOut, PasswordChangeIn

router = APIRouter(prefix="/api/auth", tags=["auth"])
settings = get_settings()

REFRESH_COOKIE = "refresh_token"


def _set_auth_cookies(response: Response, player_id: int) -> None:
    access = security.create_access_token(player_id)
    refresh = security.create_refresh_token(player_id)
    csrf = security.generate_csrf_token()

    # SameSite=Lax, а не Strict. Strict не отдаёт куку ни при одном переходе,
    # инициированном извне: админ, пришедший по кнопке «Оценить игру» из бота
    # (ARCHITECTURE.md, раздел 8) или по ссылке из другой вкладки, всегда
    # попадал на форму логина, хотя сессия жива. От CSRF нас защищает не этот
    # флаг, а double-submit токен (см. app/deps.py: require_csrf), который Lax
    # никак не ослабляет: он по-прежнему не пускает межсайтовые POST/PUT/DELETE.
    common = dict(httponly=True, secure=settings.cookie_secure, samesite="lax", domain=settings.cookie_domain)
    response.set_cookie(ACCESS_COOKIE, access, max_age=settings.jwt_access_ttl_seconds, **common)
    response.set_cookie(REFRESH_COOKIE, refresh, max_age=settings.jwt_refresh_ttl_seconds, **common)
    response.set_cookie(
        CSRF_COOKIE,
        csrf,
        max_age=settings.jwt_refresh_ttl_seconds,
        httponly=False,
        secure=settings.cookie_secure,
        samesite="lax",
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


@router.post("/password")
@limiter.limit("5/minute")
def change_password(
    request: Request,
    response: Response,
    data: PasswordChangeIn,
    db: Session = Depends(get_db),
    user: models.Player = Depends(get_current_site_user),
    _: None = Depends(require_csrf),
) -> dict:
    """Смена собственного пароля.

    Единственный способ сменить пароль раньше -- перевыдать случайный временный
    через админку или запустить CLI-скрипт на сервере; задать себе постоянный
    пароль из интерфейса было нельзя.

    Текущий пароль спрашивается обязательно: cookie-сессия живёт неделю, и без
    этой проверки любой доступ к незалоченному чужому браузеру означал бы
    молчаливый захват учётной записи.
    """
    if not user.site_password_hash:
        raise HTTPException(400, "У этой учётной записи нет пароля для входа на сайт")

    if not security.verify_password(data.current_password, user.site_password_hash):
        # Считаем неудачную попытку так же, как при входе: иначе этот эндпоинт
        # становится способом перебирать пароль в обход блокировки на /login.
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= settings.login_max_attempts:
            user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=settings.login_lockout_minutes)
            user.failed_login_attempts = 0
        db.commit()
        raise HTTPException(400, "Текущий пароль указан неверно")

    if data.new_password == data.current_password:
        raise HTTPException(422, "Новый пароль совпадает со старым")

    user.site_password_hash = security.hash_password(data.new_password)
    user.failed_login_attempts = 0
    user.locked_until = None
    db.commit()

    # Выдаём свежую пару токенов: пароль сменился, сессию логично начать заново,
    # а пользователь при этом остаётся залогиненным и не теряет вкладку.
    _set_auth_cookies(response, user.id)
    return {"ok": True}


@router.get("/me", response_model=LoginOut)
def me(user: models.Player = Depends(get_current_site_user)) -> LoginOut:
    return LoginOut(nickname=user.nickname, is_site_admin=user.is_site_admin)
