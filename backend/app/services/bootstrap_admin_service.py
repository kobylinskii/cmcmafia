"""Выдача bot-админ прав по конфигу (SUPERADMIN_TELEGRAM_IDS / BOOTSTRAP_ADMIN_PHONE).

Перенесено с клиента (бота) на сервер: раньше `ensure_superadmin`/`ensure_admin_by_phone`
писали в БД напрямую без проверки прав вызывающего. Через авторизованный API
`/api/bot/admin/admins` требует уже быть админом, так что самопожалование первого
админа возможно только здесь, где сервер сам знает доверенный список/номер."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app import models
from app.config import get_settings


def maybe_grant_bootstrap_admin(db: Session, *, player: models.Player) -> bool:
    if player.is_bot_admin:
        return False

    settings = get_settings()
    is_superadmin = player.telegram_id is not None and player.telegram_id in settings.superadmin_telegram_ids
    is_bootstrap_phone = (
        settings.bootstrap_admin_phone is not None and player.phone == settings.bootstrap_admin_phone
    )
    if not (is_superadmin or is_bootstrap_phone):
        return False

    player.is_bot_admin = True
    db.flush()
    return True
