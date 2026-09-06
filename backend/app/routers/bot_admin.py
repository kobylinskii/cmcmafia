from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.deps import require_bot_admin_actor
from app.rate_limit import limiter
from app.schemas.bot import (
    AdminInfoOut,
    BotAdminGrantIn,
    BroadcastPlayerOut,
    BulkSessionCreateIn,
    ConflictCheckIn,
    DayCardOut,
    PlayerLookupOut,
    SessionCreateIn,
    SessionOut,
    SessionUpdateIn,
    WeeklyBroadcastOut,
)
from app.schemas.game import GameListItem
from app.serializers import session_to_out
from app.services import admin_grant, broadcast_service, game_service, schedule_admin_service
from app.services.game_service import GameValidationError

router = APIRouter(
    prefix="/api/bot/admin",
    tags=["bot-admin"],
    dependencies=[Depends(require_bot_admin_actor)],
)


@router.post("/sessions", response_model=SessionOut)
@limiter.limit("30/minute")
def create_session(
    request: Request,
    telegram_id: int,
    data: SessionCreateIn,
    db: Session = Depends(get_db),
    actor: models.Player = Depends(require_bot_admin_actor),
) -> SessionOut:
    game = models.Game(
        starts_at=data.starts_at,
        location=data.location,
        game_type=data.game_type,
        registration_until=data.registration_until or data.starts_at,
        max_players=data.max_players,
        status="scheduled",
        created_by=actor.id,
    )
    db.add(game)
    db.commit()
    db.refresh(game)
    return session_to_out(game)


@router.post("/sessions/bulk", response_model=list[int])
@limiter.limit("30/minute")
def create_sessions_bulk(
    request: Request,
    telegram_id: int,
    data: BulkSessionCreateIn,
    db: Session = Depends(get_db),
    actor: models.Player = Depends(require_bot_admin_actor),
) -> list[int]:
    ids = schedule_admin_service.bulk_create_sessions(
        db,
        starts_at_list=data.starts_at_list,
        location=data.location,
        game_type=data.game_type,
        created_by=actor.id,
    )
    db.commit()
    return ids


@router.post("/sessions/check-conflicts")
@limiter.limit("30/minute")
def check_conflicts(request: Request, telegram_id: int, data: ConflictCheckIn, db: Session = Depends(get_db)) -> dict:
    conflicts = schedule_admin_service.check_conflicts(
        db, starts_at_list=data.starts_at_list, exclude_session_ids=set(data.exclude_session_ids)
    )
    return {"conflicts": conflicts}


@router.get("/sessions/day-cards", response_model=list[DayCardOut])
@limiter.limit("30/minute")
def get_day_cards(request: Request, telegram_id: int, game_type: str | None = None, db: Session = Depends(get_db)) -> list[dict]:
    return schedule_admin_service.day_cards(db, game_type=game_type)


@router.get("/sessions/by-day", response_model=list[SessionOut])
@limiter.limit("30/minute")
def get_sessions_by_day(request: Request, telegram_id: int, day: str, db: Session = Depends(get_db)) -> list[SessionOut]:
    games = schedule_admin_service.games_by_day(db, day=day)
    return [session_to_out(g) for g in games]


@router.put("/sessions/{session_id}", response_model=SessionOut)
@limiter.limit("30/minute")
def update_session(
    request: Request, telegram_id: int, session_id: int, data: SessionUpdateIn, db: Session = Depends(get_db)
) -> SessionOut:
    game = db.get(models.Game, session_id)
    if game is None:
        raise HTTPException(404, "Сессия не найдена")

    if data.starts_at is not None:
        game.starts_at = data.starts_at
    if data.location is not None:
        game.location = data.location
    if data.game_type is not None:
        game.game_type = data.game_type
    if data.registration_until is not None:
        game.registration_until = data.registration_until
    db.commit()
    db.refresh(game)
    return session_to_out(game)


@router.delete("/sessions/{session_id}")
@limiter.limit("30/minute")
def delete_session(request: Request, telegram_id: int, session_id: int, db: Session = Depends(get_db)) -> dict:
    game = db.get(models.Game, session_id)
    if game is None:
        raise HTTPException(404, "Сессия не найдена")
    game_service.delete_game(db, game=game)
    db.commit()
    return {"ok": True}


@router.get("/sessions/pending-review", response_model=list[GameListItem])
@limiter.limit("30/minute")
def sessions_pending_review(request: Request, telegram_id: int, db: Session = Depends(get_db)) -> list[models.Game]:
    return game_service.games_pending_review(db)


