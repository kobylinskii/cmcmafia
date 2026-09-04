from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

AFFILIATIONS = {"vmk", "mgu_no_pass", "outside_need_pass"}
GAME_TYPES = {"tournament", "funky", "training"}


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


class BotPlayerProfileUpdateIn(BaseModel):
    salutation: str | None = Field(default=None, max_length=20)
    full_name: str | None = Field(default=None, max_length=150)
    affiliation: str | None = None
    nickname: str | None = Field(default=None, min_length=2, max_length=100)
    can_play: bool | None = None
    can_staff: bool | None = None

    @field_validator("affiliation")
    @classmethod
    def validate_affiliation(cls, v: str | None) -> str | None:
        if v is not None and v not in AFFILIATIONS:
            raise ValueError(f"affiliation должен быть одним из {AFFILIATIONS}")
        return v


class SessionOut(BaseModel):
    id: int
    starts_at: datetime
    location: str | None
    game_type: str
    status: str
    registration_until: datetime | None
    is_open: bool
    hosts: int
    judges: int
    players: int
    max_players: int
    reserves: int


class SessionCreateIn(BaseModel):
    starts_at: datetime
    location: str = Field(min_length=1, max_length=200)
    game_type: str = "tournament"
    registration_until: datetime | None = None
    max_players: int = Field(default=10, ge=2, le=20)

    @field_validator("game_type")
    @classmethod
    def validate_game_type(cls, v: str) -> str:
        if v not in GAME_TYPES:
            raise ValueError(f"game_type должен быть одним из {GAME_TYPES}")
        return v


class SessionUpdateIn(BaseModel):
    starts_at: datetime | None = None
    location: str | None = Field(default=None, max_length=200)
    game_type: str | None = None
    registration_until: datetime | None = None


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


class BulkSessionCreateIn(BaseModel):
    starts_at_list: list[datetime] = Field(min_length=1, max_length=48)
    location: str = Field(min_length=1, max_length=200)
    game_type: str

    @field_validator("game_type")
    @classmethod
    def validate_game_type(cls, v: str) -> str:
        if v not in GAME_TYPES:
            raise ValueError(f"game_type должен быть одним из {GAME_TYPES}")
        return v


class ConflictCheckIn(BaseModel):
    starts_at_list: list[datetime]
    exclude_session_ids: list[int] = Field(default_factory=list)


class DayCardOut(BaseModel):
    day: str
    types: list[str]


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
