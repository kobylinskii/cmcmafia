from __future__ import annotations

from pydantic import BaseModel


class RatingLegendItem(BaseModel):
    symbol: str
    text: str


class RatingKTier(BaseModel):
    condition: str
    k: int
    removal_penalty: float
    ppk_penalty: float


class GameTypeWeight(BaseModel):
    game_type: str
    label: str
    weight: float
    rated: bool


class RatingFormulaOut(BaseModel):
    intro: str
    start_rating: float
    formula: str
    legend: list[RatingLegendItem]
    expected_score_min: float
    expected_score_max: float
    k_tiers: list[RatingKTier]
    note: str
    game_type_weights: list[GameTypeWeight]
    training_note: str


class RatingRowOut(BaseModel):
    # null у найденного поиском игрока без единой сыгранной игры: места в
    # рейтинге у него ещё нет (stats_service.rating_table).
    rank: int | None
    slug: str
    nickname: str
    photo_url: str | None
    rating: float
    games_count: int
    win_rate: float | None
    avg_bonus: float | None


class RatingTableOut(BaseModel):
    items: list[RatingRowOut]
    total: int
