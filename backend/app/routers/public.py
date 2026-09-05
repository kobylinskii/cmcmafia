from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.rate_limit import limiter
from app.schemas.game import GameListItem, GameListOut, GameOut
from app.schemas.player import PlayerDetailOut, PlayerListItem, PlayerPublic, PlayerStatsOut
from app.schemas.rating import RatingFormulaOut, RatingRowOut, RatingTableOut
from app.schemas.tournament import (
    TournamentDetailOut,
    TournamentListItem,
    TournamentPublic,
    TournamentRef,
    TournamentStageDetailOut,
    TournamentStagePublicGameOut,
    TournamentStandingOut,
)
from app import serializers
from app.services import rating_service, stats_service, tournament_service

router = APIRouter(prefix="/api", tags=["public"])


@router.get("/games", response_model=GameListOut)
@limiter.limit("60/minute")
def list_games(
    request: Request,
    limit: int = Query(default=10, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    date_from: date | None = None,
    date_to: date | None = None,
    game_type: Literal["tournament", "funky", "training"] | None = None,
    player_slug: str | None = None,
    tournament_slug: str | None = None,
    db: Session = Depends(get_db),
) -> GameListOut:
    rows, total = stats_service.list_rated_games(
        db,
        limit=limit,
        offset=offset,
        date_from=date_from,
        date_to=date_to,
        game_type=game_type,
        player_slug=player_slug,
        tournament_slug=tournament_slug,
    )
    return GameListOut(items=[GameListItem.model_validate(g) for g in rows], total=total)


@router.get("/games/{game_id}", response_model=GameOut)
@limiter.limit("60/minute")
def get_game(request: Request, game_id: int, db: Session = Depends(get_db)) -> GameOut:
    game = stats_service.get_rated_game(db, game_id)
    if game is None:
        raise HTTPException(404, "Игра не найдена")
    # roster не передаём: игра уже оценена, состав виден в participants.
    return serializers.game_to_out(game)


@router.get("/rating", response_model=RatingTableOut)
@limiter.limit("60/minute")
def get_rating(
    request: Request,
    q: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> RatingTableOut:
    rows, total = stats_service.rating_table(db, q=q, limit=limit, offset=offset)
    return RatingTableOut(
        items=[
            RatingRowOut(
                rank=r.rank,
                slug=r.player.slug,
                nickname=r.player.nickname,
                photo_url=r.player.photo_url,
                rating=r.rating,
                games_count=r.games_count,
                win_rate=r.win_rate,
                avg_bonus=r.avg_bonus,
            )
            for r in rows
        ],
        total=total,
    )


@router.get("/rating/formula", response_model=RatingFormulaOut)
@limiter.limit("60/minute")
def get_rating_formula(request: Request) -> RatingFormulaOut:
    return rating_service.describe_formula()


@router.get("/stats")
@limiter.limit("60/minute")
def get_site_stats(request: Request, db: Session = Depends(get_db)) -> dict:
    """Счётчики для главной. Отдельный эндпоинт появился потому, что главная
    раньше тянула весь список игроков целиком только чтобы взять len()."""
    return stats_service.site_counters(db)


@router.get("/tournaments", response_model=list[TournamentListItem])
@limiter.limit("60/minute")
def list_tournaments(request: Request, db: Session = Depends(get_db)) -> list[TournamentListItem]:
    counts = tournament_service.games_count_map(db)
    return [
        TournamentListItem(
            slug=t.slug, name=t.name, location=t.location, games_count=counts.get(t.id, 0)
        )
        for t in tournament_service.list_tournaments(db)
    ]


def _standing_rows_to_out(
    rows: list, advanced_ids: set[int] | None = None
) -> list[TournamentStandingOut]:
    advanced_ids = advanced_ids or set()
    return [
        TournamentStandingOut(
            rank=row.rank,
            slug=row.player.slug,
            nickname=row.player.nickname,
            photo_url=row.player.photo_url,
            games_count=row.games_count,
            points_win=row.points_win,
            points_judge=row.points_judge,
            lh_points=row.lh_points,
            ci=row.ci,
            removals=row.removals,
            ppk_count=row.ppk_count,
            zk=row.zk,
            sk=row.sk,
            total_score=row.total_score,
            advanced=row.player.id in advanced_ids,
        )
        for row in rows
    ]


@router.get("/tournaments/{slug}", response_model=TournamentDetailOut)
@limiter.limit("60/minute")
def get_tournament(request: Request, slug: str, db: Session = Depends(get_db)) -> TournamentDetailOut:
    tournament = tournament_service.get_by_slug(db, slug)
    if tournament is None:
        raise HTTPException(404, "Турнир не найден")

    # Четыре групповых запроса на весь турнир вместо четырёх на каждый этап:
    # раньше сводная таблица, список прошедших дальше и список игр брались
    # внутри цикла по этапам, и ручка стоила 36 запросов на восьми этапах.
    stages = tournament_service.list_stages(db, tournament_id=tournament.id)
    standings_by_stage = stats_service.tournament_standings_all(db, tournament_id=tournament.id)
    advances_by_stage = tournament_service.get_advances_map(db, tournament_id=tournament.id)
    games_by_stage = tournament_service.list_games_by_stage(db, tournament_id=tournament.id)

    # У турнира без сеток stage_id=None -- это ровно "все игры турнира", раз
    # game_service держит его так принудительно (см. tournament_standings).
    # У турнира С сетками это "игры, ещё не разнесённые по этапам" -- обычно
    # пусто, но не теряется, если такие всё же есть.
    unstaged = standings_by_stage.get(None, [])

    return TournamentDetailOut(
        tournament=TournamentPublic.model_validate(tournament),
        games_count=tournament_service.games_count_for(db, tournament_id=tournament.id),
        standings=_standing_rows_to_out(unstaged),
        stages=[
            TournamentStageDetailOut(
                id=stage.id,
                name=stage.name,
                order=stage.order,
                is_final=stage.is_final,
                standings=_standing_rows_to_out(
                    standings_by_stage.get(stage.id, []),
                    advances_by_stage.get(stage.id, set()),
                ),
                games=[
                    TournamentStagePublicGameOut(
                        number=i, id=g.id, starts_at=g.starts_at, status=g.status, result=g.result
                    )
                    for i, g in enumerate(games_by_stage.get(stage.id, []), start=1)
                ],
            )
            for stage in stages
        ],
    )


@router.get("/players", response_model=list[PlayerListItem])
@limiter.limit("60/minute")
def list_players(
    request: Request,
    limit: int = Query(default=500, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[models.Player]:
    """Ограничение сверху есть всегда: ручку читают и sitemap, и выпадающие
    списки, и без него список рос бы вместе с клубом на каждой такой странице.
    Дефолт держит обратную совместимость -- вызов без параметров работает
    по-старому, пока игроков меньше пятисот; sitemap.ts обходит страницами."""
    return (
        db.query(models.Player)
        .filter(models.Player.is_active.is_(True))
        .order_by(models.Player.nickname.asc(), models.Player.id.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )


@router.get("/players/{slug}", response_model=PlayerDetailOut)
@limiter.limit("60/minute")
def get_player(request: Request, slug: str, db: Session = Depends(get_db)) -> PlayerDetailOut:
    player = (
        db.query(models.Player)
        .filter(models.Player.slug == slug, models.Player.is_active.is_(True))
        .one_or_none()
    )
    if player is None:
        raise HTTPException(404, "Игрок не найден")

    stats = stats_service.compute_player_stats(db, player.id)
    return PlayerDetailOut(
        player=PlayerPublic.model_validate(player),
        stats=PlayerStatsOut(
            total_games=stats.total_games,
            wins=stats.wins,
            losses=stats.losses,
            draws=stats.draws,
            win_rate=stats.win_rate,
            black_card_games=stats.black_card_games,
            black_card_win_rate=stats.black_card_win_rate,
            red_card_games=stats.red_card_games,
            red_card_win_rate=stats.red_card_win_rate,
            don_games=stats.don_games,
            don_win_rate=stats.don_win_rate,
            sheriff_games=stats.sheriff_games,
            sheriff_win_rate=stats.sheriff_win_rate,
            first_kill_count=stats.first_kill_count,
            # Ключи -- попадания «сколько из трёх названных оказались чёрными».
            # Раньше здесь стояли 0/0.5/1/1.5 и подписывались как баллы, из-за
            # чего 0/3 и 1/3 выглядели одним и тем же случаем.
            lh_distribution={
                "0/3": stats.lh_hits_0,
                "1/3": stats.lh_hits_1,
                "2/3": stats.lh_hits_2,
                "3/3": stats.lh_hits_3,
            },
            rating=stats.rating,
            rating_games_count=stats.rating_games_count,
            rank=stats.rank,
            avg_score=stats.avg_score,
            avg_bonus=stats.avg_bonus,
        ),
    )
