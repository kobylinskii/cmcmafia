from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.deps import get_bot_actor, require_bot_service
from app.rate_limit import limiter
from app.serializers import is_session_open, roster_to_out, session_to_out
from app.timeutil import club_day
from app.schemas.bot import (
    BotPlayerProfileOut,
    BotPlayerProfileUpdateIn,
    BotPlayerRegisterIn,
    MyRegistrationOut,
    RegisterIn,
    RegistrationOut,
    ReserveIn,
    RosterOut,
    SessionOut,
)
from app.services import admin_grant, bootstrap_admin_service, registration_service, slug_service
from app.services.registration_service import RegistrationError

router = APIRouter(prefix="/api/bot", tags=["bot"])


@router.post("/players/register", response_model=BotPlayerProfileOut)
@limiter.limit("20/minute")
def register_player(
    request: Request, data: BotPlayerRegisterIn, db: Session = Depends(get_db), _: None = Depends(require_bot_service)
) -> models.Player:
    if db.query(models.Player).filter(models.Player.telegram_id == data.telegram_id).first():
        raise HTTPException(409, "Этот Telegram-аккаунт уже зарегистрирован")
    if db.query(models.Player).filter(models.Player.nickname.ilike(data.nickname)).first():
        raise HTTPException(409, "Ник уже занят")

    slug = slug_service.suggest_slug(data.nickname, db)
    player = models.Player(
        telegram_id=data.telegram_id,
        telegram_username=data.telegram_username,
        phone=data.phone,
        nickname=data.nickname,
        slug=slug,
        salutation=data.salutation,
        full_name=data.full_name,
        affiliation=data.affiliation,
        can_play=data.can_play,
        can_staff=data.can_staff,
    )
    db.add(player)
    db.flush()
    admin_grant.consume_pending_admin(db, player=player)
    bootstrap_admin_service.maybe_grant_bootstrap_admin(db, player=player)
    db.commit()
    db.refresh(player)
    return player


@router.get("/players/me", response_model=BotPlayerProfileOut)
@limiter.limit("20/minute")
def get_my_profile(
    request: Request,
    telegram_username: str | None = None,
    db: Session = Depends(get_db),
    actor: models.Player = Depends(get_bot_actor),
) -> models.Player:
    # Оппортунистическая синхронизация username при каждом /start — телеграм
    # не уведомляет бэкенд о смене username, поэтому бот просто присылает
    # текущее значение при каждом обращении. Заодно переоцениваем bootstrap-права
    # (см. bootstrap_admin_service) — конфиг мог измениться после регистрации игрока.
    changed = False
    if telegram_username is not None and telegram_username != actor.telegram_username:
        actor.telegram_username = telegram_username
        changed = True
    if admin_grant.consume_pending_admin(db, player=actor):
        changed = True
    if bootstrap_admin_service.maybe_grant_bootstrap_admin(db, player=actor):
        changed = True
    if changed:
        db.commit()
        db.refresh(actor)
    return actor


@router.put("/players/me", response_model=BotPlayerProfileOut)
@limiter.limit("20/minute")
def update_my_profile(
    request: Request,
    data: BotPlayerProfileUpdateIn,
    db: Session = Depends(get_db),
    actor: models.Player = Depends(get_bot_actor),
) -> models.Player:
    if data.nickname and data.nickname.lower() != actor.nickname.lower():
        if db.query(models.Player).filter(models.Player.nickname.ilike(data.nickname)).first():
            raise HTTPException(409, "Ник уже занят")

    for field in ("salutation", "full_name", "affiliation", "nickname", "can_play", "can_staff"):
        value = getattr(data, field)
        if value is not None:
            setattr(actor, field, value)
    db.commit()
    db.refresh(actor)
    return actor


@router.get("/game-days")
@limiter.limit("20/minute")
def list_game_days(
    request: Request,
    telegram_id: int,
    game_type: str | None = None,
    db: Session = Depends(get_db),
    actor: models.Player = Depends(get_bot_actor),
) -> list[str]:
    sessions = registration_service.list_open_sessions(db, game_type=game_type, exclude_player_id=actor.id)
    days = sorted({club_day(s.starts_at) for s in sessions})
    return days


@router.get("/sessions/open", response_model=list[SessionOut])
@limiter.limit("20/minute")
def list_open_sessions(
    request: Request,
    telegram_id: int,
    game_type: str | None = None,
    day: str | None = None,
    db: Session = Depends(get_db),
    actor: models.Player = Depends(get_bot_actor),
) -> list[SessionOut]:
    sessions = registration_service.list_open_sessions(db, game_type=game_type, exclude_player_id=actor.id)
    if day:
        sessions = [s for s in sessions if club_day(s.starts_at) == day]
    return [session_to_out(s) for s in sessions]


