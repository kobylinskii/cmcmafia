"""Логика записи на будущие игры (перенесена из bot/mafia-tg-bot/app/db/database.py,
адаптирована под unified-схему: users -> players, games.status='scheduled')."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models, serializers
from app.errors import ServiceError

HOST_LIMIT = 1
JUDGE_LIMIT = 2


class RegistrationError(ServiceError):
    def __init__(self, message: str, reason: str | None = None):
        self.reason = reason
        super().__init__(message)


@dataclass(frozen=True)
class JoinResult:
    """Чем закончилась попытка записаться.

    Резерв перестал быть отдельным действием пользователя: первые десять
    занимают места за столом, одиннадцатый тем же нажатием встаёт в очередь.
    Вызывающему коду нужно знать, что именно произошло, -- отсюда этот
    результат вместо голой Registration.
    """

    role: str
    reserved: bool
    position: int | None = None
    # Кого подняли из резерва этой же записью. Заполняется только при уходе
    # из-за стола в штаб: место игрока освобождается, и очередь обязана
    # сдвинуться так же, как при отмене (см. register_for_kind).
    promoted: "models.Player | None" = None


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


def list_open_sessions(db: Session, *, game_type: str | None = None):
    """Игры, на которые сейчас идёт запись.

    Свои записи отсюда НЕ вычитаются: строка остаётся в списке с галочкой (см.
    my_roles ниже). Раньше игра после записи из списка исчезала, и нажатие
    выглядело так, будто слот пропал, а не занят.
    """
    query = db.query(models.Game).options(*serializers.session_load_options()).filter(
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
    return query.order_by(models.Game.starts_at.asc()).all()


def my_roles(db: Session, *, player_id: int) -> dict[int, str]:
    """game_id -> роль игрока в этой игре ('host'/'judge'/'player'/'reserve').

    Именно этим списки бота отмечают галочкой уже занятые слоты.
    """
    roles = {
        game_id: role
        for game_id, role in db.query(
            models.Registration.game_id, models.Registration.role
        ).filter(models.Registration.player_id == player_id)
    }
    for (game_id,) in db.query(models.Reserve.game_id).filter(
        models.Reserve.player_id == player_id
    ):
        roles.setdefault(game_id, "reserve")
    return roles


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


def register_for_kind(db: Session, *, game: models.Game, player: models.Player, role_kind: str) -> JoinResult:
    """Записать игрока на игру в выбранном качестве.

    Роль 'player' переполнением не отказывает: стол на max_players человек
    собирается первым, а все следующие тем же нажатием уходят в резерв и
    поднимаются автоматически при первой отмене. Раньше здесь возвращался
    отказ role_full, бот показывал отдельный экран «мест нет», и попасть в
    очередь можно было только вторым нажатием -- половина людей до него не
    доходила.

    Штаб (ведущий + двое судей) резерва не имеет: заменить ведущего некем,
    очередь на эти три места была бы очередью в пустоту.
    """
    if role_kind == "player":
        try:
            reg = register(db, game=game, player=player, role="player")
        except RegistrationError as exc:
            if exc.reason != "role_full":
                raise
            add_to_reserve(db, game_id=game.id, player_id=player.id)
            return JoinResult(role="reserve", reserved=True, position=reserve_position(db, game_id=game.id))
        return JoinResult(role=reg.role, reserved=False)
    if role_kind != "staff":
        raise RegistrationError("Неизвестный тип роли")

    # Уход из-за стола в штаб освобождает место игрока ровно так же, как
    # отмена записи -- разница только в том, что человек остаётся в игре.
    # Промоушен жил лишь в unregister(), и эта дорога его миновала: стол
    # оставался неполным, а очередь резерва стояла при свободном месте.
    freed_player_seat = (
        db.query(models.Registration)
        .filter(
            models.Registration.game_id == game.id,
            models.Registration.player_id == player.id,
            models.Registration.role == "player",
        )
        .first()
        is not None
    )

    if _role_count(db, game.id, "host") < HOST_LIMIT:
        reg = register(db, game=game, player=player, role="host")
    else:
        reg = register(db, game=game, player=player, role="judge")

    promoted = promote_next_reserve(db, game_id=game.id) if freed_player_seat else None
    return JoinResult(role=reg.role, reserved=False, promoted=promoted)


def reserve_position(db: Session, *, game_id: int) -> int:
    """Длина очереди резерва. Вызывается сразу после add_to_reserve, поэтому
    равна номеру только что добавленного: created_at на неподтверждённой
    строке ещё не заполнен сервером, и считать место по нему нельзя."""
    return (
        db.query(func.count(models.Reserve.id)).filter(models.Reserve.game_id == game_id).scalar() or 0
    )


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
        # id -- тай-брейкер, а не украшение: created_at заполняется
        # server_default=func.now(), а это в Postgres время НАЧАЛА транзакции,
        # одинаковое у всех строк одной транзакции. Без второго ключа порядок
        # очереди при совпадении меток определял планировщик, и поднятым мог
        # оказаться не тот, кому бот показал «вы в резерве, №1». Тот же приём
        # уже применён в нумерации игр и в рейтинговой таблице.
        .order_by(models.Reserve.created_at.asc(), models.Reserve.id.asc())
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
