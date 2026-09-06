"""Список ФИО на пропуск: кому из записавшихся на игры недели нужен проход.

Клуб играет на ВМК, и людям не из МГУ пропуск заказывают заранее списком.
Список закрывается не календарной неделей, а клубным рубежом (по умолчанию
воскресенье 18:00 МСК, настраивается на вкладке «Обзор»): в момент рубежа
показ переключается на наступающую неделю, чтобы заявку успели подать.

Окно -- полуинтервал [последний прошедший рубеж; следующий рубеж), то есть
ровно семь суток. Игра, начинающаяся ровно в момент рубежа, попадает в новую
неделю, а не в закрывшуюся.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app import models
from app.services import settings_service
from app.timeutil import CLUB_TZ

# Пропуск нужен только тем, кто сам указал этот статус при регистрации в боте.
PASS_AFFILIATION = "outside_need_pass"
# Турнирные игры сюда не попадают: их состав ведётся на сайте вручную, а не
# записью через бота (см. ARCHITECTURE.md, раздел 7.7).
PASS_GAME_TYPES = ("funky", "training")

WEEKDAY_LABELS = (
    "понедельник",
    "вторник",
    "среда",
    "четверг",
    "пятница",
    "суббота",
    "воскресенье",
)


@dataclass
class PassListGame:
    game_id: int
    starts_at: datetime
    game_type: str
    location: str | None
    role: str  # player | host | judge | reserve


@dataclass
class PassListEntry:
    player_id: int
    nickname: str
    full_name: str | None
    phone: str | None
    confirmation_status: str
    games: list[PassListGame]


@dataclass
class PassListResult:
    week_start: datetime
    week_end: datetime
    rollover_weekday: int
    rollover_time: str
    entries: list[PassListEntry]


def current_week_window(db: Session) -> tuple[datetime, datetime]:
    settings = settings_service.get_settings(db)
    return week_window(
        weekday=settings.pass_week_rollover_weekday,
        time_hhmm=settings.pass_week_rollover_time,
    )


def week_window(*, weekday: int, time_hhmm: str, now: datetime | None = None) -> tuple[datetime, datetime]:
    """Полуинтервал текущей пропускной недели в московском времени."""
    moment = (now or datetime.now(CLUB_TZ)).astimezone(CLUB_TZ)
    hour, minute = (int(part) for part in time_hhmm.split(":"))
    # Отматываем назад к ближайшему дню нужной недели, затем ставим время
    # рубежа. Если получившийся рубеж ещё впереди (сегодня нужный день, но
    # время не наступило) -- берём прошлую неделю.
    days_back = (moment.weekday() - weekday) % 7
    start = (moment - timedelta(days=days_back)).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )
    if start > moment:
        start -= timedelta(days=7)
    return start, start + timedelta(days=7)


def build_pass_list(db: Session) -> PassListResult:
    settings = settings_service.get_settings(db)
    start, end = current_week_window(db)

    entries: dict[int, PassListEntry] = {}

    def _entry(player: models.Player) -> PassListEntry:
        existing = entries.get(player.id)
        if existing is None:
            existing = PassListEntry(
                player_id=player.id,
                nickname=player.nickname,
                full_name=player.full_name,
                phone=player.phone,
                confirmation_status=player.confirmation_status,
                games=[],
            )
            entries[player.id] = existing
        return existing

    def _game_filters(query):
        return query.filter(
            models.Player.affiliation == PASS_AFFILIATION,
            models.Player.is_active.is_(True),
            models.Game.game_type.in_(PASS_GAME_TYPES),
            models.Game.starts_at >= start,
            models.Game.starts_at < end,
        )

    registrations = _game_filters(
        db.query(models.Registration, models.Game, models.Player)
        .join(models.Game, models.Game.id == models.Registration.game_id)
        .join(models.Player, models.Player.id == models.Registration.player_id)
    ).all()
    for registration, game, player in registrations:
        _entry(player).games.append(
            PassListGame(
                game_id=game.id,
                starts_at=game.starts_at,
                game_type=game.game_type,
                location=game.location,
                role=registration.role,
            )
        )

    # Резерв тоже в списке: человек попадает в состав в последний момент, когда
    # заказать пропуск уже поздно.
    reserves = _game_filters(
        db.query(models.Reserve, models.Game, models.Player)
        .join(models.Game, models.Game.id == models.Reserve.game_id)
        .join(models.Player, models.Player.id == models.Reserve.player_id)
    ).all()
    for _, game, player in reserves:
        _entry(player).games.append(
            PassListGame(
                game_id=game.id,
                starts_at=game.starts_at,
                game_type=game.game_type,
                location=game.location,
                role="reserve",
            )
        )

    ordered = sorted(entries.values(), key=lambda e: ((e.full_name or e.nickname).lower(), e.player_id))
    for entry in ordered:
        entry.games.sort(key=lambda g: (g.starts_at, g.game_id))

    return PassListResult(
        week_start=start,
        week_end=end,
        rollover_weekday=settings.pass_week_rollover_weekday,
        rollover_time=settings.pass_week_rollover_time,
        entries=ordered,
    )
