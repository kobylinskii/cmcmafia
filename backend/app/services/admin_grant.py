"""Общая логика выдачи прав бот-админа — используется и с сайта
(/api/admin/bot-admins), и из бота (/api/bot/admin/admins): это буквально
один и тот же сервисный метод над одной и той же таблицей players."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app import models
from app.textmatch import ci_equals


def grant_bot_admin(db: Session, *, telegram_id: int | None, username: str | None) -> dict:
    if telegram_id is None and not username:
        raise ValueError("Нужно указать telegram_id или username")

    player = None
    if telegram_id is not None:
        player = db.query(models.Player).filter(models.Player.telegram_id == telegram_id).one_or_none()
    elif username:
        clean = username.strip().lstrip("@")
        player = (
            db.query(models.Player).filter(ci_equals(models.Player.telegram_username, clean)).one_or_none()
        )

    if player is not None:
        if player.is_bot_admin:
            return {"status": "already_admin", "player_id": player.id, "telegram_id": player.telegram_id}
        player.is_bot_admin = True
        db.commit()
        return {"status": "granted", "player_id": player.id, "telegram_id": player.telegram_id}

    if not username:
        raise ValueError("Игрок с таким telegram_id ещё не регистрировался в боте")

    clean = username.strip().lstrip("@").lower()
    existing = db.query(models.PendingBotAdmin).filter(models.PendingBotAdmin.username == clean).one_or_none()
    if existing is not None:
        return {"status": "already_pending", "username": clean}
    db.add(models.PendingBotAdmin(username=clean))
    db.commit()
    return {"status": "pending", "username": clean}


def remove_bot_admin_by_telegram_id(db: Session, *, telegram_id: int) -> bool:
    player = db.query(models.Player).filter(models.Player.telegram_id == telegram_id).one_or_none()
    if player is None or not player.is_bot_admin:
        return False
    player.is_bot_admin = False
    db.commit()
    return True


def remove_pending_by_username(db: Session, *, username: str) -> bool:
    clean = username.strip().lstrip("@").lower()
    pending = db.query(models.PendingBotAdmin).filter(models.PendingBotAdmin.username == clean).one_or_none()
    if pending is None:
        return False
    db.delete(pending)
    db.commit()
    return True


def list_bot_admins(db: Session) -> list[models.Player]:
    return db.query(models.Player).filter(models.Player.is_bot_admin.is_(True)).all()


def list_pending_admins(db: Session) -> list[str]:
    return [p.username for p in db.query(models.PendingBotAdmin).order_by(models.PendingBotAdmin.username).all()]


def consume_pending_admin(db: Session, *, player: models.Player) -> bool:
    """Вызывается при регистрации нового игрока в боте: если его username
    был заранее добавлен в очередь на права админа — выдаёт их сразу."""
    if not player.telegram_username:
        return False
    clean = player.telegram_username.strip().lstrip("@").lower()
    pending = db.query(models.PendingBotAdmin).filter(models.PendingBotAdmin.username == clean).one_or_none()
    if pending is None:
        return False
    db.delete(pending)
    player.is_bot_admin = True
    db.flush()
    return True
