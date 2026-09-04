from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app import models
from app.services import rating_service


class GameValidationError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


@dataclass
class ParticipantInput:
    player_id: int
    seat_number: int
    role: str
    points_win: float = 0
    points_judge: float = 0
    lh: float | None = None
    ci: float | None = None
    info: str | None = None
    removals: int | None = None
    ppk: bool = False
    zk: float | None = None
    sk: float | None = None


def _validate_participants(participants: list[ParticipantInput]) -> None:
    if len(participants) != 10:
        raise GameValidationError("В игре должно быть ровно 10 участников")

    seats = [p.seat_number for p in participants]
    if sorted(seats) != list(range(1, 11)):
        raise GameValidationError("Места за столом должны быть уникальны и покрывать 1..10")

    player_ids = [p.player_id for p in participants]
    if len(set(player_ids)) != len(player_ids):
        raise GameValidationError("Игрок не может занимать больше одного места в одной игре")

    valid_roles = {"mafia", "don", "sheriff", "citizen"}
    for p in participants:
        if p.role not in valid_roles:
            raise GameValidationError(f"Недопустимая роль: {p.role}")
        if p.lh is not None and not (0 <= p.lh <= 1.5):
            raise GameValidationError("ЛХ должен быть в диапазоне 0..1.5")
        if p.info is not None and p.info not in {"first_killed", "killed", "voted_out"}:
            raise GameValidationError(f"Недопустимое значение Инфо: {p.info}")


def create_rated_game(
    db: Session,
    *,
    starts_at: datetime,
    location: str | None,
    game_type: str,
    result: str,
    notes: str | None,
    created_by: int,
    participants: list[ParticipantInput],
) -> models.Game:
    _validate_participants(participants)
    if result not in {"city_win", "mafia_win", "draw"}:
        raise GameValidationError("Недопустимый исход игры")

    game = models.Game(
        starts_at=starts_at,
        location=location,
        game_type=game_type,
        status="rated",
        result=result,
        notes=notes,
        created_by=created_by,
    )
    db.add(game)
    db.flush()

    for p in participants:
        db.add(
            models.GameParticipant(
                game_id=game.id,
                player_id=p.player_id,
                seat_number=p.seat_number,
                role=p.role,
                points_win=p.points_win,
                points_judge=p.points_judge,
                lh=p.lh,
                ci=p.ci,
                info=p.info,
                removals=p.removals,
                ppk=p.ppk,
                zk=p.zk,
                sk=p.sk,
            )
        )
    db.flush()

    rating_service.recompute_all(db)
    return game


def update_rated_game(
    db: Session,
    *,
    game: models.Game,
    starts_at: datetime | None,
    location: str | None,
    game_type: str | None,
    result: str | None,
    notes: str | None,
    participants: list[ParticipantInput] | None,
) -> models.Game:
    if starts_at is not None:
        game.starts_at = starts_at
    if location is not None:
        game.location = location
    if game_type is not None:
        game.game_type = game_type
    if notes is not None:
        game.notes = notes

    if participants is not None:
        _validate_participants(participants)
        if result is None:
            raise GameValidationError("При обновлении состава нужно указать исход игры")
        if result not in {"city_win", "mafia_win", "draw"}:
            raise GameValidationError("Недопустимый исход игры")

        db.query(models.GameParticipant).filter(models.GameParticipant.game_id == game.id).delete()
        for p in participants:
            db.add(
                models.GameParticipant(
                    game_id=game.id,
                    player_id=p.player_id,
                    seat_number=p.seat_number,
                    role=p.role,
                    points_win=p.points_win,
                    points_judge=p.points_judge,
                    lh=p.lh,
                    ci=p.ci,
                    info=p.info,
                    removals=p.removals,
                    ppk=p.ppk,
                    zk=p.zk,
                    sk=p.sk,
                )
            )
        game.result = result
        game.status = "rated"
    elif result is not None:
        if result not in {"city_win", "mafia_win", "draw"}:
            raise GameValidationError("Недопустимый исход игры")
        game.result = result

    db.flush()
    rating_service.recompute_all(db)
    return game


def delete_game(db: Session, *, game: models.Game) -> None:
    was_rated = game.status == "rated"
    db.delete(game)
    db.flush()
    if was_rated:
        rating_service.recompute_all(db)


def games_pending_review(db: Session) -> list[models.Game]:
    return (
        db.query(models.Game)
        .filter(models.Game.status == "played")
        .order_by(models.Game.starts_at.asc())
        .all()
    )


def mark_past_sessions_as_played(db: Session) -> int:
    """Переводит прошедшие 'scheduled'/'registration_closed' игры в 'played'.
    Вызывается фоновой задачей (см. app/routers/bot_admin.py)."""
    now = datetime.now(timezone.utc)
    rows = (
        db.query(models.Game)
        .filter(models.Game.status.in_(["scheduled", "registration_closed"]))
        .filter(models.Game.starts_at < now)
        .all()
    )
    for game in rows:
        game.status = "played"
    db.flush()
    return len(rows)
