"""Напоминание «сегодня игры» за несколько часов до первой игры дня.

Одно сообщение на человека на клубный день, а не на каждый слот: записавшийся
на две игры подряд не должен получать два одинаковых напоминания.

Устройство то же, что у остальных рассылок (см. admin_notification_service):
бэкенд копит очередь и отдаёт её боту, бот рассылает и подтверждает ack'ом.
Признак «уже разослано» -- `day_reminder_sent_at` у ПЕРВОЙ игры дня: она же
задаёт и момент отправки, так что второго места для этой метки не нужно.

Пока ack не пришёл, день остаётся в очереди -- упавший бот напоминание не
теряет. Просроченные (первая игра уже началась) из очереди уходят сами:
напоминать о том, что уже идёт, поздно.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app import models
from app.timeutil import club_day

# За сколько часов до начала первой игры дня уходит напоминание.
REMINDER_LEAD_HOURS = 3


@dataclass(frozen=True)
class DayReminder:
    """Один клубный день, о котором пора напомнить."""

    day: str
    # Первая игра дня -- на ней и стоит метка «разослано».
    marker_game_id: int
    games: list[models.Game]
    recipients: list[models.Player]


def _scheduled_games(db: Session) -> list[models.Game]:
    return (
        db.query(models.Game)
        .filter(
            models.Game.status == "scheduled",
            models.Game.game_type != "tournament",
        )
        .order_by(models.Game.starts_at.asc())
        .all()
    )


def _recipients(db: Session, game_ids: list[int]) -> list[models.Player]:
    """Все, кто записан на игры этого дня, включая резерв.

    Резерв тоже зовём: место освобождается чаще всего именно в день игры, и
    человеку из очереди надо быть готовым прийти.
    """
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


def pending_reminders(db: Session, *, now: datetime | None = None) -> list[DayReminder]:
    """Дни, до первой игры которых осталось меньше REMINDER_LEAD_HOURS."""
    now = now or datetime.now(timezone.utc)
    deadline = now + timedelta(hours=REMINDER_LEAD_HOURS)

    days: dict[str, list[models.Game]] = {}
    for game in _scheduled_games(db):
        days.setdefault(club_day(game.starts_at), []).append(game)

    reminders: list[DayReminder] = []
    for day, games in days.items():
        first = games[0]  # игры уже отсортированы по времени начала
        if first.day_reminder_sent_at is not None:
            continue
        # Окно: первая игра ещё не началась, но до неё меньше трёх часов.
        if not (now < first.starts_at <= deadline):
            continue
        recipients = _recipients(db, [game.id for game in games])
        if not recipients:
            continue
        reminders.append(
            DayReminder(day=day, marker_game_id=first.id, games=games, recipients=recipients)
        )
    return sorted(reminders, key=lambda item: item.marker_game_id)


def mark_sent(db: Session, *, game_ids: list[int]) -> int:
    if not game_ids:
        return 0
    now = datetime.now(timezone.utc)
    return int(
        db.query(models.Game)
        .filter(models.Game.id.in_(game_ids), models.Game.day_reminder_sent_at.is_(None))
        .update({models.Game.day_reminder_sent_at: now}, synchronize_session=False)
    )