@router.get("/sessions/awaiting-confirmation", response_model=list[SessionOut])
@limiter.limit("30/minute")
def sessions_awaiting_confirmation(
    request: Request, telegram_id: int, db: Session = Depends(get_db)
) -> list[SessionOut]:
    """Прошедшие игры, проведение которых админ ещё не подтвердил."""
    return [session_to_out(g) for g in game_service.sessions_awaiting_confirmation(db)]


@router.post("/sessions/{session_id}/played", response_model=SessionOut)
@limiter.limit("30/minute")
def mark_session_played(
    request: Request, telegram_id: int, session_id: int, db: Session = Depends(get_db)
) -> SessionOut:
    """«Игра проведена» из бота: единственный вход сессии в «Ждут оценки».

    Фоновой задачи, делавшей это самой, больше нет -- см. app/main.py.
    """
    game = db.get(models.Game, session_id)
    if game is None:
        raise HTTPException(404, "Сессия не найдена")
    try:
        game_service.mark_session_played(db, game=game)
        db.commit()
    except GameValidationError as exc:
        db.rollback()
        raise HTTPException(409, exc.message) from exc
    db.refresh(game)
    return session_to_out(game)


@router.get("/sessions/locations", response_model=list[str])
@limiter.limit("30/minute")
def recent_locations(request: Request, telegram_id: int, db: Session = Depends(get_db)) -> list[str]:
    return schedule_admin_service.recent_locations(db)


@router.get("/broadcast/weekly", response_model=WeeklyBroadcastOut)
@limiter.limit("30/minute")
def weekly_broadcast(
    request: Request, telegram_id: int, days: int = broadcast_service.DEFAULT_WINDOW_DAYS, db: Session = Depends(get_db)
) -> WeeklyBroadcastOut:
    """Что рассылать и кому. Сам текст собирает и отправляет бот (раздел 12)."""
    days = max(1, min(days, 31))
    games = broadcast_service.upcoming_sessions(db, days=days)
    recipients = broadcast_service.announcement_recipients(db, days=days)
    return WeeklyBroadcastOut(
        days=days,
        games=[session_to_out(g) for g in games],
        recipients=[BroadcastPlayerOut.model_validate(p) for p in recipients],
    )


@router.get("/players/by-username", response_model=PlayerLookupOut)
@limiter.limit("30/minute")
def lookup_by_username(request: Request, telegram_id: int, username: str, db: Session = Depends(get_db)) -> models.Player:
    player = schedule_admin_service.find_player_by_username(db, username)
    if player is None:
        raise HTTPException(404, "Пользователь с таким @username не найден среди зарегистрированных")
    return player


@router.get("/players/by-phone", response_model=PlayerLookupOut)
@limiter.limit("30/minute")
def lookup_by_phone(request: Request, telegram_id: int, phone: str, db: Session = Depends(get_db)) -> models.Player:
    player = schedule_admin_service.find_player_by_phone(db, phone)
    if player is None:
        raise HTTPException(404, "Пользователь с таким номером не найден среди зарегистрированных")
    return player


@router.get("/admins", response_model=list[AdminInfoOut])
@limiter.limit("30/minute")
def list_admins(request: Request, telegram_id: int, db: Session = Depends(get_db)) -> list[models.Player]:
    return admin_grant.list_bot_admins(db)


@router.get("/admins/pending", response_model=list[str])
@limiter.limit("30/minute")
def list_pending_admins(request: Request, telegram_id: int, db: Session = Depends(get_db)) -> list[str]:
    return admin_grant.list_pending_admins(db)


@router.post("/admins")
@limiter.limit("30/minute")
def add_admin(request: Request, telegram_id: int, data: BotAdminGrantIn, db: Session = Depends(get_db)) -> dict:
    try:
        return admin_grant.grant_bot_admin(db, telegram_id=data.telegram_id, username=data.username)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.delete("/admins/by-telegram/{target_telegram_id}")
@limiter.limit("30/minute")
def remove_admin(request: Request, telegram_id: int, target_telegram_id: int, db: Session = Depends(get_db)) -> dict:
    removed = admin_grant.remove_bot_admin_by_telegram_id(db, telegram_id=target_telegram_id)
    return {"removed": removed}


@router.delete("/admins/pending/{username}")
@limiter.limit("30/minute")
def remove_pending_admin(request: Request, telegram_id: int, username: str, db: Session = Depends(get_db)) -> dict:
    removed = admin_grant.remove_pending_by_username(db, username=username)
    return {"removed": removed}
