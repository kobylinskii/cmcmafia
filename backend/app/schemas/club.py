"""Схемы вкладки «Обзор» в админке: модерация игроков и списки на пропуск."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

WEEKDAY_LABELS = (
    "понедельник",
    "вторник",
    "среда",
    "четверг",
    "пятница",
    "суббота",
    "воскресенье",
)


class PendingPlayerOut(BaseModel):
    """Карточка заявки: всё, что человек указал о себе в боте, чтобы решение
    принималось без перехода на отдельную страницу игрока."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    nickname: str
    slug: str
    full_name: str | None
    salutation: str | None
    affiliation: str | None
    phone: str | None
    telegram_id: int | None
    telegram_username: str | None
    can_play: bool
    can_staff: bool
    age: int | None
    favorite_role: str | None
    experience: str | None
    bio: str | None
    created_at: datetime


class ProfileChangeOut(BaseModel):
    """Строка очереди правок: кто, какое поле и на что меняет.

    `current_value` считается на момент чтения, а не хранится: пока правка
    ждала, поле мог поменять и сам админ на сайте, и сравнивать надо с тем,
    что действительно будет перезаписано.
    """

    id: int
    player_id: int
    player_nickname: str
    player_slug: str
    telegram_username: str | None
    field: str
    field_label: str
    current_value: str | None
    new_value: str | None
    created_at: datetime


class ProfileChangeRejectIn(BaseModel):
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Нужно указать причину отклонения")
        return cleaned


class BotProfileChangeNotificationOut(BaseModel):
    """Решение по правке, о котором игрок ещё не знает."""

    change_id: int
    telegram_id: int
    field_label: str
    new_value: str | None
    status: str
    rejection_reason: str | None


class BotProfileChangeAckIn(BaseModel):
    change_ids: list[int]


class PlayerRejectIn(BaseModel):
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Нужно указать причину отклонения")
        return cleaned


class PassWeekSettingsIn(BaseModel):
    pass_week_rollover_weekday: int = Field(ge=0, le=6)
    pass_week_rollover_time: str = Field(pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")


class PassWeekSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pass_week_rollover_weekday: int
    pass_week_rollover_time: str


class PassListGameOut(BaseModel):
    game_id: int
    starts_at: datetime
    game_type: str
    location: str | None
    role: str


class PassListEntryOut(BaseModel):
    player_id: int
    nickname: str
    full_name: str | None
    phone: str | None
    confirmation_status: str
    games: list[PassListGameOut]


class PassListOut(BaseModel):
    """Окно недели отдаётся вместе со списком: подпись «с ... по ...» на
    странице должна показывать ровно тот интервал, по которому отобраны
    строки, а не пересчитанный в браузере по своим часам."""

    week_start: datetime
    week_end: datetime
    rollover_weekday: int
    rollover_time: str
    entries: list[PassListEntryOut]


class BotConfirmationNotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    player_id: int = Field(validation_alias="id")
    telegram_id: int
    nickname: str
    confirmation_status: str
    rejection_reason: str | None


class BotConfirmationAckIn(BaseModel):
    player_ids: list[int] = Field(min_length=1, max_length=100)
