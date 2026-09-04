"""Полный пересчёт рейтинга Эло по формуле «Мафия с Левшой».

R'a = Ra + K * (Sa - E * M) / M - O

Рейтинг накопительный и зависит от хронологического порядка игр, поэтому
пересчитывается полным реплеем всей истории (games.status == 'rated',
по возрастанию starts_at, id), а не инкрементально. См. ARCHITECTURE.md, раздел 5.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app import models

START_RATING = 1000.0
M = 7.0
E_MIN, E_MAX = 0.3, 0.7

BLACK_ROLES = {"mafia", "don"}
RED_ROLES = {"citizen", "sheriff"}

# Rating-only conversion of the judges' raw ЛХ mark (0 / 0.5 / 1 / 1.5, "x out
# of 3" in club shorthand) into the bonus actually used in Sa. The raw value
# stays exactly what's recorded on the game record and shown in the games
# table -- only its contribution to the rating changes here.
LH_RATING_VALUE: dict[float, float] = {0.0: 0.0, 0.5: 0.0, 1.0: 0.5, 1.5: 1.0}

# Игра меняет рейтинг с этим весом: фановая игра стоит меньше турнирной.
GAME_TYPE_WEIGHT: dict[str, float] = {"funky": 0.3, "tournament": 1.0, "training": 0.0}


def lh_rating_value(raw_lh: float | None) -> float:
    if raw_lh is None:
        return 0.0
    return LH_RATING_VALUE.get(float(raw_lh), 0.0)


def _k_coefficient(games_before: int, rating_before: float) -> int:
    if games_before < 30:
        return 40
    if rating_before > 2000:
        return 10
    return 20


def _penalty_rates(games_before: int, rating_before: float) -> tuple[float, float]:
    """Возвращает (штраф за одно удаление, штраф за ППК)."""
    if games_before < 30:
        return 8.0, 15.0
    if rating_before > 2000:
        return 3.0, 5.0
    return 5.0, 10.0


def _expected_score(own_avg: float, opp_avg: float) -> float:
    raw = 1.0 / (1.0 + 10 ** ((opp_avg - own_avg) / 400.0))
    return max(E_MIN, min(E_MAX, raw))


@dataclass
class _PlayerState:
    rating: float = START_RATING
    games_count: int = 0
    wins: int = 0
    losses: int = 0
    draws: int = 0


@dataclass
class RecomputeResult:
    games_processed: int = 0
    players_affected: int = 0
    history_rows: list[models.PlayerRatingHistory] = field(default_factory=list)


def recompute_all(db: Session) -> RecomputeResult:
    """Полностью пересчитывает рейтинг всех игроков. Вызывать внутри транзакции,
    вместе с create/update/delete рейтинговой игры, чтобы читатели никогда не
    видели промежуточное состояние."""

    games = (
        db.query(models.Game)
        .filter(models.Game.status == "rated")
        .order_by(models.Game.starts_at.asc(), models.Game.id.asc())
        .all()
    )

    state: dict[int, _PlayerState] = {}
    result = RecomputeResult()

    for game in games:
        participants = (
            db.query(models.GameParticipant)
            .filter(models.GameParticipant.game_id == game.id)
            .all()
        )
        if not participants:
            continue

        for p in participants:
            state.setdefault(p.player_id, _PlayerState())

        black = [p for p in participants if p.role in BLACK_ROLES]
        red = [p for p in participants if p.role in RED_ROLES]

        black_avg = sum(state[p.player_id].rating for p in black) / len(black) if black else START_RATING
        red_avg = sum(state[p.player_id].rating for p in red) / len(red) if red else START_RATING

        e_red = _expected_score(red_avg, black_avg)
        e_black = _expected_score(black_avg, red_avg)

        # Считаем все дельты по состоянию ДО этой игры, применяем атомарно после,
        # чтобы обновление одного участника не влияло на средний рейтинг команды
        # для остальных участников этой же игры.
        weight = GAME_TYPE_WEIGHT.get(game.game_type, 1.0)
        computed: list[tuple[models.GameParticipant, float, float, int, float, float, float]] = []
        for p in participants:
            st = state[p.player_id]
            ra = st.rating
            games_before = st.games_count
            k = _k_coefficient(games_before, ra)
            e = e_red if p.role in RED_ROLES else e_black
            sa = float(p.points_win) + float(p.points_judge) + lh_rating_value(p.lh) + float(p.ci or 0)
            removal_rate, ppk_rate = _penalty_rates(games_before, ra)
            penalty = (p.removals or 0) * removal_rate + (ppk_rate if p.ppk else 0.0)
            r_new = ra + weight * (k * (sa - e * M) / M - penalty)
            computed.append((p, ra, r_new, k, e, sa, penalty))

        won_black = game.result == "mafia_win"
        won_red = game.result == "city_win"
        is_draw = game.result == "draw"

        for p, ra, r_new, k, e, sa, penalty in computed:
            st = state[p.player_id]
            st.rating = r_new
            st.games_count += 1
            if is_draw:
                st.draws += 1
            elif (p.role in BLACK_ROLES and won_black) or (p.role in RED_ROLES and won_red):
                st.wins += 1
            else:
                st.losses += 1

            result.history_rows.append(
                models.PlayerRatingHistory(
                    player_id=p.player_id,
                    game_id=game.id,
                    rating_before=round(ra, 2),
                    rating_after=round(r_new, 2),
                    delta=round(r_new - ra, 2),
                    k_coefficient=k,
                    expected_score=round(e, 4),
                    sa=round(sa, 2),
                    penalty=round(penalty, 2),
                )
            )

        result.games_processed += 1

    db.execute(delete(models.PlayerRatingHistory))
    db.execute(delete(models.PlayerRating))
    db.flush()

    for player_id, st in state.items():
        db.add(
            models.PlayerRating(
                player_id=player_id,
                rating=round(st.rating, 2),
                games_count=st.games_count,
                wins=st.wins,
                losses=st.losses,
                draws=st.draws,
            )
        )
    db.add_all(result.history_rows)

    result.players_affected = len(state)
    return result