@router.get("/sessions/{session_id}", response_model=SessionOut)
@limiter.limit("20/minute")
def get_session(
    request: Request, session_id: int, telegram_id: int, db: Session = Depends(get_db), _: models.Player = Depends(get_bot_actor)
) -> SessionOut:
    game = db.get(models.Game, session_id)
    if game is None:
        raise HTTPException(404, "Сессия не найдена")
    return session_to_out(game)


@router.post("/sessions/{session_id}/register", response_model=RegistrationOut)
@limiter.limit("20/minute")
def register_for_session(
    request: Request, session_id: int, data: RegisterIn, db: Session = Depends(get_db), _: None = Depends(require_bot_service)
) -> RegistrationOut:
    actor = db.query(models.Player).filter(models.Player.telegram_id == data.telegram_id).one_or_none()
    if actor is None:
        raise HTTPException(404, "Игрок не найден")

    game = db.get(models.Game, session_id)
    if game is None or not is_session_open(game):
        raise HTTPException(404, "Сессия недоступна для записи")

    try:
        registration_service.register_for_kind(db, game=game, player=actor, role_kind=data.role_kind)
        db.commit()
    except RegistrationError as exc:
        db.rollback()
        return RegistrationOut(ok=False, message=exc.message, reason=exc.reason)
    return RegistrationOut(ok=True, message="Вы успешно записаны")


@router.post("/sessions/{session_id}/reserve", response_model=RegistrationOut)
@limiter.limit("20/minute")
def reserve_for_session(
    request: Request, session_id: int, data: ReserveIn, db: Session = Depends(get_db), _: None = Depends(require_bot_service)
) -> RegistrationOut:
    actor = db.query(models.Player).filter(models.Player.telegram_id == data.telegram_id).one_or_none()
    if actor is None:
        raise HTTPException(404, "Игрок не найден")

    game = db.get(models.Game, session_id)
    if game is None or not is_session_open(game):
        raise HTTPException(404, "Сессия недоступна для записи")

    try:
        registration_service.add_to_reserve(db, game_id=session_id, player_id=actor.id)
        db.commit()
    except RegistrationError as exc:
        db.rollback()
        return RegistrationOut(ok=False, message=exc.message, reason=exc.reason)
    return RegistrationOut(ok=True, message="Вы записаны в резерв")


@router.get("/sessions/{session_id}/roster", response_model=RosterOut)
@limiter.limit("20/minute")
def get_session_roster(
    request: Request, session_id: int, telegram_id: int, db: Session = Depends(get_db), _: models.Player = Depends(get_bot_actor)
) -> RosterOut:
    game = db.get(models.Game, session_id)
    if game is None:
        raise HTTPException(404, "Сессия не найдена")
    return roster_to_out(game)


@router.delete("/sessions/{session_id}/registration", response_model=RegistrationOut)
@limiter.limit("20/minute")
def cancel_registration(
    request: Request, session_id: int, telegram_id: int, db: Session = Depends(get_db), actor: models.Player = Depends(get_bot_actor)
) -> RegistrationOut:
    promoted = registration_service.unregister(db, game_id=session_id, player_id=actor.id)
    db.commit()
    if promoted:
        db.refresh(promoted)
        return RegistrationOut(
            ok=True,
            message="Запись отменена",
            promoted_telegram_id=promoted.telegram_id,
            promoted_nickname=promoted.nickname,
        )
    return RegistrationOut(ok=True, message="Запись отменена")


@router.get("/registrations/mine", response_model=list[MyRegistrationOut])
@limiter.limit("20/minute")
def my_registrations(
    request: Request, telegram_id: int, db: Session = Depends(get_db), actor: models.Player = Depends(get_bot_actor)
) -> list[MyRegistrationOut]:
    return _actor_registrations(db, actor.id)


def _actor_registrations(db: Session, player_id: int) -> list[MyRegistrationOut]:
    out: list[MyRegistrationOut] = []
    regs = db.query(models.Registration).filter(models.Registration.player_id == player_id).all()
    for r in regs:
        out.append(
            MyRegistrationOut(
                game_id=r.game_id,
                starts_at=r.game.starts_at,
                location=r.game.location,
                game_type=r.game.game_type,
                role=r.role,
                is_reserve=False,
            )
        )
    reserves = db.query(models.Reserve).filter(models.Reserve.player_id == player_id).all()
    for r in reserves:
        out.append(
            MyRegistrationOut(
                game_id=r.game_id,
                starts_at=r.game.starts_at,
                location=r.game.location,
                game_type=r.game.game_type,
                role="reserve",
                is_reserve=True,
            )
        )
    return sorted(out, key=lambda x: x.starts_at)
