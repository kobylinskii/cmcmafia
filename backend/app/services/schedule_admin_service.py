"""Административные операции над расписанием игр (bulk-создание слотов,
поиск конфликтов, обзор по дням) — перенесено из bot/mafia-tg-bot/app/db/database.py,
адаптировано под unified-схему (games.status вместо отдельной таблицы сессий)."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models
from app.timeutil import CLUB_TZ


def bulk_create_sessions(
    db: Session, *, starts_at_list: list[datetime], location: str, game_type: str, created_by: int
) -> list[int]:
    created: list[models.Game] = []
    for starts_at in starts_at_list:
        game = models.Game(
            starts_at=starts_at,
            location=location,
            game_type=game_type,
            registration_until=starts_at,
            status="scheduled",
            created_by=created_by,
        )
        db.add(game)
        created.append(game)
    db.flush()
    return [g.id for g in created]


def check_conflicts(
    db: Session, *, starts_at_list: list[datetime], exclude_session_ids: set[int] | None = None
) -> list[datetime]:
    if not starts_at_list:
        return []
    excluded = exclude_session_ids or set()
    rows = (
        db.query(models.Game.starts_at)
        .filter(models.Game.starts_at.in_(starts_at_list))
        .filter(models.Game.id.notin_(excluded) if excluded else True)
        .order_by(models.Game.starts_at.asc())
        .all()
    )
    return [r[0] for r in rows]


def _club_day_bounds(day: str) -> tuple[datetime, datetime]:
    """'ДД.ММ.ГГГГ' -> границы этих суток [начало, конец) в московском времени.

    Именно в московском: игра в 00:30 МСК приходится на 21:30 UTC предыдущих
    суток, и наивное сравнение по UTC отправило бы её в соседний день
    (см. app/timeutil.py).
    """
    start = datetime.strptime(day, "%d.%m.%Y").replace(tzinfo=CLUB_TZ)
    return start, start + timedelta(days=1)


# Календарный день игры по московскому времени, посчитанный на стороне СУБД.
_CLUB_DAY_SQL = func.date(func.timezone(str(CLUB_TZ), models.Game.starts_at))


def day_cards(db: Session, *, game_type: str | None = None) -> list[dict]:
    """Группировка делается в SQL: раньше в память выгружались строки по каждой
    игре клуба за всю историю, и список дней стоил O(всех игр)."""
    query = (
        db.query(
            _CLUB_DAY_SQL.label("day"),
            models.Game.game_type,
            func.min(models.Game.starts_at).label("min_start"),
        )
        # Турнирные слоты этапа сюда не попадают: у бота для них нет ни одного
        # осмысленного действия (нет регистрации, нет ростера через бота) --
        # только фанки/обучающие, которыми бот-админ реально управляет.
        .filter(models.Game.game_type != "tournament")
        .group_by(_CLUB_DAY_SQL, models.Game.game_type)
    )
    if game_type and game_type != "all":
        query = query.filter(models.Game.game_type == game_type)

    grouped: dict[str, dict] = {}
    for day, gtype, min_start in query.all():
        key = day.strftime("%d.%m.%Y")
        entry = grouped.setdefault(key, {"types": set(), "min_start": min_start})
        entry["types"].add(gtype)
        if min_start < entry["min_start"]:
            entry["min_start"] = min_start

    ordered = sorted(grouped.items(), key=lambda kv: kv[1]["min_start"])
    return [{"day": day, "types": sorted(v["types"])} for day, v in ordered]


def games_by_day(db: Session, *, day: str) -> list[models.Game]:
    """Отбор по диапазону в SQL, а не выгрузка всей таблицы с фильтрацией
    на Python."""
    start, end = _club_day_bounds(day)
    return (
        db.query(models.Game)
        .filter(
            models.Game.starts_at >= start,
            models.Game.starts_at < end,
            models.Game.game_type != "tournament",
        )
        .order_by(models.Game.starts_at.asc())
        .all()
    )


def find_player_by_username(db: Session, username: str) -> models.Player | None:
    clean = username.strip().lstrip("@")
    if not clean:
        return None
    return db.query(models.Player).filter(models.Player.telegram_username.ilike(clean)).one_or_none()


def find_player_by_phone(db: Session, phone: str) -> models.Player | None:
    digits = "".join(ch for ch in phone if ch.isdigit())
    if len(digits) < 10:
        return None
    return db.query(models.Player).filter(models.Player.phone == digits).one_or_none()
