"""Оповещение админов сайта о новых заявках и правках, ждущих проверки.

Обратная сторона модерации из разделов 3.7 и 3.8: там сайт копит решения
админа, а бот их разносит игрокам; здесь бот копит новые pending-строки и
разносит их админам. Причина та же -- бэкенд в Telegram не пишет, токен бота
живёт только у бота, поэтому доставка устроена опросом.

Очередь = pending-строка, о которой админам ещё не написали. Признак «написали»
-- отдельная метка (`confirmation_admin_notified_at` у заявки, `admin_notified_at`
у правки), которую ставит бот `ack`'ом после рассылки. Пока метки нет, строка
в очереди, так что упавший бот ничего не теряет.

Получатели -- любые админы с привязанным Telegram: заявку и правку разбирают
кнопками прямо в этом уведомлении, экрана под них на сайте больше нет.
Админ без telegram_id в рассылку не попадает -- писать некуда.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session, joinedload

from app import models

STATUS_PENDING_PLAYER = models.ConfirmationStatus.pending.value
STATUS_PENDING_CHANGE = models.ProfileChangeStatus.pending.value


def admin_recipients(db: Session) -> list[models.Player]:
    """Кому писать о заявке или правке.

    Любой админ с привязанным Telegram -- и сайта, и бота: решение теперь
    принимается прямо в сообщении, кнопками (см. /api/bot/moderation/*), и
    другого экрана под него нет. Админ без telegram_id в рассылку не попадает
    -- писать некуда.
    """
    return (
        db.query(models.Player)
        .filter(
            models.Player.is_site_admin.is_(True) | models.Player.is_bot_admin.is_(True),
            models.Player.telegram_id.isnot(None),
        )
        .order_by(models.Player.id.asc())
        .all()
    )


def pending_registrations(db: Session, *, limit: int = 50) -> list[models.Player]:
    """Заявки на вступление, о которых админам ещё не писали."""
    return (
        db.query(models.Player)
        .filter(
            models.Player.confirmation_status == STATUS_PENDING_PLAYER,
            models.Player.confirmation_admin_notified_at.is_(None),
        )
        .order_by(models.Player.created_at.asc(), models.Player.id.asc())
        .limit(limit)
        .all()
    )


def pending_profile_changes(db: Session, *, limit: int = 50) -> list[models.PlayerProfileChange]:
    """Правки профиля, о которых админам ещё не писали."""
    return (
        db.query(models.PlayerProfileChange)
        .options(joinedload(models.PlayerProfileChange.player))
        .filter(
            models.PlayerProfileChange.status == STATUS_PENDING_CHANGE,
            models.PlayerProfileChange.admin_notified_at.is_(None),
        )
        .order_by(
            models.PlayerProfileChange.created_at.asc(), models.PlayerProfileChange.id.asc()
        )
        .limit(limit)
        .all()
    )


def mark_registrations_notified(db: Session, *, player_ids: list[int]) -> int:
    if not player_ids:
        return 0
    now = datetime.now(timezone.utc)
    updated = (
        db.query(models.Player)
        .filter(
            models.Player.id.in_(player_ids),
            models.Player.confirmation_admin_notified_at.is_(None),
        )
        .update(
            {models.Player.confirmation_admin_notified_at: now}, synchronize_session=False
        )
    )
    return int(updated)


def mark_profile_changes_notified(db: Session, *, change_ids: list[int]) -> int:
    if not change_ids:
        return 0
    now = datetime.now(timezone.utc)
    updated = (
        db.query(models.PlayerProfileChange)
        .filter(
            models.PlayerProfileChange.id.in_(change_ids),
            models.PlayerProfileChange.admin_notified_at.is_(None),
        )
        .update(
            {models.PlayerProfileChange.admin_notified_at: now}, synchronize_session=False
        )
    )
    return int(updated)
