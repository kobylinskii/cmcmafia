"""Номинации турнира: лучший мирный / чёрный / дон / шериф, MVP и топ-3 мест.

Считаются ТОЛЬКО по играм финального стола -- финального этапа, если у турнира
есть сетка, иначе по единственной таблице турнира (все игры без этапа, см.
stats_service.tournament_standings). Отборочные этапы в номинации не входят
вообще: составы там разные, а средний балл за игру сравнивал бы игроков,
сыгравших с разными соперниками.

В базе номинации не хранятся -- это чистая производная от оценённых игр, и
после правки оценки игры они обязаны пересчитаться сами. Хранится ровно две
вещи: ручная замена победителя (models.TournamentAward, строка появляется
только там, где админ не согласился с расчётом) и флаг публикации блока на
сайте (tournaments.awards_published).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app import models
from app.services import stats_service, tournament_service
from app.services.tournament_service import TournamentValidationError


@dataclass(frozen=True)
class Nomination:
    key: str
    title: str
    # Как считается -- показывается и в админке, и на публичной странице:
    # без формулы «лучший мирный» ни о чём не говорит.
    formula: str
    # Подпись к блоку статистики победителя («Статистика на мирном»).
    stats_label: str
    # Роль, по играм на которой считается номинация. None -- по всем играм
    # финального стола.
    role: str | None
    # Учитывать ли баллы за ЛХ. У чёрных ролей номинация -- только судейские
    # (ЛХ у мафии бывает, но в зачёт чёрных номинаций регламент её не берёт).
    with_lh: bool
    # Место в турнирной таблице, если номинация -- это место турнира, а не
    # средний балл на роли.
    place: int | None = None


NOMINATIONS: list[Nomination] = [
    Nomination(
        "best_citizen", "Лучший мирный",
        "(баллы от судей + ЛХ на мирном) ÷ игры на мирном",
        "Статистика на мирном", "citizen", True,
    ),
    Nomination(
        "best_mafia", "Лучший чёрный",
        "баллы от судей на мафии ÷ игры на мафии",
        "Статистика на мафии", "mafia", False,
    ),
    Nomination(
        "best_don", "Лучший дон",
        "баллы от судей на доне ÷ игры на доне",
        "Статистика на доне", "don", False,
    ),
    Nomination(
        "best_sheriff", "Лучший шериф",
        "(баллы от судей + ЛХ на шерифе) ÷ игры на шерифе",
        "Статистика на шерифе", "sheriff", True,
    ),
    Nomination(
        "mvp", "MVP турнира",
        "(баллы от судей + ЛХ на всех ролях) ÷ игры",
        "Статистика на финальном столе", None, True,
    ),
    Nomination(
        "first_place", "Победитель турнира",
        "1 место по сумме баллов финального стола",
        "Статистика на финальном столе", None, True, place=1,
    ),
    Nomination(
        "second_place", "Второе место",
        "2 место по сумме баллов финального стола",
        "Статистика на финальном столе", None, True, place=2,
    ),
    Nomination(
        "third_place", "Третье место",
        "3 место по сумме баллов финального стола",
        "Статистика на финальном столе", None, True, place=3,
    ),
]


@dataclass
class AwardCandidate:
    player: models.Player
    # Место в таблице финального стола -- он же тай-брейк номинации: при равном
    # среднем балле выше тот, кто выше в таблице (stats_service._standing_sort_key
    # разводит равные суммы по судейским, победам и активным ролям).
    rank: int
    games_count: int
    wins: int
    losses: int
    points_judge: float
    lh_points: float
    # Величина, по которой присуждается номинация: средний балл за игру у
    # ролевых номинаций и MVP, сумма баллов таблицы -- у мест турнира.
    score: float
    total_score: float


@dataclass
class Award:
    nomination: Nomination
    winner: AwardCandidate | None
    # Победитель выбран админом вручную, а не расчётом.
    manual: bool
    candidates: list[AwardCandidate]


@dataclass
class AwardsResult:
    # Название стола, по которому всё посчитано (None -- турнир без сеток).
    table_name: str | None
    # Почему считать не по чему -- показывается админу вместо номинаций.
    problem: str | None
    published: bool
    awards: list[Award]


def _round(value: float) -> float:
    return round(value, 2)


def _final_table(db: Session, tournament_id: int) -> tuple[int | None, str | None, str | None]:
    """(stage_id финального стола, его название, причина отказа).

    stage_id=None -- это «игры без этапа», что для турнира без сеток и есть
    все его игры (см. stats_service.tournament_standings).
    """
    stages = tournament_service.list_stages(db, tournament_id=tournament_id)
    if not stages:
        return None, None, None
    final = next((s for s in stages if s.is_final), None)
    if final is None:
        return None, None, (
            "У турнира есть этапы, но ни один не отмечен финальным — "
            "номинации считаются только по финальному столу."
        )
    return final.id, final.name, None


def _sorted_candidates(candidates: list[AwardCandidate]) -> list[AwardCandidate]:
    """По убыванию зачётной величины, при равенстве -- по месту в таблице."""
    return sorted(candidates, key=lambda c: (c.score, -c.rank), reverse=True)


def compute_awards(db: Session, *, tournament: models.Tournament) -> AwardsResult:
    stage_id, table_name, problem = _final_table(db, tournament.id)
    if problem:
        return AwardsResult(
            table_name=None, problem=problem, published=tournament.awards_published, awards=[]
        )

    standings = stats_service.tournament_standings(
        db, tournament_id=tournament.id, stage_id=stage_id
    )
    if not standings:
        return AwardsResult(
            table_name=table_name,
            problem="На финальном столе ещё нет оценённых игр.",
            published=tournament.awards_published,
            awards=[],
        )

    role_rows = stats_service.tournament_role_stats(
        db, tournament_id=tournament.id, stage_id=stage_id
    )
    by_player = {row.player.id: row for row in standings}
    overrides = {
        award.nomination: award.player_id
        for award in db.query(models.TournamentAward).filter(
            models.TournamentAward.tournament_id == tournament.id
        )
    }

    awards: list[Award] = []
    for nomination in NOMINATIONS:
        candidates = _candidates_for(nomination, standings, role_rows, by_player)
        winner, manual = _pick_winner(nomination, candidates, overrides.get(nomination.key))
        awards.append(
            Award(nomination=nomination, winner=winner, manual=manual, candidates=candidates)
        )
    return AwardsResult(
        table_name=table_name,
        problem=None,
        published=tournament.awards_published,
        awards=awards,
    )


def _candidates_for(
    nomination: Nomination,
    standings: list,
    role_rows: list,
    by_player: dict[int, object],
) -> list[AwardCandidate]:
    if nomination.role is not None:
        candidates = [
            AwardCandidate(
                player=by_player[r.player_id].player,
                rank=by_player[r.player_id].rank,
                games_count=r.games_count,
                wins=r.wins,
                losses=r.losses,
                points_judge=r.points_judge,
                lh_points=r.lh_points,
                score=_round(
                    (r.points_judge + (r.lh_points if nomination.with_lh else 0.0))
                    / r.games_count
                ),
                total_score=by_player[r.player_id].total_score,
            )
            for r in role_rows
            if r.role == nomination.role and r.games_count > 0 and r.player_id in by_player
        ]
        return _sorted_candidates(candidates)

    # MVP и места турнира -- по всей таблице финального стола. Разница только
    # в зачётной величине: средний балл за игру против суммы баллов.
    candidates = [
        AwardCandidate(
            player=row.player,
            rank=row.rank,
            games_count=row.games_count,
            wins=row.wins,
            losses=row.losses,
            points_judge=row.points_judge,
            lh_points=row.lh_points,
            score=(
                row.total_score
                if nomination.place is not None
                else _round((row.points_judge + row.lh_points) / row.games_count)
            ),
            total_score=row.total_score,
        )
        for row in standings
        if row.games_count > 0
    ]
    return _sorted_candidates(candidates)


def _pick_winner(
    nomination: Nomination, candidates: list[AwardCandidate], override_id: int | None
) -> tuple[AwardCandidate | None, bool]:
    if override_id is not None:
        manual = next((c for c in candidates if c.player.id == override_id), None)
        if manual is not None:
            return manual, True
        # Игрок мог выпасть из кандидатов после переоценки игры (например,
        # больше не играл эту роль на финале) -- тогда молча возвращаемся к
        # расчёту, а не показываем пустую номинацию.
    index = (nomination.place or 1) - 1
    return (candidates[index] if index < len(candidates) else None), False


def set_awards(
    db: Session,
    *,
    tournament: models.Tournament,
    published: bool | None = None,
    winners: dict[str, str | None] | None = None,
) -> None:
    """Правка блока номинаций: флаг публикации и/или ручные победители.

    winners -- ЧАСТИЧНОЕ обновление: приходят только те номинации, которые
    админ трогал: slug игрока либо None -- «вернуть расчёт», то есть удалить
    ручную правку.
    """
    if published is not None:
        tournament.awards_published = published
    if not winners:
        return

    computed = compute_awards(db, tournament=tournament)
    by_key = {award.nomination.key: award for award in computed.awards}
    for key, slug in winners.items():
        if key not in by_key:
            raise TournamentValidationError(f"Неизвестная номинация: {key}")
        existing = db.get(models.TournamentAward, (tournament.id, key))
        if slug is None:
            if existing is not None:
                db.delete(existing)
            continue
        # Победителя выбирают ИЗ кандидатов номинации: «лучшим доном» не может
        # стать тот, кто на финальном столе доном не играл.
        candidate = next((c for c in by_key[key].candidates if c.player.slug == slug), None)
        if candidate is None:
            raise TournamentValidationError(
                f"Игрок не входит в число кандидатов номинации «{by_key[key].nomination.title}»"
            )
        if existing is None:
            db.add(
                models.TournamentAward(
                    tournament_id=tournament.id, nomination=key, player_id=candidate.player.id
                )
            )
        else:
            existing.player_id = candidate.player.id
