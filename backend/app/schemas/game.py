from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.tournament import TournamentRef, TournamentStageRef

InGameRoleT = Literal["mafia", "don", "sheriff", "citizen"]
GameResultT = Literal["city_win", "mafia_win", "draw"]
ParticipantInfoT = Literal["first_killed", "killed", "voted_out"]
GameTypeT = Literal["tournament", "funky", "training"]
# Вкладка «Игры» в админке создаёт только бот-форматы: турнирные игры теперь
# заводятся исключительно как слоты этапа (см. app.routers.admin, раздел
# турниров) -- там сразу известны tournament_id/stage_id и плейсхолдер-дата.
CreatableGameTypeT = Literal["funky", "training"]

# Поле балла -> (шаг кратности, подпись для ошибки). Шаги заданы регламентом
# клуба и продублированы в форме оценки (frontend/src/components/admin/game-form.tsx).
_STEP_BY_FIELD: dict[str, tuple[float, str]] = {
    "points_win": (0.25, "Баллы за победу"),
    "points_judge": (0.25, "Баллы от судей"),
    "ci": (0.5, "Ci"),
    "lh": (0.5, "lh"),
    "zk": (0.5, "zk"),
    "sk": (0.5, "sk"),
}


class ParticipantIn(BaseModel):
    player_id: int
    seat_number: int = Field(ge=1, le=10)
    role: InGameRoleT
    points_win: float = Field(default=0, ge=0, le=10)
    # Судейские баллы -- от 0 до 5 с шагом 0.25 (регламент клуба).
    points_judge: float = Field(default=0, ge=0, le=5)
    lh: float | None = Field(default=None, ge=0, le=1.5)
    ci: float | None = Field(default=None, ge=-20, le=20)
    info: ParticipantInfoT | None = None
    removals: int | None = Field(default=None, ge=0, le=10)
    ppk: bool = False
    zk: float | None = Field(default=None, ge=0, le=10)
    sk: float | None = Field(default=None, ge=0, le=10)

    @field_validator("points_win", "points_judge", "ci", "lh", "zk", "sk")
    @classmethod
    def _round_to_step(cls, v: float | None, info) -> float | None:
        if v is None:
            return None
        step, name = _STEP_BY_FIELD[info.field_name]
        ratio = v / step
        if abs(ratio - round(ratio)) > 1e-6:
            raise ValueError(f"{name} должен быть кратен {step}")
        return v


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
    # 'tournament' сюда не передать -- тип это запрещает (турнирные игры
    # заводятся только как слоты этапа), поэтому tournament_id/stage_id тут
    # не нужны.
    game_type: CreatableGameTypeT = "funky"
    tournament_id: int | None = None
    stage_id: int | None = None
    result: GameResultT
    notes: str | None = Field(default=None, max_length=2000)
    participants: list[ParticipantIn]


class GameUpdate(BaseModel):
    starts_at: datetime | None = None
    location: str | None = Field(default=None, max_length=200)
    game_type: GameTypeT | None = None
    tournament_id: int | None = None
    stage_id: int | None = None
    result: GameResultT | None = None
    notes: str | None = Field(default=None, max_length=2000)
    participants: list[ParticipantIn] | None = None
    # Осознанная смена состава в турнирной таблице, где уже есть другие
    # оценённые игры. По умолчанию такое отклоняется 422 с кодом
    # ROSTER_MISMATCH -- флаг ставит форма после подтверждения администратором.
    allow_roster_change: bool = False


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
