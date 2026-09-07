"""Единая точка правды для группировки/показа игр «по дню».

БД хранит games.starts_at как TIMESTAMPTZ (UTC внутри), это правильно. Но
клуб и бот работают в терминах календарного дня по московскому времени —
группировка "какие игры сегодня"/"список дней" обязана конвертировать в эту
зону перед тем, как брать дату, иначе игра в 00:30 МСК (21:30 UTC предыдущих
суток) попадёт не в тот день.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

CLUB_TZ = ZoneInfo("Europe/Moscow")


def club_day(dt: datetime) -> str:
    return dt.astimezone(CLUB_TZ).strftime("%d.%m.%Y")


def club_day_time(dt: datetime) -> str:
    """«ДД.ММ.ГГГГ ЧЧ:ММ» по клубному времени -- для текстов ошибок."""
    return dt.astimezone(CLUB_TZ).strftime("%d.%m.%Y %H:%M")
