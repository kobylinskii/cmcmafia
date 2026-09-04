from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.rate_limit import limiter
from app.schemas.game import GameListItem, GameListOut, GameOut, ParticipantOut
from app.schemas.player import PlayerListItem, PlayerPublic, PlayerStatsOut
from app.schemas.rating import RatingRowOut, RatingTableOut
from app.services import stats_service

router = APIRouter(prefix="/api", tags=["public"])

RATING_FORMULA_TEXT = """\
Рейтинг основан на системе Эло (как в шахматах), адаптированной под правила клуба.

Старт: у каждого игрока 1000 очков. За каждую сыгранную рейтинговую игру рейтинг
меняется по формуле:

    R' = R + K * (Sa - E * 7) / 7 - O

где Sa — баллы игрока за игру (за победу + от судей + ЛХ + Ci), E — ожидаемый
результат команды игрока против команды соперников (по среднему рейтингу команд,
в диапазоне 0.3..0.7), K — коэффициент (40 для игроков с числом игр меньше 30,
иначе 10 при рейтинге выше 2000, иначе 20), O — штраф за удаления/ППК.

Побеждать сильных соперников и набирать больше баллов за игру выгоднее для роста
рейтинга, чем побеждать более слабых.
"""


@router.get("/games", response_model=GameListOut)
@limiter.limit("60/minute")
def list_games(
    request: Request,
    limit: int = Query(default=10, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    date_from: date | None = None,
    date_to: date | None = None,
    game_type: str | None = None,
    result: str | None = None,
    player_slug: str | None = None,
    db: Session = Depends(get_db),
) -> GameListOut:
    rows, total = stats_service.list_rated_games(
        db,
        limit=limit,
        offset=offset,
        date_from=date_from,
        date_to=date_to,
        game_type=game_type,
        result=result,
        player_slug=player_slug,
    )
    return GameListOut(items=[GameListItem.model_validate(g) for g in rows], total=total)


@router.get("/games/{game_id}", response_model=GameOut)
@limiter.limit("60/minute")
def get_game(request: Request, game_id: int, db: Session = Depends(get_db)) -> GameOut:
    game = stats_service.get_rated_game(db, game_id)
    if game is None:
        raise HTTPException(404, "Игра не найдена")

    participants = sorted(game.participants, key=lambda p: p.seat_number)
    return GameOut(
        id=game.id,
        starts_at=game.starts_at,
        location=game.location,
        game_type=game.game_type,
        status=game.status,
        result=game.result,
        notes=game.notes,
        participants=[
            ParticipantOut(
                seat_number=p.seat_number,
                role=p.role,
                points_win=float(p.points_win),
                points_judge=float(p.points_judge),
                lh=float(p.lh) if p.lh is not None else None,
                ci=float(p.ci) if p.ci is not None else None,
                info=p.info,
                removals=p.removals,
                ppk=p.ppk,
                zk=float(p.zk) if p.zk is not None else None,
                sk=float(p.sk) if p.sk is not None else None,
                player_slug=p.player.slug,
                player_nickname=p.player.nickname,
            )
            for p in participants
        ],
    )


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


@router.get("/rating/formula")
@limiter.limit("60/minute")
def get_rating_formula(request: Request) -> dict:
    return {"text": RATING_FORMULA_TEXT}


@router.get("/players", response_model=list[PlayerListItem])
@limiter.limit("60/minute")
def list_players(request: Request, db: Session = Depends(get_db)) -> list[models.Player]:
    return (
        db.query(models.Player)
        .filter(models.Player.is_active.is_(True))
        .order_by(models.Player.nickname.asc())
        .all()
    )


@router.get("/players/{slug}")
@limiter.limit("60/minute")
def get_player(request: Request, slug: str, db: Session = Depends(get_db)) -> dict:
    player = (
        db.query(models.Player)
        .filter(models.Player.slug == slug, models.Player.is_active.is_(True))
        .one_or_none()
    )
    if player is None:
        raise HTTPException(404, "Игрок не найден")

    stats = stats_service.compute_player_stats(db, player.id)
    return {
        "player": PlayerPublic.model_validate(player),
        "stats": PlayerStatsOut(
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
            lh_distribution={"0": stats.lh_0, "0.5": stats.lh_05, "1": stats.lh_1, "1.5": stats.lh_15},
            rating=stats.rating,
            rating_games_count=stats.rating_games_count,
            rank=stats.rank,
            avg_score=stats.avg_score,
            avg_bonus=stats.avg_bonus,
        ),
    }
