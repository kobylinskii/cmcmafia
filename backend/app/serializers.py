from __future__ import annotations

from datetime import datetime, timezone

from app import models
from app.schemas.bot import RosterMemberOut, RosterOut, ReserveMemberOut, SessionOut


def is_session_open(game: models.Game) -> bool:
    return game.status == "scheduled" and game.starts_at >= datetime.now(timezone.utc)


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
