from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

FavoriteRoleT = Literal["mafia", "don", "sheriff", "citizen"]


class PlayerPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    slug: str
    nickname: str
    full_name: str | None
    age: int | None
    favorite_role: str | None
    experience: str | None
    bio: str | None
    photo_url: str | None


class PlayerListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    slug: str
    nickname: str
    photo_url: str | None


class PlayerStatsOut(BaseModel):
    total_games: int
    wins: int
    losses: int
    draws: int
    win_rate: float | None

    black_card_games: int
    black_card_win_rate: float | None
    red_card_games: int
    red_card_win_rate: float | None
    don_games: int
    don_win_rate: float | None
    sheriff_games: int
    sheriff_win_rate: float | None

    first_kill_count: int
    lh_distribution: dict[str, int]

    rating: float | None
    rating_games_count: int
    rank: int | None

    avg_score: float | None
    avg_bonus: float | None


class PlayerDetailOut(BaseModel):
    """Ответ GET /api/players/{slug}. Раньше ручка возвращала голый dict и в
    OpenAPI выглядела объектом неизвестной формы, хотя обе половины уже были
    описаны схемами."""

    player: PlayerPublic
    stats: PlayerStatsOut


class PlayerCreate(BaseModel):
    nickname: str = Field(min_length=1, max_length=100)
    slug: str = Field(min_length=3, max_length=50)
    full_name: str | None = Field(default=None, max_length=150)
    age: int | None = Field(default=None, ge=5, le=100)
    favorite_role: FavoriteRoleT | None = None
    experience: str | None = Field(default=None, max_length=2000)
    bio: str | None = Field(default=None, max_length=4000)


class PlayerUpdate(BaseModel):
    nickname: str | None = Field(default=None, min_length=1, max_length=100)
    slug: str | None = Field(default=None, min_length=3, max_length=50)
    full_name: str | None = Field(default=None, max_length=150)
    age: int | None = Field(default=None, ge=5, le=100)
    favorite_role: FavoriteRoleT | None = None
    experience: str | None = Field(default=None, max_length=2000)
    bio: str | None = Field(default=None, max_length=4000)


class PlayerAdminOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    nickname: str
    full_name: str | None
    age: int | None
    favorite_role: str | None
    experience: str | None
    bio: str | None
    photo_url: str | None
    is_active: bool
    confirmation_status: str
    rejection_reason: str | None
    is_bot_admin: bool
    is_site_admin: bool
    site_username: str | None
    telegram_id: int | None
    telegram_username: str | None
    created_at: datetime


class SiteAccessGrantOut(BaseModel):
    site_username: str
    temp_password: str
