from __future__ import annotations

from datetime import datetime, timezone

from app import models
from app.schemas.bot import RosterMemberOut, RosterOut, ReserveMemberOut, SessionOut
from app.schemas.game import GameOut, GameRosterEntry, ParticipantOut
from app.schemas.tournament import TournamentRef, TournamentStageRef


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


def session_to_out(game: models.Game) -> SessionOut:
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
        registration_until=game.registration_until,
        is_open=is_open,
        hosts=hosts,
        judges=judges,
        players=players,
        max_players=game.max_players,
        reserves=len(game.reserves),
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
