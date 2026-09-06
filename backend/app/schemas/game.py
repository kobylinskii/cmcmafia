from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.tournament import TournamentRef, TournamentStageRef

IN_GAME_ROLES = {"mafia", "don", "sheriff", "citizen"}
GAME_RESULTS = {"city_win", "mafia_win", "draw"}
INFO_VALUES = {"first_killed", "killed", "voted_out"}
GAME_TYPES = {"tournament", "funky", "training"}
# Вкладка «Игры» в админке создаёт только бот-форматы: турнирные игры теперь
# заводятся исключительно как слоты этапа (см. app.routers.admin, раздел
# турниров) -- там сразу известны tournament_id/stage_id и плейсхолдер-дата.
CREATABLE_GAME_TYPES = {"funky", "training"}


def _round_half_step(value: float | None, step: float, field_name: str) -> float | None:
    """Значение должно быть кратно шагу. Шаги заданы регламентом клуба и
    продублированы в форме оценки (frontend/src/components/admin/game-form.tsx)."""
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
    # Судейские баллы -- от 0 до 5 с шагом 0.25 (регламент клуба).
    points_judge: float = Field(default=0, ge=0, le=5)
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

    @field_validator("points_win")
    @classmethod
    def validate_points_win(cls, v: float) -> float:
        return _round_half_step(v, 0.25, "Баллы за победу")

    @field_validator("points_judge")
    @classmethod
    def validate_points_judge(cls, v: float) -> float:
        return _round_half_step(v, 0.25, "Баллы от судей")

    @field_validator("ci")
    @classmethod
    def validate_ci(cls, v: float | None) -> float | None:
        return _round_half_step(v, 0.5, "Ci")

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
    game_type: str = "funky"
    # tournament_id/stage_id тут больше не нужны: 'tournament' вообще нельзя
    # передать через этот эндпоинт (см. validate_game_type ниже).
    tournament_id: int | None = None
    stage_id: int | None = None
    result: str
    notes: str | None = Field(default=None, max_length=2000)
    participants: list[ParticipantIn]

    @field_validator("game_type")
    @classmethod
    def validate_game_type(cls, v: str) -> str:
        if v not in CREATABLE_GAME_TYPES:
            raise ValueError(f"game_type должен быть одним из {CREATABLE_GAME_TYPES}")
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
    tournament_id: int | None = None
    stage_id: int | None = None
    result: str | None = None
    notes: str | None = Field(default=None, max_length=2000)
    participants: list[ParticipantIn] | None = None
    # Осознанная смена состава в турнирной таблице, где уже есть другие
    # оценённые игры. По умолчанию такое отклоняется 422 с кодом
    # ROSTER_MISMATCH -- флаг ставит форма после подтверждения администратором.
    allow_roster_change: bool = False

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


class GameRosterEntry(BaseModel):
    """Кто записался на игру ДО неё (ведущий/судья/игрок) -- это не то же самое,
    что participants (места за столом с ролями и баллами, заполняются после).
    Нужен админке, чтобы форма оценки игры из бота открывалась с уже
    подставленным составом, а не пустой (ARCHITECTURE.md, раздел 8, шаг 4)."""

    model_config = ConfigDict(from_attributes=True)

    player_id: int
    nickname: str
    role: str


class GameOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    starts_at: datetime
    location: str | None
    game_type: str
    status: str
    result: str | None
    notes: str | None
    tournament: TournamentRef | None = None
    stage: TournamentStageRef | None = None
    participants: list[ParticipantOut]
    # Пусто в публичном ответе: там игра уже оценена, состав виден в participants.
    roster: list[GameRosterEntry] = []


class GameListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    starts_at: datetime
    location: str | None
    game_type: str
    result: str | None
    tournament: TournamentRef | None = None


class GameListOut(BaseModel):
    items: list[GameListItem]
    total: int
