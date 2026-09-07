"""То, что осталось от админки бота: права и две рассылки.

Всё, что касается расписания -- создание игрового дня, правка слота,
подтверждение проведения -- переехало в админку сайта
(`routers/admin_schedule.py`). Здесь живёт ровно то, чего на сайте сделать
нельзя: назначить админа тому, кого знают только по @username в Telegram, и
собрать список получателей для рассылки, которую отправляет бот (токен
Telegram есть только у него, см. ARCHITECTURE.md, раздел 12).
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.deps import require_bot_admin_actor
from app.rate_limit import limiter
from app.schemas.bot import (
    AdminInfoOut,
    BotAdminGrantIn,
    BroadcastAudienceOut,
    BroadcastPlayerOut,
    PlayerLookupOut,
    WeeklyBroadcastOut,
)
from app.serializers import session_to_out
from app.services import admin_grant, broadcast_service, schedule_admin_service

router = APIRouter(
    prefix="/api/bot/admin",
    tags=["bot-admin"],
    dependencies=[Depends(require_bot_admin_actor)],
)


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


@router.get("/broadcast/audience", response_model=BroadcastAudienceOut)
@limiter.limit("30/minute")
def broadcast_audience(request: Request, telegram_id: int, db: Session = Depends(get_db)) -> BroadcastAudienceOut:
    """Получатели произвольного сообщения от админа.

    В отличие от анонса, записавшиеся отсюда не вычитаются: объявление
    «сегодня играем в 685-й, а не в 683-й» нужно в первую очередь как раз им.
    """
    recipients = broadcast_service.all_recipients(db)
    return BroadcastAudienceOut(
        recipients=[BroadcastPlayerOut.model_validate(p) for p in recipients]
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
