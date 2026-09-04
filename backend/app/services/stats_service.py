from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import and_, case, func, or_
from sqlalchemy.orm import Session

from app import models

# Mirrors rating_service.LH_RATING_VALUE (Python) as a SQL CASE for the
# rating-table aggregate below -- keep the two in sync if this mapping changes.
_LH_RATING_SQL = case(
    (models.GameParticipant.lh == 1.5, 1.0),
    (models.GameParticipant.lh == 1.0, 0.5),
    else_=0.0,
)

BLACK_ROLES = ("mafia", "don")
RED_ROLES = ("citizen", "sheriff")


def list_rated_games(
    db: Session,
    *,
    limit: int = 10,
    offset: int = 0,
    date_from: date | None = None,
    date_to: date | None = None,
    game_type: str | None = None,
    result: str | None = None,
    player_slug: str | None = None,
) -> tuple[list[models.Game], int]:
    query = db.query(models.Game).filter(models.Game.status == "rated")
    if date_from:
        query = query.filter(models.Game.starts_at >= date_from)
    if date_to:
        query = query.filter(models.Game.starts_at < date_to)
    if game_type:
        query = query.filter(models.Game.game_type == game_type)
    if result:
        query = query.filter(models.Game.result == result)
    if player_slug:
        query = query.filter(
            models.Game.id.in_(
                db.query(models.GameParticipant.game_id)
                .join(models.Player, models.Player.id == models.GameParticipant.player_id)
                .filter(models.Player.slug == player_slug)
            )
        )

    total = query.count()
    rows = (
        query.order_by(models.Game.starts_at.desc(), models.Game.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return rows, total


def get_rated_game(db: Session, game_id: int) -> models.Game | None:
    return (
        db.query(models.Game)
        .filter(models.Game.id == game_id, models.Game.status == "rated")
        .one_or_none()
    )


@dataclass
class RatingRow:
    player: models.Player
    rank: int
    rating: float
    games_count: int
    win_rate: float | None
    avg_bonus: float | None


def rating_table(db: Session, *, q: str | None = None, limit: int = 50, offset: int = 0) -> tuple[list[RatingRow], int]:
    avg_bonus_subq = (
        db.query(
            models.GameParticipant.player_id.label("player_id"),
            func.avg(
                models.GameParticipant.points_judge
                + _LH_RATING_SQL
                + func.coalesce(models.GameParticipant.ci, 0)
            ).label("avg_bonus"),
        )
        .join(models.Game, models.Game.id == models.GameParticipant.game_id)
        .filter(models.Game.status == "rated")
        .group_by(models.GameParticipant.player_id)
        .subquery()
    )

    query = (
        db.query(models.Player, models.PlayerRating, avg_bonus_subq.c.avg_bonus)
        .join(models.PlayerRating, models.PlayerRating.player_id == models.Player.id)
        .outerjoin(avg_bonus_subq, avg_bonus_subq.c.player_id == models.Player.id)
        .filter(models.Player.is_active.is_(True), models.PlayerRating.games_count > 0)
    )
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(models.Player.nickname.ilike(like))

    total = query.count()
    query = query.order_by(models.PlayerRating.rating.desc())
    rows = query.offset(offset).limit(limit).all()

    result: list[RatingRow] = []
    for idx, (player, rating, avg_bonus) in enumerate(rows, start=offset + 1):
        games_count = rating.games_count
        win_rate = (rating.wins / games_count) if games_count else None
        result.append(
            RatingRow(
                player=player,
                rank=idx,
                rating=float(rating.rating),
                games_count=games_count,
                win_rate=win_rate,
                avg_bonus=float(avg_bonus) if avg_bonus is not None else None,
            )
        )
    return result, total


@dataclass
class PlayerStats:
    total_games: int = 0
    wins: int = 0
    losses: int = 0
    draws: int = 0

    black_card_games: int = 0
    black_card_wins: int = 0
    red_card_games: int = 0
    red_card_wins: int = 0
    don_games: int = 0
    don_wins: int = 0
    sheriff_games: int = 0
    sheriff_wins: int = 0

    first_kill_count: int = 0
    lh_0: int = 0
    lh_05: int = 0
    lh_1: int = 0
    lh_15: int = 0

    rating: float | None = None
    rating_games_count: int = 0
    rank: int | None = None

    avg_score: float | None = None
    avg_bonus: float | None = None

    @property
    def win_rate(self) -> float | None:
        return self.wins / self.total_games if self.total_games else None

    @property
    def black_card_win_rate(self) -> float | None:
        return self.black_card_wins / self.black_card_games if self.black_card_games else None

    @property
    def red_card_win_rate(self) -> float | None:
        return self.red_card_wins / self.red_card_games if self.red_card_games else None

    @property
    def don_win_rate(self) -> float | None:
        return self.don_wins / self.don_games if self.don_games else None

    @property
    def sheriff_win_rate(self) -> float | None:
        return self.sheriff_wins / self.sheriff_games if self.sheriff_games else None


def compute_player_stats(db: Session, player_id: int) -> PlayerStats:
    won_expr = or_(
        and_(models.GameParticipant.role.in_(BLACK_ROLES), models.Game.result == "mafia_win"),
        and_(models.GameParticipant.role.in_(RED_ROLES), models.Game.result == "city_win"),
    )

    row = (
        db.query(
            func.count().label("total_games"),
            func.count().filter(won_expr).label("wins"),
            func.count()
            .filter(~won_expr, models.Game.result != "draw")
            .label("losses"),
            func.count().filter(models.Game.result == "draw").label("draws"),
            func.count().filter(models.GameParticipant.role.in_(BLACK_ROLES)).label("black_card_games"),
            func.count()
            .filter(models.GameParticipant.role.in_(BLACK_ROLES), won_expr)
            .label("black_card_wins"),
            func.count().filter(models.GameParticipant.role.in_(RED_ROLES)).label("red_card_games"),
            func.count()
            .filter(models.GameParticipant.role.in_(RED_ROLES), won_expr)
            .label("red_card_wins"),
            func.count().filter(models.GameParticipant.role == "don").label("don_games"),
            func.count().filter(models.GameParticipant.role == "don", won_expr).label("don_wins"),
            func.count().filter(models.GameParticipant.role == "sheriff").label("sheriff_games"),
            func.count()
            .filter(models.GameParticipant.role == "sheriff", won_expr)
            .label("sheriff_wins"),
            func.count().filter(models.GameParticipant.info == "first_killed").label("first_kill_count"),
            func.count()
            .filter(models.GameParticipant.info == "first_killed", models.GameParticipant.lh == 0)
            .label("lh_0"),
            func.count()
            .filter(models.GameParticipant.info == "first_killed", models.GameParticipant.lh == 0.5)
            .label("lh_05"),
            func.count()
            .filter(models.GameParticipant.info == "first_killed", models.GameParticipant.lh == 1)
            .label("lh_1"),
            func.count()
            .filter(models.GameParticipant.info == "first_killed", models.GameParticipant.lh == 1.5)
            .label("lh_15"),
            func.avg(
                models.GameParticipant.points_win
                + models.GameParticipant.points_judge
                + _LH_RATING_SQL
                + func.coalesce(models.GameParticipant.ci, 0)
            ).label("avg_score"),
            func.avg(
                models.GameParticipant.points_judge
                + _LH_RATING_SQL
                + func.coalesce(models.GameParticipant.ci, 0)
            ).label("avg_bonus"),
        )
        .select_from(models.GameParticipant)
        .join(models.Game, models.Game.id == models.GameParticipant.game_id)
        .filter(models.GameParticipant.player_id == player_id, models.Game.status == "rated")
        .one()
    )

    stats = PlayerStats(
        **{k: (v or 0) for k, v in row._mapping.items() if k not in ("avg_score", "avg_bonus")}
    )
    stats.avg_score = float(row.avg_score) if row.avg_score is not None else None
    stats.avg_bonus = float(row.avg_bonus) if row.avg_bonus is not None else None

    rating = db.get(models.PlayerRating, player_id)
    if rating and rating.games_count > 0:
        stats.rating = float(rating.rating)
        stats.rating_games_count = rating.games_count
        stats.rank = (
            db.query(func.count())
            .select_from(models.PlayerRating)
            .join(models.Player, models.Player.id == models.PlayerRating.player_id)
            .filter(
                models.Player.is_active.is_(True),
                models.PlayerRating.games_count > 0,
                models.PlayerRating.rating > rating.rating,
            )
            .scalar()
            + 1
        )

    return stats
