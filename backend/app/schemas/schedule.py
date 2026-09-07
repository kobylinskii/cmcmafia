"""Схемы планировщика игр в админке сайта (вкладка «Игры → Расписание»).

Раньше эти же данные ходили через `/api/bot/admin/sessions/*` и жили в
schemas/bot.py. Представление самой сессии (`SessionOut`) осталось общим --
бот показывает те же слоты в записи, -- а вот вход планировщика здесь свой:
бот создавал день диапазоном целых часов, сайт задаёт шаг и количество.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.bot import GameTypeLiteral, RosterOut, SessionOut

# Шаг между слотами. Минимум -- полчаса (короче игра не заканчивается),
# максимум -- полсуток: больше означает, что админ перепутал поле.
MIN_STEP_MINUTES = 30
MAX_STEP_MINUTES = 720


class SchedulePlanIn(BaseModel):
    """Пачка слотов одним нажатием: первый в `starts_at`, дальше через шаг."""

    starts_at: datetime
    count: int = Field(ge=1, le=48)
    step_minutes: int = Field(default=60, ge=MIN_STEP_MINUTES, le=MAX_STEP_MINUTES)
    location: str = Field(min_length=1, max_length=200)
    game_type: GameTypeLiteral
    # По умолчанию игра оценивается: так работал единственный существовавший
    # до этого флоу, и «забыл поставить галочку» не должно тихо выкидывать
    # игру из рейтинга.
    needs_rating: bool = True


class SchedulePlanPreviewOut(BaseModel):
    """Во что развернётся план и что из этого уже занято.

    Предпросмотр отдельной ручкой, а не «попробуй создать и разбери ошибку»:
    админ должен увидеть все десять времён и оба конфликта разом, до записи.
    """

    starts_at_list: list[datetime]
    conflicts: list[datetime]


class ScheduleSessionUpdateIn(BaseModel):
    starts_at: datetime | None = None
    location: str | None = Field(default=None, min_length=1, max_length=200)
    game_type: GameTypeLiteral | None = None
    needs_rating: bool | None = None


class ScheduleDayOut(BaseModel):
    day: str
    types: list[str]
    games_count: int
    # Сколько игр этого дня ждут ответа «состоялась или нет». Счётчик прямо в
    # строке дня: иначе единственный способ узнать, что что-то забыто, --
    # открыть каждый день по очереди.
    awaiting_count: int
    first_starts_at: datetime


class ScheduleSessionOut(SessionOut):
    """Карточка слота: сессия плюс кто на неё записан."""

    roster: RosterOut
