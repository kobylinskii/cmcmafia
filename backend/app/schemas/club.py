"""Схемы модерации игроков и списков на пропуск.

Решение по заявке и по правке принимается в Telegram (раздел 3.8); на вкладке
«Обзор» остались только списки на пропуск.
"""

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


class _RejectIn(BaseModel):
    """Общее тело отказа: причину видит игрок в боте, пустая недопустима."""

    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def _strip_reason(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Нужно указать причину отклонения")
        return cleaned


class ProfileChangeRejectIn(_RejectIn):
    pass


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


class PlayerRejectIn(_RejectIn):
    pass


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


class AdminRegistrationNoticeOut(BaseModel):
    """Новая заявка на вступление -- то, что боту нужно, чтобы написать админам."""

    player_id: int
    nickname: str
    full_name: str | None
    affiliation: str | None
    telegram_username: str | None
    created_at: datetime


class AdminProfileChangeNoticeOut(BaseModel):
    """Новая правка профиля, ждущая проверки."""

    change_id: int
    player_nickname: str
    telegram_username: str | None
    field_label: str
    current_value: str | None
    new_value: str | None
    created_at: datetime


class BotModerationQueueOut(BaseModel):
    """Всё, что сейчас ждёт решения, -- раздел «На проверке» в админ-меню бота.

    Отличается от BotAdminNotificationsOut ровно одним, но важным: это полная
    очередь, а не «о чём ещё не писали». Уведомление можно удалить из чата, и
    без такого списка незакрытая заявка после ack'а не всплыла бы больше нигде.
    """

    registrations: list[AdminRegistrationNoticeOut]
    profile_changes: list[AdminProfileChangeNoticeOut]


class BotAdminNotificationsOut(BaseModel):
    """Очередь оповещения админов сайта: что появилось на проверку и кому писать.

    `recipients` -- telegram_id админов сайта с привязанным Telegram. Пустой
    список означает «писать некому»: бот тогда ничего не делает и не
    подтверждает очередь, строки дождутся админа с привязанным Telegram.
    """

    recipients: list[int]
    registrations: list[AdminRegistrationNoticeOut]
    profile_changes: list[AdminProfileChangeNoticeOut]


class DayReminderGameOut(BaseModel):
    """Одна игра дня в напоминании -- бот собирает из них текст сообщения."""

    starts_at: datetime
    game_type: str
    location: str | None


class DayReminderOut(BaseModel):
    """Один клубный день, о котором пора напомнить записавшимся."""

    day: str
    # Первая игра дня: её id бот присылает обратно ack'ом как «разослано».
    marker_game_id: int
    games: list[DayReminderGameOut]
    recipients: list[int]


class DayRemindersAckIn(BaseModel):
    game_ids: list[int] = Field(min_length=1, max_length=100)


class BotAdminNotificationsAckIn(BaseModel):
    registration_player_ids: list[int] = Field(default_factory=list, max_length=100)
    profile_change_ids: list[int] = Field(default_factory=list, max_length=100)
