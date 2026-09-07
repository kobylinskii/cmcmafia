"""Подбор данных для анонса игр, который бот-админ рассылает из бота.

Сам текст и отправка -- на стороне бота (токен Telegram живёт только там, см.
ARCHITECTURE.md, раздел 12). API отвечает на два вопроса, ответить на которые
может только он: какие игры попадают в окно и кому из клуба этот анонс ещё
интересен.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app import models, serializers

# Окно анонса по умолчанию -- ближайшая неделя от момента нажатия, а не
# календарная: рассылку запускают в произвольный день, и «следующая неделя»
# для вторника и для пятницы означала бы разное.
DEFAULT_WINDOW_DAYS = 7


def _window(days: int) -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    return now, now + timedelta(days=days)


def upcoming_sessions(db: Session, *, days: int = DEFAULT_WINDOW_DAYS) -> list[models.Game]:
    """Игры окна, на которые прямо сейчас можно записаться.

    Игра с прошедшим registration_until в анонс не идёт: кнопка «Записаться»
    под таким сообщением привела бы человека к отказу.
    """
    start, end = _window(days)
    return (
        db.query(models.Game)
        .options(*serializers.session_load_options())
        .filter(
            models.Game.status == "scheduled",
            models.Game.game_type != "tournament",
            models.Game.starts_at >= start,
            models.Game.starts_at < end,
            or_(models.Game.registration_until.is_(None), models.Game.registration_until >= start),
        )
        .order_by(models.Game.starts_at.asc())
        .all()
    )


def announcement_recipients(db: Session, *, days: int = DEFAULT_WINDOW_DAYS) -> list[models.Player]:
    """Кому анонс ещё нужен.

    Не получают его двое: отклонённые (им сначала нужно поправить анкету) и
    те, у кого на это же окно уже есть запись или резерв -- напоминать про
    игры человеку, который на них идёт, значит приучать его закрывать
    сообщения бота не читая.
    """
    game_ids = [game.id for game in upcoming_sessions(db, days=days)]
    query = db.query(models.Player).filter(
        models.Player.telegram_id.isnot(None),
        models.Player.confirmation_status != models.ConfirmationStatus.rejected.value,
    )
    if game_ids:
        busy_registered = db.query(models.Registration.player_id).filter(
            models.Registration.game_id.in_(game_ids)
        )
        busy_reserved = db.query(models.Reserve.player_id).filter(models.Reserve.game_id.in_(game_ids))
        query = query.filter(models.Player.id.notin_(busy_registered)).filter(
            models.Player.id.notin_(busy_reserved)
        )
    return query.order_by(models.Player.id.asc()).all()


def all_recipients(db: Session) -> list[models.Player]:
    """Аудитория произвольного сообщения от админа.

    Отличие от announcement_recipients ровно одно: записавшиеся не
    вычитаются. Анонс им не нужен -- они уже идут; объявление («аудитория
    поменялась», «сегодня без ведущего») нужно в первую очередь как раз им.
    Отклонённые не получают ничего: у них сначала анкета.
    """
    return (
        db.query(models.Player)
        .filter(
            models.Player.telegram_id.isnot(None),
            models.Player.confirmation_status != models.ConfirmationStatus.rejected.value,
        )
        .order_by(models.Player.id.asc())
        .all()
    )
