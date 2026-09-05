from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app import models
from app.services import rating_service


class GameValidationError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


@dataclass
class ParticipantInput:
    player_id: int
    seat_number: int
    role: str
    points_win: float = 0
    points_judge: float = 0
    lh: float | None = None
    ci: float | None = None
    info: str | None = None
    removals: int | None = None
    ppk: bool = False
    zk: float | None = None
    sk: float | None = None


# Классическая раздача на десять человек. Это не настройка, а допущение,
# зашитое в саму формулу рейтинга: rating_service.M = 7.0 -- размер команды, и
# ожидаемый результат E считается от средних рейтингов ровно двух команд.
EXPECTED_ROLES = Counter({"don": 1, "mafia": 2, "sheriff": 1, "citizen": 6})

# Шкала ЛХ: попадания «сколько из трёх названных оказались чёрными».
# Совпадает с rating_service.LH_POINTS и с CHECK-констрейнтом
# ck_participants_lh_scale в БД.
VALID_LH_VALUES = frozenset({0.0, 0.5, 1.0, 1.5})


def _validate_participants(participants: list[ParticipantInput]) -> None:
    if len(participants) != 10:
        raise GameValidationError("В игре должно быть ровно 10 участников")

    seats = [p.seat_number for p in participants]
    if sorted(seats) != list(range(1, 11)):
        raise GameValidationError("Места за столом должны быть уникальны и покрывать 1..10")

    player_ids = [p.player_id for p in participants]
    if len(set(player_ids)) != len(player_ids):
        raise GameValidationError("Игрок не может занимать больше одного места в одной игре")

    valid_roles = {"mafia", "don", "sheriff", "citizen"}
    for p in participants:
        if p.role not in valid_roles:
            raise GameValidationError(f"Недопустимая роль: {p.role}")
        if p.lh is not None and float(p.lh) not in VALID_LH_VALUES:
            raise GameValidationError("ЛХ должен быть одним из значений 0, 0.5, 1, 1.5")
        if p.info is not None and p.info not in {"first_killed", "killed", "voted_out"}:
            raise GameValidationError(f"Недопустимое значение Инфо: {p.info}")

    # Раньше роли проверялись поштучно, а состав целиком -- нет: игра из десяти
    # мирных сохранялась молча. Дальше в реплее рейтинга список чёрных оказывался
    # пуст, средний рейтинг «команды» подставлялся как START_RATING, и формула
    # считалась по несуществующей команде -- без единой ошибки.
    if Counter(p.role for p in participants) != EXPECTED_ROLES:
        raise GameValidationError(
            "Состав ролей должен быть: 1 дон, 2 мафии, 1 шериф, 6 мирных"
        )

    # Первоубиенный в игре ровно один -- и ЛХ бывает только у него. Без этих
    # двух проверок баллы за ЛХ уходили в рейтинг и в средний балл любому, у
    # кого заполнено поле, а распределение ЛХ на странице игрока фильтрует по
    # info == 'first_killed' и такого игрока не показывало: числа на двух
    # страницах переставали сходиться без видимой причины.
    first_killed = [p for p in participants if p.info == "first_killed"]
    if len(first_killed) > 1:
        raise GameValidationError("Первоубиенный в игре может быть только один")
    if any(p.lh is not None and p.info != "first_killed" for p in participants):
        raise GameValidationError("ЛХ заполняется только у первоубиенного")


def _resolve_tournament(db: Session, *, game_type: str, tournament_id: int | None) -> int | None:
    """Турнир обязателен ровно для турнирных игр и бессмысленен для остальных.

    То же правило продублировано чек-констрейнтом в БД (для оценённых игр),
    но проверяем и здесь, чтобы отдать 422 с внятным текстом, а не 500 от
    нарушения констрейнта.
    """
    if game_type != "tournament":
        if tournament_id is not None:
            raise GameValidationError("Турнир указывается только для турнирных игр")
        return None
    if tournament_id is None:
        raise GameValidationError("Для турнирной игры нужно выбрать турнир")
    if db.get(models.Tournament, tournament_id) is None:
        raise GameValidationError("Турнир не найден")
    return tournament_id


