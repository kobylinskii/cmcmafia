from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

AFFILIATIONS = {"vmk", "mgu_no_pass", "outside_need_pass"}
# Те же значения, что и у анкеты игрока на сайте (app/schemas/player.ROLE_VALUES):
# бот заполняет ровно то же поле players.favorite_role.
FAVORITE_ROLES = {"mafia", "don", "sheriff", "citizen"}
# Турнирные игры больше не создаются и не набираются через бота вообще:
# у них теперь своя сетка этапов, управляемая целиком на сайте (см. раздел
# «Турниры» в админке). Бот работает только с фанки/обучающими сессиями.
GAME_TYPES = {"funky", "training"}


class BotPlayerRegisterIn(BaseModel):
    telegram_id: int
    telegram_username: str | None = None
    phone: str = Field(min_length=5, max_length=20)
    nickname: str = Field(min_length=2, max_length=100)
    salutation: str = Field(min_length=1, max_length=20)
    full_name: str | None = Field(default=None, max_length=150)
    affiliation: str
    can_play: bool = True
    can_staff: bool = True

    @field_validator("affiliation")
    @classmethod
    def validate_affiliation(cls, v: str) -> str:
        if v not in AFFILIATIONS:
            raise ValueError(f"affiliation должен быть одним из {AFFILIATIONS}")
        return v

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, v: str) -> str:
        digits = "".join(ch for ch in v if ch.isdigit())
        if not digits:
            raise ValueError("Некорректный номер телефона")
        return digits


class BotPlayerProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    telegram_id: int | None
    nickname: str
    slug: str
    salutation: str | None
    full_name: str | None
    affiliation: str | None
    phone: str | None
    can_play: bool
    can_staff: bool
    is_bot_admin: bool
    # Анкетные поля с сайта -- бот показывает их в профиле и даёт заполнить
    # всё, кроме фото.
    age: int | None
    favorite_role: str | None
    experience: str | None
    bio: str | None
    # Модерация регистрации (models.ConfirmationStatus): бот показывает статус
    # в профиле и предлагает отклонённому отправиться на повторную проверку.
    confirmation_status: str
    rejection_reason: str | None
    # Правки, ждущие решения админа: {поле: новое значение}. Значение null --
    # запрошенная очистка поля. В самом профиле поля остаются прежними, и
    # бот показывает эту пару рядом («сейчас X, на проверке Y»).
    pending_changes: dict[str, str | None] = {}


class BotPlayerProfileUpdateIn(BaseModel):
    salutation: str | None = Field(default=None, max_length=20)
    full_name: str | None = Field(default=None, max_length=150)
    affiliation: str | None = None
    nickname: str | None = Field(default=None, min_length=2, max_length=100)
    can_play: bool | None = None
    can_staff: bool | None = None
    age: int | None = Field(default=None, ge=5, le=100)
    favorite_role: str | None = None
    experience: str | None = Field(default=None, max_length=2000)
    bio: str | None = Field(default=None, max_length=4000)

    @field_validator("affiliation")
    @classmethod
    def validate_affiliation(cls, v: str | None) -> str | None:
        if v is not None and v not in AFFILIATIONS:
            raise ValueError(f"affiliation должен быть одним из {AFFILIATIONS}")
        return v

    @field_validator("favorite_role")
    @classmethod
    def validate_favorite_role(cls, v: str | None) -> str | None:
        if v is not None and v not in FAVORITE_ROLES:
            raise ValueError(f"favorite_role должен быть одним из {FAVORITE_ROLES}")
        return v


class SessionOut(BaseModel):
    id: int
    starts_at: datetime
    location: str | None
    game_type: str
    status: str
    # Будет ли игра оцениваться. Бот этим полем не пользуется -- оно нужно
    # планировщику на сайте, но представление сессии в проекте одно.
    needs_rating: bool
    registration_until: datetime | None
    is_open: bool
    hosts: int
    judges: int
    players: int
    max_players: int
    reserves: int


class RegisterIn(BaseModel):
    telegram_id: int
    role_kind: str = Field(pattern="^(player|staff)$")
    available_from: str | None = None
    available_until: str | None = None


class ReserveIn(BaseModel):
    telegram_id: int


class RegistrationOut(BaseModel):
    ok: bool
    message: str
    reason: str | None = None
    promoted_telegram_id: int | None = None
    promoted_nickname: str | None = None
    # Чем закончилась запись: роль за столом либо 'reserve' с номером в
    # очереди. Одиннадцатый игрок попадает в резерв тем же нажатием, что и
    # первый десяток, и узнать об этом бот может только отсюда.
    role: str | None = None
    is_reserve: bool = False
    reserve_position: int | None = None


class MyRegistrationOut(BaseModel):
    game_id: int
    starts_at: datetime
    location: str | None
    game_type: str
    role: str
    is_reserve: bool


class BotAdminGrantIn(BaseModel):
    telegram_id: int | None = None
    username: str | None = None


class RosterMemberOut(BaseModel):
    nickname: str
    telegram_id: int | None
    telegram_username: str | None
    role: str


class ReserveMemberOut(BaseModel):
    nickname: str
    telegram_id: int | None


class RosterOut(BaseModel):
    registrations: list[RosterMemberOut]
    reserves: list[ReserveMemberOut]


class PlayerLookupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    telegram_id: int | None
    nickname: str


class AdminInfoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    telegram_id: int | None
    nickname: str
    telegram_username: str | None


class BroadcastPlayerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    telegram_id: int
    nickname: str


class BroadcastAudienceOut(BaseModel):
    """Кому уйдёт произвольное сообщение админа."""

    recipients: list[BroadcastPlayerOut]


class WeeklyBroadcastOut(BaseModel):
    """Всё, что боту нужно для анонса игр на неделю: что рассылать и кому."""

    days: int
    games: list[SessionOut]
    recipients: list[BroadcastPlayerOut]


class BotPlayerStatsOut(BaseModel):
    """Очень короткая выжимка для карточки профиля в боте.

    Отдельная ручка, а не поля в /players/me: профиль читается почти на каждое
    нажатие кнопки, а статистика -- это тяжёлый агрегат по всем играм.
    """

    total_games: int
    wins: int
    win_rate: float | None
    rating: float | None
    rating_games_count: int
    rank: int | None
