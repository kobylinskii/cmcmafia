from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

IN_GAME_ROLES = {"mafia", "don", "sheriff", "citizen"}
GAME_RESULTS = {"city_win", "mafia_win", "draw"}
INFO_VALUES = {"first_killed", "killed", "voted_out"}
GAME_TYPES = {"tournament", "funky", "training"}


def _round_half_step(value: float | None, step: float, field_name: str) -> float | None:
    if value is None:
        return None
    ratio = value / step
    if abs(ratio - round(ratio)) > 1e-6:
        raise ValueError(f"{field_name} должен быть кратен {step}")
    return value


class ParticipantIn(BaseModel):
    player_id: int
    seat_number: int = Field(ge=1, le=10)
    role: str
    points_win: float = Field(default=0, ge=0, le=10)
    points_judge: float = Field(default=0, ge=-10, le=10)
    lh: float | None = Field(default=None, ge=0, le=1.5)
    ci: float | None = Field(default=None, ge=-20, le=20)
    info: str | None = None
    removals: int | None = Field(default=None, ge=0, le=10)
    ppk: bool = False
    zk: float | None = Field(default=None, ge=0, le=10)
    sk: float | None = Field(default=None, ge=0, le=10)

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in IN_GAME_ROLES:
            raise ValueError(f"role должен быть одним из {IN_GAME_ROLES}")
        return v

    @field_validator("info")
    @classmethod
    def validate_info(cls, v: str | None) -> str | None:
        if v is not None and v not in INFO_VALUES:
            raise ValueError(f"info должен быть одним из {INFO_VALUES}")
        return v

    @field_validator("lh")
    @classmethod
    def validate_lh(cls, v: float | None) -> float | None:
        return _round_half_step(v, 0.5, "lh")

    @field_validator("zk")
    @classmethod
    def validate_zk(cls, v: float | None) -> float | None:
        return _round_half_step(v, 0.5, "zk")

    @field_validator("sk")
    @classmethod
    def validate_sk(cls, v: float | None) -> float | None:
        return _round_half_step(v, 0.5, "sk")


class ParticipantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    seat_number: int
    role: str
    points_win: float
    points_judge: float
    lh: float | None
    ci: float | None
    info: str | None
    removals: int | None
    ppk: bool
    zk: float | None
    sk: float | None

    player_slug: str
    player_nickname: str


class GameCreate(BaseModel):
    starts_at: datetime
    location: str | None = Field(default=None, max_length=200)
    game_type: str = "tournament"
    result: str
    notes: str | None = Field(default=None, max_length=2000)
    participants: list[ParticipantIn]

    @field_validator("game_type")
    @classmethod
    def validate_game_type(cls, v: str) -> str:
        if v not in GAME_TYPES:
            raise ValueError(f"game_type должен быть одним из {GAME_TYPES}")
        return v

    @field_validator("result")
    @classmethod
    def validate_result(cls, v: str) -> str:
        if v not in GAME_RESULTS:
            raise ValueError(f"result должен быть одним из {GAME_RESULTS}")
        return v


class GameUpdate(BaseModel):
    starts_at: datetime | None = None
    location: str | None = Field(default=None, max_length=200)
    game_type: str | None = None
    result: str | None = None
    notes: str | None = Field(default=None, max_length=2000)
    participants: list[ParticipantIn] | None = None

    @field_validator("game_type")
    @classmethod
    def validate_game_type(cls, v: str | None) -> str | None:
        if v is not None and v not in GAME_TYPES:
            raise ValueError(f"game_type должен быть одним из {GAME_TYPES}")
        return v

    @field_validator("result")
    @classmethod
    def validate_result(cls, v: str | None) -> str | None:
        if v is not None and v not in GAME_RESULTS:
            raise ValueError(f"result должен быть одним из {GAME_RESULTS}")
        return v


class GameOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    starts_at: datetime
    location: str | None
    game_type: str
    status: str
    result: str | None
    notes: str | None
    participants: list[ParticipantOut]


class GameListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    starts_at: datetime
    location: str | None
    game_type: str
    result: str | None


class GameListOut(BaseModel):
    items: list[GameListItem]
    total: int
