"""Модерация игроков, зарегистрировавшихся через бота.

Решение админа и доставка этого решения игроку -- две разные вещи, поэтому и
полей два: confirmation_decided_at ставит сайт в момент нажатия кнопки, а
confirmation_notified_at -- бот, когда сообщение реально ушло в Telegram.
Пара «решено, но не доставлено» и есть очередь, которую бот разгребает
опросом /api/bot/players/confirmation-notifications. Бэкенд в Telegram не
ходит: токен бота остаётся только у бота.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app import models

STATUS_PENDING = models.ConfirmationStatus.pending.value
STATUS_CONFIRMED = models.ConfirmationStatus.confirmed.value
STATUS_REJECTED = models.ConfirmationStatus.rejected.value


class ConfirmationError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def list_pending(db: Session) -> list[models.Player]:
    return (
        db.query(models.Player)
        .filter(models.Player.confirmation_status == STATUS_PENDING)
        .order_by(models.Player.created_at.asc(), models.Player.id.asc())
        .all()
    )


def pending_count(db: Session) -> int:
    return (
        db.query(models.Player)
        .filter(models.Player.confirmation_status == STATUS_PENDING)
        .count()
    )


def confirm(db: Session, *, player: models.Player) -> models.Player:
    if player.confirmation_status == STATUS_CONFIRMED:
        raise ConfirmationError("Игрок уже подтверждён")
    player.confirmation_status = STATUS_CONFIRMED
    player.rejection_reason = None
    player.confirmation_decided_at = datetime.now(timezone.utc)
    player.confirmation_notified_at = None
    db.flush()
    return player


def reject(db: Session, *, player: models.Player, reason: str) -> models.Player:
    reason = (reason or "").strip()
    if not reason:
        # Не только требование констрейнта: причина -- единственное, что игрок
        # увидит в боте, и без неё отказ выглядит как поломка бота.
        raise ConfirmationError("Нужно указать причину отклонения")
    player.confirmation_status = STATUS_REJECTED
    player.rejection_reason = reason
    player.confirmation_decided_at = datetime.now(timezone.utc)
    player.confirmation_notified_at = None
    db.flush()
    return player


def resubmit(db: Session, *, player: models.Player) -> models.Player:
    """Отклонённый игрок поправил данные и просит проверить заново."""
    if player.confirmation_status != STATUS_REJECTED:
        raise ConfirmationError("Повторная проверка нужна только после отклонения")
    player.confirmation_status = STATUS_PENDING
    player.rejection_reason = None
    player.confirmation_decided_at = None
    player.confirmation_notified_at = None
    # Повторная подача -- новое событие для админа: снимаем метку, чтобы бот
    # снова написал о заявке в очереди оповещения (admin_notification_service).
    player.confirmation_admin_notified_at = None
    db.flush()
    return player


def pending_notifications(db: Session, *, limit: int = 50) -> list[models.Player]:
    """Решения, о которых игрок ещё не знает. Только те, у кого есть telegram_id:
    игроку, заведённому на сайте руками, писать некуда."""
    return (
        db.query(models.Player)
        .filter(
            models.Player.confirmation_decided_at.isnot(None),
            models.Player.confirmation_notified_at.is_(None),
            models.Player.telegram_id.isnot(None),
        )
        .order_by(models.Player.confirmation_decided_at.asc())
        .limit(limit)
        .all()
    )


def mark_notified(db: Session, *, player_ids: list[int]) -> int:
    if not player_ids:
        return 0
    now = datetime.now(timezone.utc)
    updated = (
        db.query(models.Player)
        .filter(
            models.Player.id.in_(player_ids),
            models.Player.confirmation_notified_at.is_(None),
        )
        .update({models.Player.confirmation_notified_at: now}, synchronize_session=False)
    )
    return int(updated)
