from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TournamentRef(BaseModel):
    """Минимальная ссылка на турнир внутри ответа об игре.

    id нужен админке: после оценки турнирной игры форма возвращает не в общий
    список игр, а в карточку того же турнира, откуда админ пришёл."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    name: str


class TournamentStageRef(BaseModel):
    """Минимальная ссылка на этап внутри ответа об игре."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class TournamentStageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tournament_id: int
    name: str
    order: int
    is_final: bool = False
    games_count: int = 0


class TournamentStageCreate(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    order: int | None = Field(default=None, ge=1, le=1000)
    # Сразу создаёт games_count пустых игровых слотов этапа (без участников,
    # статус 'scheduled', дата -- плейсхолдер по дате начала турнира). Список
    # можно донабрать/сократить позже через отдельные ручки на конкретный слот.
    games_count: int = Field(ge=1, le=64)
    # На публичной странице турнира таблица финального этапа развёрнута по
    # умолчанию. У турнира одновременно может быть отмечен только один
    # финальный этап -- см. tournament_service.create_stage/update_stage.
    is_final: bool = False


class TournamentStageUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    order: int | None = Field(default=None, ge=1, le=1000)
    is_final: bool | None = None


class TournamentStageGameOut(BaseModel):
    """Один игровой слот этапа для панели админки: список из N слотов, часть
    уже оценена (status='rated', есть result), часть ещё нет."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    starts_at: datetime
    location: str | None
    status: str
    result: str | None


class AddStageGamesIn(BaseModel):
    count: int = Field(default=1, ge=1, le=64)


class TournamentStageAdvancesIn(BaseModel):
    player_ids: list[int]


class TournamentStageAdvancesOut(BaseModel):
    player_ids: list[int]


class TournamentPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    slug: str
    name: str
    description: str | None
    location: str | None
    starts_at: datetime
    ends_at: datetime


class TournamentListItem(BaseModel):
    slug: str
    name: str
    location: str | None
    games_count: int


class TournamentStandingOut(BaseModel):
    rank: int
    slug: str
    nickname: str
    photo_url: str | None
    games_count: int
    points_win: float
    points_judge: float
    lh_points: float
    ci: float
    removals: int
    ppk_count: int
    zk: float
    sk: float
    total_score: float
    # Осмысленно только внутри таблицы КОНКРЕТНОГО этапа (см.
    # TournamentStageDetailOut) -- прошёл ли игрок дальше по итогам этой
    # сводной таблицы. В плоской таблице турнира без сеток всегда false.
    advanced: bool = False


class TournamentStagePublicGameOut(BaseModel):
    """Один пронумерованный слот этапа для публичной страницы турнира --
    оценённый ведёт на карточку игры, ещё не оценённый просто показывает
    место в очереди."""

    number: int
    id: int
    starts_at: datetime
    status: str
    result: str | None


class TournamentStageDetailOut(BaseModel):
    id: int
    name: str
    order: int
    is_final: bool = False
    standings: list[TournamentStandingOut]
    games: list[TournamentStagePublicGameOut] = []


class TournamentDetailOut(BaseModel):
    tournament: TournamentPublic
    games_count: int
    # У турнира без сеток -- одна общая таблица, stages пуст (как было раньше).
    # У турнира с сетками -- по таблице на каждый этап, а standings НЕ несёт
    # общую сумму по всему турниру: складывать очки игроков, сыгравших разное
    # число игр на разных этапах, в одну строку -- ровно та проблема, ради
    # которой сетки и завели. Игры без этапа (staged-турнир, но конкретную
    # игру ещё не разнесли по этапам) попадают в псевдо-этап "Без этапа".
    standings: list[TournamentStandingOut]
    stages: list[TournamentStageDetailOut] = []


class TournamentCreate(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    slug: str = Field(min_length=2, max_length=50)
    # Период проведения турнира -- обязателен у любого турнира, даже
    # однодневного (starts_at == ends_at). Даты конкретных игр выставляются
    # отдельно, по слоту (турнир часто идёт в несколько заходов).
    starts_at: datetime
    ends_at: datetime
    description: str | None = Field(default=None, max_length=4000)
    location: str | None = Field(default=None, max_length=200)


class TournamentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    slug: str | None = Field(default=None, min_length=2, max_length=50)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    description: str | None = Field(default=None, max_length=4000)
    location: str | None = Field(default=None, max_length=200)


class TournamentAdminOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    name: str
    description: str | None
    location: str | None
    starts_at: datetime
    ends_at: datetime
    created_at: datetime
    games_count: int = 0