def _resolve_stage(db: Session, *, tournament_id: int | None, stage_id: int | None) -> int | None:
    """Этап обязателен ровно тогда, когда у турнира вообще есть этапы.

    Обычный турнир (≤10 участников, без сетки) этапов не заводит -- его игры
    всегда держат stage_id=NULL, поведение не меняется относительно того, что
    было до сеток. Как только у турнира появился хотя бы один этап (админ
    завёл квалификацию), КАЖДАЯ его игра обязана лежать на конкретном этапе --
    иначе турнирные таблицы снова смешают несопоставимые составы, а это и
    была исходная проблема, которую сетки решают.
    """
    if tournament_id is None:
        if stage_id is not None:
            raise GameValidationError("Этап указывается только вместе с турниром")
        return None

    has_stages = (
        db.query(models.TournamentStage.id)
        .filter(models.TournamentStage.tournament_id == tournament_id)
        .first()
        is not None
    )
    if not has_stages:
        if stage_id is not None:
            raise GameValidationError("У этого турнира нет этапов")
        return None

    if stage_id is None:
        raise GameValidationError("У этого турнира есть этапы — выберите этап для игры")

    stage = db.get(models.TournamentStage, stage_id)
    if stage is None or stage.tournament_id != tournament_id:
        raise GameValidationError("Этап не найден в этом турнире")
    return stage_id


def create_rated_game(
    db: Session,
    *,
    starts_at: datetime,
    location: str | None,
    game_type: str,
    tournament_id: int | None,
    stage_id: int | None = None,
    result: str,
    notes: str | None,
    created_by: int,
    participants: list[ParticipantInput],
) -> models.Game:
    if game_type == "tournament":
        # Единственный путь создания турнирной игры -- bulk-слоты этапа
        # (tournament_service.create_stage_with_games / add_stage_game):
        # там сразу известны tournament_id/stage_id и плейсхолдер-дата
        # турнира, а результат вносится потом отдельным шагом (оценкой).
        # Через этот эндпоинт (общая вкладка «Игры») турнир создать нельзя.
        raise GameValidationError("Турнирные игры создаются в разделе «Турниры», внутри этапа")
    _validate_participants(participants)
    if result not in {"city_win", "mafia_win", "draw"}:
        raise GameValidationError("Недопустимый исход игры")
    tournament_id = _resolve_tournament(db, game_type=game_type, tournament_id=tournament_id)
    stage_id = _resolve_stage(db, tournament_id=tournament_id, stage_id=stage_id)

    game = models.Game(
        starts_at=starts_at,
        location=location,
        game_type=game_type,
        tournament_id=tournament_id,
        stage_id=stage_id,
        status="rated",
        result=result,
        notes=notes,
        created_by=created_by,
    )
    db.add(game)
    db.flush()

    for p in participants:
        db.add(
            models.GameParticipant(
                game_id=game.id,
                player_id=p.player_id,
                seat_number=p.seat_number,
                role=p.role,
                points_win=p.points_win,
                points_judge=p.points_judge,
                lh=p.lh,
                ci=p.ci,
                info=p.info,
                removals=p.removals,
                ppk=p.ppk,
                zk=p.zk,
                sk=p.sk,
            )
        )
    db.flush()

    rating_service.recompute_all(db)
    return game


def _validate_tournament_roster_consistency(
    db: Session, *, game: models.Game, participants: list[ParticipantInput]
) -> None:
    """В одной турнирной таблице (турнир без этапов целиком -- или конкретный
    этап) соревнуются одни и те же 10 игроков во всех её играх: иначе сумма
    очков по таблице теряет смысл (кто-то сыграл 3 игры, кто-то одну).
    Сверяем состав с любой другой уже оценённой игрой этой же таблицы --
    первая оценённая игра тем самым неявно фиксирует состав для всех
    следующих."""
    stage_filter = (
        models.Game.stage_id.is_(None) if game.stage_id is None else models.Game.stage_id == game.stage_id
    )
    sibling = (
        db.query(models.Game)
        .filter(
            models.Game.tournament_id == game.tournament_id,
            stage_filter,
            models.Game.status == "rated",
            models.Game.id != game.id,
        )
        .first()
    )
    if sibling is None:
        return
    existing_ids = {p.player_id for p in sibling.participants}
    new_ids = {p.player_id for p in participants}
    if existing_ids != new_ids:
        raise GameValidationError(
            "Состав игроков должен быть одинаковым во всех играх этой таблицы (турнира или этапа)"
        )


