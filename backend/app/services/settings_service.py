"""Клубные настройки, которые правит админ из интерфейса (models.ClubSettings)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app import models

SETTINGS_ID = 1


def get_settings(db: Session) -> models.ClubSettings:
    """Строку создаёт миграция; ленивая вставка здесь -- страховка для базы,
    которую вычистили TRUNCATE'ом (так делают тесты)."""
    settings = db.get(models.ClubSettings, SETTINGS_ID)
    if settings is None:
        settings = models.ClubSettings(id=SETTINGS_ID)
        db.add(settings)
        db.flush()
    return settings


def update_settings(
    db: Session, *, pass_week_rollover_weekday: int, pass_week_rollover_time: str
) -> models.ClubSettings:
    settings = get_settings(db)
    settings.pass_week_rollover_weekday = pass_week_rollover_weekday
    settings.pass_week_rollover_time = pass_week_rollover_time
    db.flush()
    return settings
