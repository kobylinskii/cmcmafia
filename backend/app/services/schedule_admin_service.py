"""Планировщик игр: пачка слотов на день, поиск конфликтов, обзор по дням.

Раньше этим управляли из бота (`/api/bot/admin/sessions/*`), теперь -- из
вкладки «Игры → Расписание» в админке сайта; сервис от перевозки не изменился,
кроме одного: у слота появился флаг `needs_rating`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

from app import models
from app.services.game_service import UNCONFIRMED_STATUSES
from app.timeutil import CLUB_TZ

# Сколько слотов максимум создаётся одним нажатием. Ограничение то же, что
# было в схеме бота: день длиннее двух суток по часу -- это опечатка в поле
# «сколько игр», а не игровой марафон.
MAX_BULK_SESSIONS = 48


def planned_starts(*, first: datetime, count: int, step_minutes: int) -> list[datetime]:
    """Времена начала слотов: первый в `first`, дальше через `step_minutes`.

    Бот умел только «по игре на каждый целый час внутри диапазона»; шаг и
    количество заданы явно, потому что вечер из трёх игр по 75 минут в эту
    сетку не ложился вообще.
    """
    return [first + timedelta(minutes=step_minutes * i) for i in range(count)]


def bulk_create_sessions(
    db: Session,
    *,
    starts_at_list: list[datetime],
    location: str,
    game_type: str,
    created_by: int,
    needs_rating: bool = True,
) -> list[int]:
    created: list[models.Game] = []
    for starts_at in starts_at_list:
        game = models.Game(
            starts_at=starts_at,
            location=location,
            game_type=game_type,
            registration_until=starts_at,
            status="scheduled",
            needs_rating=needs_rating,
            created_by=created_by,
        )
        db.add(game)
        created.append(game)
    db.flush()
    return [g.id for g in created]


def check_conflicts(
    db: Session, *, starts_at_list: list[datetime], exclude_session_ids: set[int] | None = None
) -> list[datetime]:
    if not starts_at_list:
        return []
    excluded = exclude_session_ids or set()
    rows = (
        db.query(models.Game.starts_at)
        .filter(models.Game.starts_at.in_(starts_at_list))
        .filter(models.Game.id.notin_(excluded) if excluded else True)
        .order_by(models.Game.starts_at.asc())
        .all()
    )
    return [r[0] for r in rows]


def _club_day_bounds(day: str) -> tuple[datetime, datetime]:
    """'ДД.ММ.ГГГГ' -> границы этих суток [начало, конец) в московском времени.

    Именно в московском: игра в 00:30 МСК приходится на 21:30 UTC предыдущих
    суток, и наивное сравнение по UTC отправило бы её в соседний день
    (см. app/timeutil.py).
    """
    start = datetime.strptime(day, "%d.%m.%Y").replace(tzinfo=CLUB_TZ)
    return start, start + timedelta(days=1)


# Календарный день игры по московскому времени, посчитанный на стороне СУБД.
_CLUB_DAY_SQL = func.date(func.timezone(str(CLUB_TZ), models.Game.starts_at))

# Что планировщик вообще показывает: только не-турнирные игры, и только пока с
# ними есть что делать. Оценённая игра из расписания уходит -- состав, баллы и
# исход правятся во вкладке «Оценённые», а список дней иначе рос бы на каждый
# отыгранный день и никогда не сокращался.
_MANAGED_GAMES = (
    models.Game.game_type != "tournament",
    models.Game.status != "rated",
)


def _active_schedule_filters(now: datetime | None = None) -> tuple:
    """К _MANAGED_GAMES добавляет отсев прошедших неоцениваемых игр.

    Игра без оценки ничего от админа не ждёт: подтверждать её проведение
    незачем, в «Ждут оценки» она не пойдёт. Оставлять её в расписании после
    начала значило бы копить строки, по которым нечего нажать. Сама запись и
    её состав остаются в базе -- пропала только из планировщика.
    """
    moment = now or datetime.now(timezone.utc)
    return _MANAGED_GAMES + (
        or_(models.Game.needs_rating.is_(True), models.Game.starts_at >= moment),
    )


def day_cards(db: Session, *, game_type: str | None = None) -> list[dict]:
    """Группировка делается в SQL: раньше в память выгружались строки по каждой
    игре клуба за всю историю, и список дней стоил O(всех игр)."""
    now = datetime.now(timezone.utc)
    # «Ждёт ответа: состоялась или нет» -- ровно условие
    # game_service.sessions_awaiting_confirmation, только посчитанное на день.
    awaiting_sql = case(
        (
            (models.Game.status.in_(UNCONFIRMED_STATUSES))
            & (models.Game.needs_rating.is_(True))
            & (models.Game.starts_at < now),
            1,
        ),
        else_=0,
    )
    query = (
        db.query(
            _CLUB_DAY_SQL.label("day"),
            models.Game.game_type,
            func.min(models.Game.starts_at).label("min_start"),
            func.count(models.Game.id).label("games"),
            func.sum(awaiting_sql).label("awaiting"),
        )
        # Турнирные слоты этапа сюда не попадают: у планировщика для них нет ни
        # одного осмысленного действия (нет регистрации, нет ростера) -- только
        # фанки/обучающие, которыми он реально управляет.
        .filter(*_active_schedule_filters(now))
        .group_by(_CLUB_DAY_SQL, models.Game.game_type)
    )
    if game_type and game_type != "all":
        query = query.filter(models.Game.game_type == game_type)

    grouped: dict[str, dict] = {}
    for day, gtype, min_start, games, awaiting in query.all():
        key = day.strftime("%d.%m.%Y")
        entry = grouped.setdefault(
            key, {"types": set(), "min_start": min_start, "games": 0, "awaiting": 0}
        )
        entry["types"].add(gtype)
        entry["games"] += int(games or 0)
        entry["awaiting"] += int(awaiting or 0)
        if min_start < entry["min_start"]:
            entry["min_start"] = min_start

    ordered = sorted(grouped.items(), key=lambda kv: kv[1]["min_start"])
    return [
        {
            "day": day,
            "types": sorted(v["types"]),
            "games_count": v["games"],
            "awaiting_count": v["awaiting"],
            "first_starts_at": v["min_start"],
        }
        for day, v in ordered
    ]


def games_by_day(db: Session, *, day: str) -> list[models.Game]:
    """Отбор по диапазону в SQL, а не выгрузка всей таблицы с фильтрацией
    на Python. Набор игр тот же, что и в day_cards: день, целиком состоящий из
    оценённых игр, из расписания исчезает вместе с ними."""
    start, end = _club_day_bounds(day)
    return (
        db.query(models.Game)
        .filter(
            models.Game.starts_at >= start,
            models.Game.starts_at < end,
            *_active_schedule_filters(),
        )
        .order_by(models.Game.starts_at.asc())
        .all()
    )


def recent_locations(db: Session, *, limit: int = 8) -> list[str]:
    """Места последних игр -- чтобы админ выбирал их из списка, а не набирал
    «ВМК МГУ, ауд. 685» руками каждый игровой день."""
    rows = (
        db.query(models.Game.location, func.max(models.Game.starts_at).label("last_used"))
        .filter(models.Game.location.isnot(None), models.Game.location != "")
        .group_by(models.Game.location)
        .order_by(func.max(models.Game.starts_at).desc())
        .limit(limit)
        .all()
    )
    return [row[0] for row in rows]


def find_player_by_username(db: Session, username: str) -> models.Player | None:
    clean = username.strip().lstrip("@")
    if not clean:
        return None
    return db.query(models.Player).filter(models.Player.telegram_username.ilike(clean)).one_or_none()


def find_player_by_phone(db: Session, phone: str) -> models.Player | None:
    digits = "".join(ch for ch in phone if ch.isdigit())
    if len(digits) < 10:
        return None
    return db.query(models.Player).filter(models.Player.phone == digits).one_or_none()