def update_rated_game(
    db: Session,
    *,
    game: models.Game,
    starts_at: datetime | None,
    location: str | None,
    game_type: str | None,
    tournament_id: int | None,
    stage_id: int | None = None,
    result: str | None,
    notes: str | None,
    participants: list[ParticipantInput] | None,
) -> models.Game:
    if starts_at is not None:
        game.starts_at = starts_at
    if location is not None:
        game.location = location
    if notes is not None:
        game.notes = notes

    if game_type is not None and game_type != game.game_type:
        # Явная смена формата. "В турнир" через этот путь тоже нельзя --
        # у турнирной игры сразу должны быть tournament_id/stage_id, которые
        # общая форма (funky/training) не собирает.
        if game_type == "tournament":
            raise GameValidationError("Турнирные игры создаются в разделе «Турниры», внутри этапа")
        game.game_type = game_type
        game.tournament_id = _resolve_tournament(db, game_type=game.game_type, tournament_id=tournament_id)
        game.stage_id = _resolve_stage(db, tournament_id=game.tournament_id, stage_id=stage_id)
    elif game.game_type != "tournament":
        # Формат не меняется и это не турнирная игра -- как раньше: обычно
        # tournament_id/stage_id так и остаются NULL, но перепроверяем на
        # случай ошибочно переданного значения.
        game.tournament_id = _resolve_tournament(db, game_type=game.game_type, tournament_id=tournament_id)
        game.stage_id = _resolve_stage(db, tournament_id=game.tournament_id, stage_id=stage_id)
    # else: game.game_type уже 'tournament' и не меняется -- турнир и этап
    # зафиксированы при создании слота (см. tournament_service) и через форму
    # оценки не переназначаются, что бы ни пришло в tournament_id/stage_id.

    if participants is not None:
        _validate_participants(participants)
        if result is None:
            raise GameValidationError("При обновлении состава нужно указать исход игры")
        if result not in {"city_win", "mafia_win", "draw"}:
            raise GameValidationError("Недопустимый исход игры")
        if game.game_type == "tournament":
            _validate_tournament_roster_consistency(db, game=game, participants=participants)

        db.query(models.GameParticipant).filter(models.GameParticipant.game_id == game.id).delete()
        for p in participants:
            db.add(
                models.GameParticipant(
                    game_id=game.id,
                    player_id=p.player_id,
                    seat_number=p.seat_number,
                    role=p.role,
                    points_win=p.points_win,
                    points_judge=p.points_judge,
                    lh=p.lh,
                    ci=p.ci,
                    info=p.info,
                    removals=p.removals,
                    ppk=p.ppk,
                    zk=p.zk,
                    sk=p.sk,
                )
            )
        game.result = result
        game.status = "rated"
    elif result is not None:
        if result not in {"city_win", "mafia_win", "draw"}:
            raise GameValidationError("Недопустимый исход игры")
        game.result = result

    db.flush()
    rating_service.recompute_all(db)
    return game


def delete_game(db: Session, *, game: models.Game) -> None:
    was_rated = game.status == "rated"
    db.delete(game)
    db.flush()
    if was_rated:
        rating_service.recompute_all(db)


def games_pending_review(db: Session) -> list[models.Game]:
    """Только бот-игры: у турнирных слотов своя отдельная очередь оценки
    внутри их этапа (см. tournament_service) -- этот дэшборд про сессии,
    сыгранные через бота, время которых прошло, а результат не внесён."""
    return (
        db.query(models.Game)
        .filter(models.Game.status == "played", models.Game.game_type != "tournament")
        .order_by(models.Game.starts_at.asc())
        .all()
    )


def mark_past_sessions_as_played(db: Session) -> int:
    """Переводит прошедшие 'scheduled'/'registration_closed' игры в 'played'.
    Вызывается фоновой задачей API (см. app/tasks.py), которая подключена
    через lifespan в app/main.py.

    Турнирные слоты этапа НЕ трогает: у них starts_at -- дата турнира-
    плейсхолдер (может уже быть в прошлом на момент создания слота), и они
    оцениваются напрямую внутри своего этапа, минуя 'played' и общий дэшборд
    «Ждут оценки» -- там про них никто не спрашивает, админ и так их видит.
    """
    now = datetime.now(timezone.utc)
    rows = (
        db.query(models.Game)
        .filter(models.Game.status.in_(["scheduled", "registration_closed"]))
        .filter(models.Game.starts_at < now)
        .filter(models.Game.game_type != "tournament")
        .all()
    )
    for game in rows:
        game.status = "played"
    db.flush()
    return len(rows)
