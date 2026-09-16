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
from app.timeutil import club_day

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


# ------------------------------------------------ рассылка по одному дню
# Две кнопки админ-меню бота ходят сюда за одним и тем же днём, но за разной
# аудиторией: «собрать на игровой день» зовёт тех, кого на нём ещё нет, а
# «напомнить про сегодняшние игры» -- наоборот, только записавшихся.
AUDIENCE_ABSENT = "absent"
AUDIENCE_REGISTERED = "registered"

# Насколько назад смотреть в расписании при выборке дня. Клубный день по
# московскому времени шире суток UTC, а тянуть из БД все 'scheduled' игры
# ради одного дня незачем.
_DAY_LOOKBACK = timedelta(days=1)


def day_sessions(db: Session, *, day: str, only_open: bool) -> list[models.Game]:
    """Игры одного клубного дня («ДД.ММ.ГГГГ»).

    only_open -- для рассылки «записывайтесь»: игру с прошедшим дедлайном
    записи анонсировать нечем. Напоминанию записавшимся, наоборот, нужны все
    игры дня: к этому моменту запись обычно уже закрыта.
    """
    games = (
        db.query(models.Game)
        .options(*serializers.session_load_options())
        .filter(
            models.Game.status == "scheduled",
            models.Game.game_type != "tournament",
            models.Game.starts_at >= datetime.now(timezone.utc) - _DAY_LOOKBACK,
        )
        .order_by(models.Game.starts_at.asc())
        .all()
    )
    games = [game for game in games if club_day(game.starts_at) == day]
    if only_open:
        games = [game for game in games if serializers.is_session_open(game)]
    return games


def day_participants(db: Session, *, game_ids: list[int]) -> list[models.Player]:
    """Все, кто занят в играх дня, включая резерв.

    Резерв считается участником в обоих смыслах: звать его записываться уже
    незачем, а напомнить о дне -- наоборот, нужно: место освобождается чаще
    всего именно в день игры.
    """
    if not game_ids:
        return []
    registered = (
        db.query(models.Player)
        .join(models.Registration, models.Registration.player_id == models.Player.id)
        .filter(
            models.Registration.game_id.in_(game_ids),
            models.Player.telegram_id.isnot(None),
            models.Player.is_active.is_(True),
        )
    )
    reserved = (
        db.query(models.Player)
        .join(models.Reserve, models.Reserve.player_id == models.Player.id)
        .filter(
            models.Reserve.game_id.in_(game_ids),
            models.Player.telegram_id.isnot(None),
            models.Player.is_active.is_(True),
        )
    )
    by_id = {player.id: player for player in registered.union(reserved).all()}
    return [by_id[key] for key in sorted(by_id)]


def day_recipients(db: Session, *, day: str, audience: str) -> list[models.Player]:
    """Кому уйдёт рассылка по дню.

    Занятость считается по ВСЕМ играм дня, а не только по открытым: человек,
    записанный на игру с закрытой записью, на этот день всё равно придёт.
    """
    game_ids = [game.id for game in day_sessions(db, day=day, only_open=False)]
    participants = day_participants(db, game_ids=game_ids)
    if audience == AUDIENCE_REGISTERED:
        return participants
    busy = {player.id for player in participants}
    return [player for player in all_recipients(db) if player.id not in busy]
