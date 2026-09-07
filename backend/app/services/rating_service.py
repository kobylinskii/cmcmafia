"""Полный пересчёт рейтинга Эло по формуле «Мафия с Левшой».

R'a = Ra + K * (Sa - E * M) / M - O

Рейтинг накопительный и зависит от хронологического порядка игр, поэтому
пересчитывается полным реплеем всей истории (games.status == 'rated',
по возрастанию starts_at, id), а не инкрементально. См. ARCHITECTURE.md, раздел 5.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import models

START_RATING = 1000.0
M = 7.0
E_MIN, E_MAX = 0.3, 0.7

BLACK_ROLES = {"mafia", "don"}
RED_ROLES = {"citizen", "sheriff"}

# game_participants.lh хранит ПОПАДАНИЯ ЛХ, а не баллы: в клубной записи
# 0 / 0.5 / 1 / 1.5 означают 0/3, 1/3, 2/3, 3/3 названных чёрных. Баллы из них
# выводятся так: 0/3 и 1/3 не дают ничего, 2/3 -> 0.5, 3/3 -> 1. Именно баллы
# идут и в Sa, и в среднюю статистику (stats_service._LH_POINTS_SQL -- зеркало
# этой таблицы на SQL, держать в синхроне).
LH_POINTS: dict[float, float] = {0.0: 0.0, 0.5: 0.0, 1.0: 0.5, 1.5: 1.0}

# Вес игры в рейтинге: фановая стоит меньше турнирной.
GAME_TYPE_WEIGHT: dict[str, float] = {"funky": 0.3, "tournament": 1.0, "training": 0.0}

# Обучающие игры не участвуют в реплее вообще. Нулевого веса для этого мало:
# при нём дельта рейтинга равна нулю, но games_count всё равно растёт, а он
# определяет коэффициент K (до 30 игр K=40, дальше 20). То есть обучающие игры
# незаметно «взрослили» игрока и через это меняли его рейтинг в последующих
# турнирных играх, а заодно попадали в счётчик игр и winrate рейтинговой таблицы.
UNRATED_GAME_TYPES = frozenset({"training"})


def lh_points(raw_lh_hits: float | None) -> float:
    """Попадания ЛХ -> баллы за ЛХ."""
    if raw_lh_hits is None:
        return 0.0
    return LH_POINTS.get(float(raw_lh_hits), 0.0)


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


GAME_TYPE_LABELS: dict[str, str] = {"tournament": "Турнирная", "funky": "Фанки", "training": "Обучающая"}


def describe_formula():
    """Собирает публичное описание формулы (см. app/schemas/rating.RatingFormulaOut).

    Числа в k_tiers/game_type_weights получены ВЫЗОВОМ настоящих
    _k_coefficient/_penalty_rates/GAME_TYPE_WEIGHT, а не переписаны сюда
    руками -- если пороги (30 игр, рейтинг 2000) или ставки штрафов когда-нибудь
    поменяются в одном месте выше, текст на сайте не разойдётся с тем, что
    реально считает recompute_all.
    """
    from app.schemas.rating import GameTypeWeight, RatingFormulaOut, RatingKTier, RatingLegendItem

    tiers = [
        ("до 30 игр", 0, 0.0),
        ("от 30 игр, рейтинг ≤ 2000", 30, 0.0),
        ("от 30 игр, рейтинг выше 2000", 30, 2001.0),
    ]
    k_tiers = [
        RatingKTier(
            condition=label,
            k=_k_coefficient(games_before, rating_before),
            removal_penalty=_penalty_rates(games_before, rating_before)[0],
            ppk_penalty=_penalty_rates(games_before, rating_before)[1],
        )
        for label, games_before, rating_before in tiers
    ]

    game_type_weights = [
        GameTypeWeight(
            game_type=game_type,
            label=GAME_TYPE_LABELS.get(game_type, game_type),
            weight=weight,
            rated=game_type not in UNRATED_GAME_TYPES,
        )
        # Порядок явный (не .items()), чтобы турнирная всегда шла первой --
        # это основной формат клуба, ей и открывать список.
        for game_type in ("tournament", "funky", "training")
        for weight in [GAME_TYPE_WEIGHT[game_type]]
    ]

    return RatingFormulaOut(
        intro="Рейтинг основан на системе Эло (как в шахматах), адаптированной под правила клуба.",
        start_rating=START_RATING,
        formula="R' = R + K · (Sa − E · M) / M − O",
        legend=[
            RatingLegendItem(
                symbol="Sa",
                text="баллы игрока за игру: за победу + от судей + ЛХ + Ci, минус карточки (ЖК, СК)",
            ),
            RatingLegendItem(
                symbol="E",
                text=f"ожидаемый результат команды игрока против команды соперников (по среднему "
                f"рейтингу команд, в диапазоне {E_MIN:.1f}–{E_MAX:.1f})",
            ),
            RatingLegendItem(symbol="M", text=f"число игроков в команде ({int(M)})"),
            RatingLegendItem(symbol="K", text="коэффициент, зависит от опыта игрока — см. таблицу ниже"),
            RatingLegendItem(symbol="O", text="штраф за удаления и ППК — см. таблицу ниже"),
        ],
        expected_score_min=E_MIN,
        expected_score_max=E_MAX,
        k_tiers=k_tiers,
        note="Побеждать сильных соперников и набирать больше баллов за игру выгоднее для роста "
        "рейтинга, чем побеждать более слабых.",
        game_type_weights=game_type_weights,
        training_note="Обучающие игры не только не двигают рейтинг: они не попадают и в счётчик "
        "сыгранных рейтинговых игр, от которого зависит коэффициент K. То есть на рейтинг они не "
        "влияют никак — ни напрямую, ни через число игр. В личной статистике игрока они при этом "
        "учитываются.",
    )


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

    # Два запроса на весь реплей, а не два на каждую игру. Раньше состав
    # запрашивался внутри цикла, и пересчёт после правки одной игры стоил
    # O(число рейтинговых игр) round-trip'ов к БД -- а он запускается при
    # каждом create/update/delete рейтинговой игры.
    games = db.execute(
        select(
            models.Game.id,
            models.Game.game_type,
            models.Game.result,
        )
        .where(models.Game.status == "rated")
        .order_by(models.Game.starts_at.asc(), models.Game.id.asc())
    ).all()

    participants_by_game: dict[int, list[models.GameParticipant]] = defaultdict(list)
    for participant in (
        db.query(models.GameParticipant)
        .join(models.Game, models.Game.id == models.GameParticipant.game_id)
        .filter(models.Game.status == "rated")
        .all()
    ):
        participants_by_game[participant.game_id].append(participant)

    state: dict[int, _PlayerState] = {}
    result = RecomputeResult()

    for game in games:
        if game.game_type in UNRATED_GAME_TYPES:
            continue

        participants = participants_by_game.get(game.id)
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
            # Sa -- «итого очков за игру» из клубной таблицы, то есть баллы
            # МИНУС карточные штрафы. ЖК и СК уже хранятся в игровых баллах,
            # поэтому вычитаются прямо здесь, а не через O: сверка с реальной
            # клубной таблицей (7 игр, 70 строк) показала, что без этого
            # вычета каждая карточка стоила игроку 0 очков рейтинга вместо
            # K*ЖК/M -- при K=40 это 2.86 очка, и ошибка расползалась дальше
            # по всем играм через средние рейтинги команд. Удаления и ППК
            # сюда НЕ входят: они считаются отдельным штрафом O сразу в очках
            # рейтинга (_penalty_rates), а не в игровых баллах.
            sa = (
                float(p.points_win)
                + float(p.points_judge)
                + lh_points(p.lh)
                + float(p.ci or 0)
                - float(p.zk or 0)
                - float(p.sk or 0)
            )
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
