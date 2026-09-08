from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import selectinload

from app import models
from app.schemas.bot import RosterMemberOut, RosterOut, ReserveMemberOut, SessionOut
from app.schemas.game import GameOut, GameRosterEntry, ParticipantOut
from app.schemas.tournament import (
    AwardCandidateOut,
    TournamentAwardOut,
    TournamentRef,
    TournamentStageRef,
    TournamentStandingOut,
)


def is_session_open(game: models.Game) -> bool:
    """Запись открыта, пока игра запланирована и не наступил дедлайн записи.

    registration_until -- отдельный от starts_at дедлайн: админ может закрыть
    запись заранее. Если он не задан (исторические игры), запись идёт до самого
    начала игры. Проверяются оба срока: игру, которая уже началась, нельзя
    считать открытой даже при кривом registration_until в будущем."""
    if game.status != "scheduled":
        return False
    now = datetime.now(timezone.utc)
    deadline = game.registration_until or game.starts_at
    return deadline >= now and game.starts_at >= now


def session_load_options():
    """Что догрузить к играм, чтобы session_to_out/roster_to_out не ходили в БД.

    session_to_out считает роли по game.registrations и длину game.reserves,
    roster_to_out раскрывает ещё и самих игроков. На ленивых связях список из
    восьми слотов стоил 1 запрос за играми плюс 16 догрузок, и так на каждом
    открытии дня в расписании, экрана записи в боте и очереди подтверждений.
    Разворачивать эти списки надо ровно везде, где сериализуется НЕ одна игра.
    """
    return (
        selectinload(models.Game.registrations).selectinload(models.Registration.player),
        selectinload(models.Game.reserves).selectinload(models.Reserve.player),
    )


def session_to_out(game: models.Game, *, my_role: str | None = None) -> SessionOut:
    hosts = sum(1 for r in game.registrations if r.role == "host")
    judges = sum(1 for r in game.registrations if r.role == "judge")
    players = sum(1 for r in game.registrations if r.role == "player")
    is_open = is_session_open(game)
    return SessionOut(
        id=game.id,
        starts_at=game.starts_at,
        location=game.location,
        game_type=game.game_type,
        status=game.status,
        needs_rating=game.needs_rating,
        registration_until=game.registration_until,
        is_open=is_open,
        hosts=hosts,
        judges=judges,
        players=players,
        max_players=game.max_players,
        reserves=len(game.reserves),
        my_role=my_role,
    )


def roster_to_out(game: models.Game) -> RosterOut:
    return RosterOut(
        registrations=[
            RosterMemberOut(
                nickname=r.player.nickname,
                telegram_id=r.player.telegram_id,
                telegram_username=r.player.telegram_username,
                role=r.role,
            )
            for r in game.registrations
        ],
        reserves=[
            ReserveMemberOut(nickname=r.player.nickname, telegram_id=r.player.telegram_id)
            for r in game.reserves
        ],
    )


def participant_to_out(p: models.GameParticipant) -> ParticipantOut:
    """Единственное место, где GameParticipant превращается в ParticipantOut.

    Публичная и админская ручки игры собирали этот объект каждая своим блоком
    на пятнадцать строк -- и уже разошлись: админская отдавала stage, публичная
    нет, из-за чего этап турнира на странице игры не показывался никогда.
    """
    return ParticipantOut(
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


def game_to_out(game: models.Game, *, roster: list[GameRosterEntry] | None = None) -> GameOut:
    """Игра в публичном виде. roster заполняется только админской ручкой: на
    публичной странице игра уже оценена, и состав виден в participants."""
    return GameOut(
        id=game.id,
        starts_at=game.starts_at,
        location=game.location,
        game_type=game.game_type,
        status=game.status,
        result=game.result,
        notes=game.notes,
        tournament=TournamentRef.model_validate(game.tournament) if game.tournament else None,
        stage=TournamentStageRef.model_validate(game.stage) if game.stage else None,
        participants=[
            participant_to_out(p) for p in sorted(game.participants, key=lambda x: x.seat_number)
        ],
        roster=roster or [],
    )


def standing_rows_to_out(
    rows: list, advanced_ids: set[int] | None = None
) -> list[TournamentStandingOut]:
    """Строки турнирной таблицы -> ответ API.

    Одна функция на обе стороны: публичная страница турнира и панель админки
    показывают ОДНУ И ТУ ЖЕ таблицу, разница только в том, что админке нужны
    ещё отметки прохода. Раньше это были две одинаковые функции в
    routers/public.py и routers/admin.py -- ровно та конструкция, на которой
    уже разъехался participant_to_out (см. комментарий к нему выше).
    """
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


def award_candidate_to_out(candidate) -> AwardCandidateOut:
    """Кандидат номинации (awards_service.AwardCandidate) -> ответ API."""
    return AwardCandidateOut(
        slug=candidate.player.slug,
        nickname=candidate.player.nickname,
        photo_url=candidate.player.photo_url,
        rank=candidate.rank,
        games_count=candidate.games_count,
        wins=candidate.wins,
        losses=candidate.losses,
        # Доля, а не проценты -- как и везде в API (см. PlayerStatsOut.win_rate),
        # форматирует её фронт.
        win_rate=(candidate.wins / candidate.games_count) if candidate.games_count else None,
        points_judge=candidate.points_judge,
        lh_points=candidate.lh_points,
        score=candidate.score,
        total_score=candidate.total_score,
    )


def awards_to_out(awards: list, *, with_candidates: bool = False) -> list[TournamentAwardOut]:
    """Номинации -> ответ API. Список кандидатов нужен только админке (там из
    него выбирают победителя вручную); публичной странице -- один победитель."""
    return [
        TournamentAwardOut(
            nomination=award.nomination.key,
            title=award.nomination.title,
            formula=award.nomination.formula,
            winner=award_candidate_to_out(award.winner) if award.winner else None,
            manual=award.manual,
            candidates=(
                [award_candidate_to_out(c) for c in award.candidates] if with_candidates else []
            ),
        )
        for award in awards
    ]
