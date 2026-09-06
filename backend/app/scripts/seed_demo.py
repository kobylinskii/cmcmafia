"""Наполнение стенда демо-данными.

Отдельный от `create_admin` скрипт и намеренно не эндпоинт: он пишет в базу
десятки строк напрямую и на бою не нужен вообще. Данные подобраны так, чтобы
на пустом стенде было видно КАЖДУЮ часть системы, а не только список игроков:

* рейтинг и статистика — турнир с двумя этапами и оценённые фанки;
* «Ждут оценки» в обзоре — сыгранная, но не оценённая игра;
* «Ожидают подтверждения» — заявки из бота в трёх статусах модерации;
* «Нужен пропуск» — записи иногородних на игры ТЕКУЩЕЙ пропускной недели,
  посчитанной тем же кодом, что и сама вкладка (pass_list_service), плюс
  игры за её границей — чтобы было видно, что окно действительно режет.

Usage (внутри контейнера api):
    docker compose exec api python -m app.scripts.seed_demo --reset
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app import models, security
from app.database import SessionLocal
from app.services import game_service, player_service, pass_list_service, tournament_service
from app.services.game_service import ParticipantInput
from app.timeutil import CLUB_TZ

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "mafia-demo-2026"

# Порядок важен: таблицы чистятся одним TRUNCATE ... CASCADE, но перечислить
# их всё равно нужно явно -- alembic_version в список не входит, иначе
# следующий запуск контейнера попытался бы прогнать миграции заново.
_ALL_TABLES = (
    "audit_log, player_rating_history, player_rating, game_participants, "
    "reserves, registrations, games, tournament_stage_advances, tournament_stages, "
    "tournaments, pending_bot_admins, club_settings, players"
)

# Классическая раздача на десять человек (game_service.EXPECTED_ROLES).
SEATING = ["don", "mafia", "mafia", "sheriff"] + ["citizen"] * 6

PLAYER_NAMES = [
    ("Барон", "Астахов Артём Игоревич"),
    ("Виконт", "Белов Борис Сергеевич"),
    ("Гроза", "Волков Вадим Петрович"),
    ("Дельта", "Гусев Глеб Андреевич"),
    ("Ёрш", "Дроздов Денис Олегович"),
    ("Жетон", "Ершов Егор Максимович"),
    ("Зодиак", "Жуков Жан Романович"),
    ("Индиго", "Зайцев Захар Ильич"),
    ("Кобра", "Ильин Игорь Никитич"),
    ("Люмен", "Карпов Кирилл Львович"),
    ("Мираж", "Лебедев Лев Юрьевич"),
    ("Норд", "Морозов Марк Данилович"),
    ("Оникс", "Носов Никита Тимурович"),
    ("Пилот", "Орлов Олег Витальевич"),
    ("Ратник", "Павлов Пётр Русланович"),
    ("Сокол", "Рыбин Роман Семёнович"),
]

# Игроки, «пришедшие из бота»: у них есть telegram_id, телефон и статус
# модерации. Иногородние среди них -- материал для списка на пропуск.
BOT_PLAYERS = [
    # (ник, ФИО, affiliation, confirmation_status, обращение)
    ("Тень", "Соколов Семён Артёмович", "outside_need_pass", "confirmed", "господин"),
    ("Вьюга", "Тимофеева Тамара Львовна", "outside_need_pass", "confirmed", "госпожа"),
    ("Штиль", "Ульянов Ульян Петрович", "outside_need_pass", "pending", "господин"),
    ("Юнга", "Фомин Фёдор Игоревич", "mgu_no_pass", "pending", "господин"),
    ("Ясень", "Хромов Харитон Данилович", "outside_need_pass", "rejected", "господин"),
    ("Аврора", "Царёва Циана Олеговна", "vmk", "confirmed", "госпожа"),
]


def reset(db: Session) -> None:
    db.execute(text(f"TRUNCATE {_ALL_TABLES} RESTART IDENTITY CASCADE"))
    db.commit()


def is_empty(db: Session) -> bool:
    return db.query(models.Player).count() == 0


def make_admin(db: Session) -> models.Player:
    admin = player_service.create_player(db, nickname="Организатор", slug="organizer")
    admin.site_username = ADMIN_USERNAME
    admin.site_password_hash = security.hash_password(ADMIN_PASSWORD)
    admin.is_site_admin = True
    admin.is_bot_admin = True
    db.flush()
    return admin


def make_players(db: Session) -> list[models.Player]:
    players: list[models.Player] = []
    for index, (nickname, full_name) in enumerate(PLAYER_NAMES, start=1):
        player = player_service.create_player(
            db,
            nickname=nickname,
            slug=f"player-{index}",
            full_name=full_name,
            age=18 + (index % 12),
            favorite_role=["citizen", "sheriff", "mafia", "don"][index % 4],
            bio="Демо-профиль для тестового стенда.",
        )
        players.append(player)
    db.flush()
    return players


def make_bot_players(db: Session) -> list[models.Player]:
    players: list[models.Player] = []
    for index, (nickname, full_name, affiliation, status, salutation) in enumerate(BOT_PLAYERS):
        player = player_service.create_player(
            db,
            nickname=nickname,
            slug=f"bot-player-{index + 1}",
            full_name=full_name,
            telegram_id=900_000 + index,
            telegram_username=f"demo_user_{index + 1}",
            phone=f"7999000{index:04d}",
        )
        player.salutation = salutation
        player.affiliation = affiliation
        player.confirmation_status = status
        if status != "pending":
            player.confirmation_decided_at = datetime.now(CLUB_TZ) - timedelta(days=1)
            # Решение помечено доставленным: иначе бот на первом же проходе
            # разошлёт демо-игрокам сообщения о подтверждении.
            player.confirmation_notified_at = datetime.now(CLUB_TZ) - timedelta(days=1)
        if status == "rejected":
            player.rejection_reason = "ФИО не совпадает с документом, поправьте и отправьте заново"
        players.append(player)
    db.flush()
    return players


def _roster(players: list[models.Player], rng: random.Random) -> list[ParticipantInput]:
    """Десять мест с классическим раскладом ролей и правдоподобными баллами."""
    chosen = players[:10]
    seats = SEATING[:]
    rng.shuffle(seats)
    participants = []
    for seat, (player, role) in enumerate(zip(chosen, seats), start=1):
        participants.append(
            ParticipantInput(
                player_id=player.id,
                seat_number=seat,
                role=role,
                points_win=round(rng.uniform(0, 3), 1),
                ci=round(rng.uniform(0, 0.6), 1) if rng.random() < 0.4 else None,
                lh=rng.choice([0.0, 0.5, 1.0, 1.5]) if seat == 1 else None,
                info="first_killed" if seat == 1 else None,
            )
        )
    return participants


def make_tournament(db: Session, players: list[models.Player], admin_id: int, rng: random.Random) -> None:
    now = datetime.now(CLUB_TZ)
    tournament = tournament_service.create_tournament(
        db,
        name="Кубок ВМК 2026",
        slug="kubok-vmk-2026",
        starts_at=now - timedelta(days=21),
        ends_at=now - timedelta(days=7),
        location="ВМК МГУ, ауд. 685",
        description="Демонстрационный турнир тестового стенда: два этапа, отбор и финал.",
    )

    # Состав внутри одного этапа обязан совпадать во всех его играх
    # (game_service._validate_tournament_roster_consistency), поэтому каждый
    # этап получает свою фиксированную десятку.
    stages = [
        ("Отборочный стол", players[:10], 3, False),
        ("Финал", players[5:15], 2, True),
    ]
    for order, (name, roster, games_count, is_final) in enumerate(stages, start=1):
        stage = tournament_service.create_stage(
            db,
            tournament_id=tournament.id,
            name=name,
            games_count=games_count,
            order=order,
            is_final=is_final,
            created_by=admin_id,
        )
        slots = tournament_service.list_stage_games(db, stage_id=stage.id)
        for index, slot in enumerate(slots):
            game_service.update_rated_game(
                db,
                game=slot,
                starts_at=tournament.starts_at + timedelta(days=index, hours=18),
                location=tournament.location,
                game_type=None,
                tournament_id=None,
                result=rng.choice(["city_win", "mafia_win"]),
                notes=None,
                participants=_roster(roster, rng),
            )
        if is_final:
            tournament_service.set_stage_advances(
                db, stage_id=stage.id, player_ids={p.id for p in roster[:4]}
            )
        else:
            tournament_service.set_stage_advances(
                db, stage_id=stage.id, player_ids={p.id for p in roster[:5]}
            )
    db.flush()


def make_rated_funky(db: Session, players: list[models.Player], admin_id: int, rng: random.Random) -> None:
    now = datetime.now(CLUB_TZ)
    for index in range(2):
        game_service.create_rated_game(
            db,
            starts_at=now - timedelta(days=5 - index, hours=-19),
            location="ВМК МГУ, ауд. 685",
            game_type="funky",
            tournament_id=None,
            result=rng.choice(["city_win", "mafia_win"]),
            notes=None,
            created_by=admin_id,
            participants=_roster(players[3:13], rng),
        )
    db.flush()


def _slots_inside_current_week(db: Session) -> list[datetime]:
    """Три момента внутри ТЕКУЩЕЙ пропускной недели, ещё не наступивших.

    Считаются от настоящего окна (pass_list_service), а не «завтра-послезавтра»:
    рубеж по умолчанию — воскресенье 18:00, и наивные +1/+2 дня спокойно
    уезжают за него, оставляя вкладку «Нужен пропуск» демонстративно пустой.
    """
    _, window_end = pass_list_service.current_week_window(db)
    now = datetime.now(CLUB_TZ)
    remaining = window_end - now
    slots = []
    for fraction in (0.3, 0.55, 0.8):
        moment = now + remaining * fraction
        rounded = moment.replace(minute=0, second=0, microsecond=0)
        slots.append(rounded if rounded > now else moment.replace(second=0, microsecond=0))
    return slots


def make_upcoming_sessions(db: Session, bot_players: list[models.Player], admin_id: int) -> None:
    _, window_end = pass_list_service.current_week_window(db)
    this_week = _slots_inside_current_week(db)
    next_week = [window_end + timedelta(days=1, hours=19), window_end + timedelta(days=3, hours=19)]

    sessions: list[models.Game] = []
    for index, starts_at in enumerate(this_week + next_week):
        game = models.Game(
            starts_at=starts_at,
            location="ВМК МГУ, ауд. 685",
            game_type="funky" if index % 2 == 0 else "training",
            registration_until=starts_at,
            max_players=10,
            status="scheduled",
            created_by=admin_id,
        )
        db.add(game)
        sessions.append(game)
    db.flush()

    # Записи расставлены так, чтобы в списке на пропуск оказались и основной
    # состав, и ведущий, и резерв, и неподтверждённый игрок -- все четыре
    # случая, которые вкладка обязана показать.
    by_nickname = {player.nickname: player for player in bot_players}
    plan = [
        (sessions[0], "Тень", "player"),
        (sessions[0], "Вьюга", "host"),
        (sessions[0], "Аврора", "player"),
        (sessions[1], "Штиль", "player"),
        (sessions[1], "Ясень", "judge"),
        (sessions[2], "Юнга", "player"),
        # Эта игра уже за рубежом недели: в текущем списке её быть не должно.
        (sessions[3], "Тень", "player"),
    ]
    for game, nickname, role in plan:
        db.add(models.Registration(game_id=game.id, player_id=by_nickname[nickname].id, role=role))
    db.add(models.Reserve(game_id=sessions[0].id, player_id=by_nickname["Штиль"].id))
    db.flush()


def make_pending_review(db: Session, players: list[models.Player], admin_id: int) -> None:
    """Игра, которая уже прошла, но результат не внесён -- строка в «Ждут оценки»."""
    now = datetime.now(CLUB_TZ)
    game = models.Game(
        starts_at=now - timedelta(days=1, hours=-19),
        location="ВМК МГУ, ауд. 685",
        game_type="funky",
        registration_until=now - timedelta(days=1, hours=-19),
        max_players=10,
        status="played",
        created_by=admin_id,
    )
    db.add(game)
    db.flush()
    for index, player in enumerate(players[:10]):
        db.add(models.Registration(game_id=game.id, player_id=player.id, role="player"))
    db.flush()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Сначала вычистить все данные. Без него скрипт откажется работать на непустой базе.",
    )
    args = parser.parse_args()

    # Один и тот же seed -- значит один и тот же стенд после каждого прогона:
    # воспроизводимость важнее «живости» случайных баллов.
    rng = random.Random(20260906)

    db = SessionLocal()
    try:
        if args.reset:
            reset(db)
        elif not is_empty(db):
            print(
                "В базе уже есть игроки. Запустите с --reset, если данные можно потерять.",
                file=sys.stderr,
            )
            return 1

        admin = make_admin(db)
        players = make_players(db)
        bot_players = make_bot_players(db)
        db.commit()

        make_tournament(db, players, admin.id, rng)
        make_rated_funky(db, players, admin.id, rng)
        make_pending_review(db, players, admin.id)
        make_upcoming_sessions(db, bot_players, admin.id)
        db.commit()

        window_start, window_end = pass_list_service.current_week_window(db)
        pass_list = pass_list_service.build_pass_list(db)
        db.commit()

        print("Стенд наполнен.\n")
        print(f"  Админка:   /mafia/admin/login")
        print(f"  Логин:     {ADMIN_USERNAME}")
        print(f"  Пароль:    {ADMIN_PASSWORD}\n")
        print(f"  Игроков:            {db.query(models.Player).count()}")
        print(f"  Оценённых игр:      {db.query(models.Game).filter(models.Game.status == 'rated').count()}")
        print(f"  Ждут оценки:        {len(game_service.games_pending_review(db))}")
        print(f"  Ждут подтверждения: {db.query(models.Player).filter(models.Player.confirmation_status == 'pending').count()}")
        print(
            f"  Нужен пропуск:      {len(pass_list.entries)} "
            f"(неделя {window_start:%d.%m %H:%M} — {window_end:%d.%m %H:%M})"
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
