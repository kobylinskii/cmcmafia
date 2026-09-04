from __future__ import annotations

from pydantic import BaseModel


class RatingRowOut(BaseModel):
    rank: int
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
