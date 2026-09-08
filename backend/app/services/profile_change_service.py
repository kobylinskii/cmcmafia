"""Модерация правок профиля, отправленных игроком из бота.

Зачем вообще: профиль -- это ФИО в списке на пропуск и ник в рейтинге и
составах игр, то есть то, по чему человека узнают в клубе. Подтверждённый
участник не переписывает их молча -- правка ждёт админа, а до его решения
действует прежнее значение.

Проверяются только поля свободного ввода (MODERATED_FIELDS). Обращение,
статус прохода, роли и любимая роль выбираются кнопками из вариантов,
заданных самим ботом: проверять там нечего, а роли к тому же решают, на какие
места пускает запись прямо сейчас.

Механика доставки решения -- та же, что у модерации регистраций
(player_confirmation_service): сайт ставит decided_at, бот забирает очередь
опросом и ставит notified_at. Бэкенд в Telegram не ходит.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session, joinedload

from app import models
from app.errors import ServiceError
from app.services.player_service import delete_photo_file
from app.textmatch import ci_equals

STATUS_PENDING = models.ProfileChangeStatus.pending.value
STATUS_APPLIED = models.ProfileChangeStatus.applied.value
STATUS_REJECTED = models.ProfileChangeStatus.rejected.value

# Поля, которые игрок вводит текстом. Значения хранятся строкой независимо от
# типа колонки -- в очереди лежит ровно то, что человек написал, а приведение
# к типу происходит в момент применения (_coerce).
MODERATED_FIELDS: tuple[str, ...] = (
    "full_name", "nickname", "age", "experience", "bio", "photo_url",
)

FIELD_LABELS: dict[str, str] = {
    "full_name": "ФИО",
    "nickname": "никнейм",
    "age": "возраст",
    "experience": "опыт",
    "bio": "о себе",
    "photo_url": "фото",
}

# Единственное поле, чьё значение в очереди -- не то, что человек написал, а
# адрес уже записанного на диск файла (боту он нужен, чтобы показать админу
# саму картинку). Отсюда особенность: у отклонённой и у вытесненной правки
# после решения остаётся файл, на который никто не ссылается, и его надо
# убрать -- иначе волюм растёт на каждую непринятую аватарку.
PHOTO_FIELD = "photo_url"


class ProfileChangeError(ServiceError):
    pass


def requires_moderation(player: models.Player, field: str) -> bool:
    """Ждать ли админа с этой правкой.

    Непподтверждённого и отклонённого игрока правка не тормозит: у них на
    проверке весь профиль целиком, и отказ «поправьте ФИО и отправьте заявку
    заново» иначе превратился бы в тупик -- исправление тоже ушло бы в
    очередь и заявку стало бы нечем поправить.
    """
    if field not in MODERATED_FIELDS:
        return False
    return player.confirmation_status == models.ConfirmationStatus.confirmed.value


def current_value(player: models.Player, field: str) -> str | None:
    value = getattr(player, field, None)
    return None if value is None else str(value)


def _coerce(field: str, raw: str | None):
    """Строка из очереди -> значение колонки. NULL -- очистка поля."""
    if raw is None:
        return None
    return int(raw) if field == "age" else raw


def submit(
    db: Session, *, player: models.Player, field: str, value
) -> models.PlayerProfileChange | None:
    """Поставить правку в очередь, заменив прежнюю по этому же полю.

    None означает «правка ни к чему»: человек прислал то же значение, что уже
    стоит в профиле. Отказывать на это нельзя -- в боте так выглядит обычное
    повторное сохранение поля, и ошибка на нём читалась бы как поломка.
    """
    if field not in MODERATED_FIELDS:
        raise ProfileChangeError(f"Поле «{field}» не проходит проверку админа")

    new_value = None if value is None else str(value)
    if new_value == current_value(player, field):
        return None
    if field == "nickname" and new_value is not None:
        _ensure_nickname_free(db, player=player, nickname=new_value)

    # Повторная правка того же поля вытесняет прежнюю: админу нужен последний
    # вариант, а не история промежуточных (и того же требует частичный
    # уникальный индекс uq_profile_changes_one_pending_per_field).
    #
    # Именно вытесняет, а не пересоздаёт: id строки обязан пережить правку.
    # Пересоздание ломало уже разосланные админам карточки и сообщения --
    # они ссылаются на id, и у всех, кроме последней, кнопка «Применить»
    # утыкалась в «Правка не найдена». Снаружи это выглядело так, будто
    # подтвердить можно только последнюю правку.
    existing = pending_for_field(db, player_id=player.id, field=field)
    if existing is not None:
        if field == PHOTO_FIELD:
            delete_photo_file(existing.new_value)
        existing.new_value = new_value
        # Значение поменялось -- админам нужно написать заново (старое
        # сообщение показывает уже неактуальное «станет»).
        existing.admin_notified_at = None
        db.flush()
        return existing

    change = models.PlayerProfileChange(
        player_id=player.id, field=field, new_value=new_value, status=STATUS_PENDING
    )
    db.add(change)
    db.flush()
    return change


def _ensure_nickname_free(db: Session, *, player: models.Player, nickname: str) -> None:
    taken = (
        db.query(models.Player)
        .filter(ci_equals(models.Player.nickname, nickname), models.Player.id != player.id)
        .first()
    )
    if taken is not None:
        raise ProfileChangeError("Ник уже занят")


def withdraw(db: Session, *, player: models.Player, field: str) -> bool:
    """Забрать правку обратно, пока админ её не рассмотрел.

    Нужно одному случаю: игрок отправил фото на проверку и тут же нажал
    «Удалить». Оставить строку в очереди значило бы, что снятое фото всё
    равно встанет в профиль, как только админ дойдёт до карточки.

    Строка удаляется, а не отклоняется: решения по ней не было, и в истории
    ей делать нечего. Карточка, уже разосланная админам, после этого честно
    ответит «Правка не найдена».
    """
    change = pending_for_field(db, player_id=player.id, field=field)
    if change is None:
        return False
    if field == PHOTO_FIELD:
        delete_photo_file(change.new_value)
    db.delete(change)
    db.flush()
    return True


def pending_for_field(db: Session, *, player_id: int, field: str) -> models.PlayerProfileChange | None:
    return (
        db.query(models.PlayerProfileChange)
        .filter(
            models.PlayerProfileChange.player_id == player_id,
            models.PlayerProfileChange.field == field,
            models.PlayerProfileChange.status == STATUS_PENDING,
        )
        .one_or_none()
    )


def pending_for_player(db: Session, *, player_id: int) -> list[models.PlayerProfileChange]:
    return (
        db.query(models.PlayerProfileChange)
        .filter(
            models.PlayerProfileChange.player_id == player_id,
            models.PlayerProfileChange.status == STATUS_PENDING,
        )
        .order_by(models.PlayerProfileChange.created_at.asc())
        .all()
    )


def list_pending(db: Session) -> list[models.PlayerProfileChange]:
    return (
        db.query(models.PlayerProfileChange)
        .options(joinedload(models.PlayerProfileChange.player))
        .filter(models.PlayerProfileChange.status == STATUS_PENDING)
        .order_by(models.PlayerProfileChange.created_at.asc(), models.PlayerProfileChange.id.asc())
        .all()
    )


def pending_count(db: Session) -> int:
    return (
        db.query(models.PlayerProfileChange)
        .filter(models.PlayerProfileChange.status == STATUS_PENDING)
        .count()
    )


def apply(db: Session, *, change: models.PlayerProfileChange) -> models.PlayerProfileChange:
    if change.status != STATUS_PENDING:
        raise ProfileChangeError("Эта правка уже рассмотрена")
    player = change.player
    # Ник мог занять кто-то другой, пока правка ждала: проверка при подаче
    # ничего не резервирует, а UNIQUE на колонке отдал бы 500 вместо отказа.
    if change.field == "nickname" and change.new_value is not None:
        _ensure_nickname_free(db, player=player, nickname=change.new_value)

    previous_photo = player.photo_url if change.field == PHOTO_FIELD else None
    setattr(player, change.field, _coerce(change.field, change.new_value))
    if previous_photo:
        delete_photo_file(previous_photo)
    change.status = STATUS_APPLIED
    change.decided_at = datetime.now(timezone.utc)
    change.notified_at = None
    db.flush()
    return change


def reject(db: Session, *, change: models.PlayerProfileChange, reason: str) -> models.PlayerProfileChange:
    if change.status != STATUS_PENDING:
        raise ProfileChangeError("Эта правка уже рассмотрена")
    reason = (reason or "").strip()
    if not reason:
        # Причина -- единственное, что игрок увидит в боте: без неё отказ
        # выглядит как поломка (та же логика, что и у отказа по заявке).
        raise ProfileChangeError("Нужно указать причину отклонения")
    if change.field == PHOTO_FIELD:
        delete_photo_file(change.new_value)
    change.status = STATUS_REJECTED
    change.rejection_reason = reason
    change.decided_at = datetime.now(timezone.utc)
    change.notified_at = None
    db.flush()
    return change


def pending_notifications(db: Session, *, limit: int = 50) -> list[models.PlayerProfileChange]:
    """Решения, о которых игрок ещё не знает. Только с telegram_id: игроку,
    заведённому на сайте руками, писать некуда."""
    return (
        db.query(models.PlayerProfileChange)
        .options(joinedload(models.PlayerProfileChange.player))
        .join(models.Player)
        .filter(
            models.PlayerProfileChange.decided_at.isnot(None),
            models.PlayerProfileChange.notified_at.is_(None),
            models.Player.telegram_id.isnot(None),
        )
        .order_by(models.PlayerProfileChange.decided_at.asc())
        .limit(limit)
        .all()
    )


def mark_notified(db: Session, *, change_ids: list[int]) -> int:
    if not change_ids:
        return 0
    now = datetime.now(timezone.utc)
    updated = (
        db.query(models.PlayerProfileChange)
        .filter(
            models.PlayerProfileChange.id.in_(change_ids),
            models.PlayerProfileChange.notified_at.is_(None),
        )
        .update({models.PlayerProfileChange.notified_at: now}, synchronize_session=False)
    )
    return int(updated)
