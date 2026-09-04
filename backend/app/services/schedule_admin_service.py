"""Административные операции над расписанием игр (bulk-создание слотов,
поиск конфликтов, обзор по дням) — перенесено из bot/mafia-tg-bot/app/db/database.py,
адаптировано под unified-схему (games.status вместо отдельной таблицы сессий)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app import models
from app.timeutil import club_day


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


def day_cards(db: Session, *, game_type: str | None = None) -> list[dict]:
    query = db.query(models.Game.starts_at, models.Game.game_type)
    if game_type and game_type != "all":
        query = query.filter(models.Game.game_type == game_type)

    grouped: dict[str, dict] = {}
    for starts_at, gtype in query.all():
        day = club_day(starts_at)
        entry = grouped.setdefault(day, {"types": set(), "min_start": starts_at})
        entry["types"].add(gtype)
        if starts_at < entry["min_start"]:
            entry["min_start"] = starts_at

    ordered = sorted(grouped.items(), key=lambda kv: kv[1]["min_start"])
    return [{"day": day, "types": sorted(v["types"])} for day, v in ordered]


def games_by_day(db: Session, *, day: str) -> list[models.Game]:
    games = db.query(models.Game).all()
    matching = [g for g in games if club_day(g.starts_at) == day]
    matching.sort(key=lambda g: g.starts_at)
    return matching


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
