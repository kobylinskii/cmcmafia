"""Логика записи на будущие игры (перенесена из bot/mafia-tg-bot/app/db/database.py,
адаптирована под unified-схему: users -> players, games.status='scheduled')."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models

HOST_LIMIT = 1
JUDGE_LIMIT = 2


class RegistrationError(Exception):
    def __init__(self, message: str, reason: str | None = None):
        self.message = message
        self.reason = reason
        super().__init__(message)


def _role_count(db: Session, game_id: int, role: str) -> int:
    return (
        db.query(func.count(models.Registration.id))
        .filter(models.Registration.game_id == game_id, models.Registration.role == role)
        .scalar()
        or 0
    )


def is_role_kind_full(db: Session, game: models.Game, role_kind: str) -> bool:
    if role_kind == "player":
        return _role_count(db, game.id, "player") >= game.max_players
    if role_kind == "staff":
        return (
            _role_count(db, game.id, "host") >= HOST_LIMIT
            and _role_count(db, game.id, "judge") >= JUDGE_LIMIT
        )
    return False


def list_open_sessions(db: Session, *, game_type: str | None = None, exclude_player_id: int | None = None):
    query = db.query(models.Game).filter(
        models.Game.status == "scheduled",
        models.Game.starts_at >= datetime.now(timezone.utc),
        # Турнирные слоты этапа тоже лежат в статусе 'scheduled' (плейсхолдер
        # даты турнира может оказаться в будущем) -- но регистрации на них
        # никогда не было и не будет, это чисто список мест за столом,
        # заполняемый на сайте. Без этого исключения игрок мог бы записаться
        # в бота на игру, которая на деле ждёт оценки турнирного этапа.
        models.Game.game_type != "tournament",
    )
    if game_type and game_type != "all":
        query = query.filter(models.Game.game_type == game_type)
    if exclude_player_id is not None:
        registered_ids = db.query(models.Registration.game_id).filter(
            models.Registration.player_id == exclude_player_id
        )
        reserved_ids = db.query(models.Reserve.game_id).filter(
            models.Reserve.player_id == exclude_player_id
        )
        query = query.filter(models.Game.id.notin_(registered_ids)).filter(
            models.Game.id.notin_(reserved_ids)
        )
    return query.order_by(models.Game.starts_at.asc()).all()


def register(
    db: Session,
    *,
    game: models.Game,
    player: models.Player,
    role: str,
    available_from: str | None = None,
    available_until: str | None = None,
) -> models.Registration:
    if role not in ("host", "judge", "player"):
        raise RegistrationError("Неизвестная роль")

    existing = (
        db.query(models.Registration)
        .filter(models.Registration.game_id == game.id, models.Registration.player_id == player.id)
        .one_or_none()
    )

    if existing and existing.role == role:
        existing.available_from = available_from
        existing.available_until = available_until
        db.flush()
        return existing

    if _role_count(db, game.id, role) >= (
        game.max_players if role == "player" else (HOST_LIMIT if role == "host" else JUDGE_LIMIT)
    ):
        raise RegistrationError(f"Роль «{role}» уже полностью занята", reason="role_full")

    remove_from_reserve(db, game_id=game.id, player_id=player.id)

    if existing:
        existing.role = role
        existing.available_from = available_from
        existing.available_until = available_until
        db.flush()
        return existing

    reg = models.Registration(
        game_id=game.id,
        player_id=player.id,
        role=role,
        available_from=available_from,
        available_until=available_until,
    )
    db.add(reg)
    db.flush()
    return reg


def register_for_kind(db: Session, *, game: models.Game, player: models.Player, role_kind: str) -> models.Registration:
    if role_kind == "player":
        return register(db, game=game, player=player, role="player")
    if role_kind != "staff":
        raise RegistrationError("Неизвестный тип роли")
    if _role_count(db, game.id, "host") < HOST_LIMIT:
        return register(db, game=game, player=player, role="host")
    return register(db, game=game, player=player, role="judge")


def add_to_reserve(db: Session, *, game_id: int, player_id: int) -> models.Reserve:
    existing_reg = (
        db.query(models.Registration)
        .filter(models.Registration.game_id == game_id, models.Registration.player_id == player_id)
        .one_or_none()
    )
    if existing_reg:
        raise RegistrationError("Вы уже записаны на эту игру в основной состав", reason="already_registered")

    existing_reserve = (
        db.query(models.Reserve)
        .filter(models.Reserve.game_id == game_id, models.Reserve.player_id == player_id)
        .one_or_none()
    )
    if existing_reserve:
        raise RegistrationError("Вы уже находитесь в запасе на эту игру", reason="already_reserved")

    reserve = models.Reserve(game_id=game_id, player_id=player_id)
    db.add(reserve)
    db.flush()
    return reserve


def remove_from_reserve(db: Session, *, game_id: int, player_id: int) -> bool:
    reserve = (
        db.query(models.Reserve)
        .filter(models.Reserve.game_id == game_id, models.Reserve.player_id == player_id)
        .one_or_none()
    )
    if reserve is None:
        return False
    db.delete(reserve)
    db.flush()
    return True


def unregister(db: Session, *, game_id: int, player_id: int) -> models.Player | None:
    """Отменяет запись игрока (из основного состава или резерва). Если освободилось
    место в основном составе — продвигает первого из резерва (FIFO) и возвращает его,
    чтобы вызывающий код (бот) отправил ему уведомление."""

    reg = (
        db.query(models.Registration)
        .filter(models.Registration.game_id == game_id, models.Registration.player_id == player_id)
        .one_or_none()
    )
    # Резерв — это очередь на переполнение конкретно роли 'player' (мест игрока
    # в партии 10/10), поэтому авто-промоушен из резерва срабатывает только при
    # отмене именно 'player'-записи, как и в исходном боте.
    was_player_registration = reg is not None and reg.role == "player"
    if reg:
        db.delete(reg)
    else:
        remove_from_reserve(db, game_id=game_id, player_id=player_id)

    db.flush()

    if not was_player_registration:
        return None

    return promote_next_reserve(db, game_id=game_id)


def promote_next_reserve(db: Session, *, game_id: int) -> models.Player | None:
    next_reserve = (
        db.query(models.Reserve)
        .filter(models.Reserve.game_id == game_id)
        .order_by(models.Reserve.created_at.asc())
        .with_for_update(skip_locked=True)
        .first()
    )
    if next_reserve is None:
        return None

    player_id = next_reserve.player_id
    db.delete(next_reserve)
    db.add(models.Registration(game_id=game_id, player_id=player_id, role="player"))
    db.flush()
    return db.get(models.Player, player_id)
