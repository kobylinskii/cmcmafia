from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app import models, serializers
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

# Какой исход присуждается, когда игрок получил ППК: победу забирает команда
# соперников. Ключ -- команда нарушителя.
PPK_AWARDS_WIN_TO = {"black": "city_win", "red": "mafia_win"}

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


def _validate_ppk(
    participants: Sequence[ParticipantInput | models.GameParticipant], result: str
) -> None:
    """ППК -- поражение по причине нарушения: победа присуждается команде
    соперников, а нарушитель остаётся без дополнительных баллов и получает
    штраф (stats_service.SCORE_PENALTY_PPK).

    Проверяется здесь, а не только в форме: правило меняет ИСХОД игры, а от
    исхода зависит и рейтинг Эло, и победы в статистике каждого участника.
    Разъехавшийся исход тихо испортил бы и то, и другое.

    Принимает и присланный состав, и уже сохранённый: при смене одного лишь
    исхода нового состава нет, а проверить правило всё равно нужно -- поля
    ppk/role/points_judge/lh у обеих сторон называются одинаково.
    """
    offenders = [p for p in participants if p.ppk]
    if not offenders:
        return
    if len(offenders) > 1:
        raise GameValidationError("ППК в игре может быть только у одного игрока")

    offender = offenders[0]
    team = "black" if offender.role in {"mafia", "don"} else "red"
    expected = PPK_AWARDS_WIN_TO[team]
    if result != expected:
        awarded = "городу" if expected == "city_win" else "мафии"
        raise GameValidationError(
            f"При ППК победа присуждается команде соперников — {awarded}. "
            f"Исправьте исход игры."
        )

    # «0 доп баллов за игру»: доп. балл -- это судейские плюс ЛХ
    # (stats_service._BONUS_SQL). Штраф за сам ППК и карточки считаются
    # отдельно и здесь не трогаются.
    if offender.points_judge:
        raise GameValidationError("Игрок с ППК не получает дополнительных баллов от судей")
    if offender.lh is not None:
        raise GameValidationError("Игрок с ППК не получает баллов за ЛХ")


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
    _validate_ppk(participants, result)
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
            "ROSTER_MISMATCH: состав игроков должен быть одинаковым во всех играх "
            "этой таблицы (турнира или этапа)"
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
    allow_roster_change: bool = False,
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
        # Тот же вызов, что и в create_rated_game. Без него правило ППК не
        # действовало там, где оно нужно чаще всего: турнирная игра заводится
        # пустым слотом и оценивается ИСКЛЮЧИТЕЛЬНО через этот путь, так что
        # проверка только на создании для турниров не срабатывала никогда.
        _validate_ppk(participants, result)
        # Состав внутри одной турнирной таблицы должен совпадать во всех её
        # играх -- иначе сумма очков перестаёт что-либо значить. Но админ живой
        # и ошибается: если во второй игре обнаружилось, что в первой не тот
        # игрок, запрет «правьте только до первой оценки» загоняет в тупик --
        # пришлось бы удалять уже внесённые игры. Поэтому не запрет, а
        # подтверждение: форма ловит эту 422, объясняет последствие и
        # повторяет запрос с allow_roster_change. Публичная страница турнира
        # при расхождении показывает предупреждение над таблицей.
        if game.game_type == "tournament" and not allow_roster_change:
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
        # Тот же _validate_ppk, что и выше, но по УЖЕ СОХРАНЁННОМУ составу.
        # Без него правило обходилось одним PUT {"result": ...} без
        # participants: игра с ППК дона переписывалась на победу мафии, и
        # recompute_all начислял победу самому нарушителю и его команде.
        _validate_ppk(game.participants, result)
        game.result = result

    db.flush()
    rating_service.recompute_all(db)
    return game


def resequence_game_ids(db: Session) -> dict[int, int]:
    """Перенумеровывает игры: id = порядковый номер по дате проведения, без дыр.

    Номер игры -- то, чем её называют («игра №14»), и он же лежит в URL
    /mafia/games/{id}. По умолчанию SERIAL нумерует в порядке СОЗДАНИЯ, из-за
    чего игра, заведённая задним числом, получала номер больше уже сыгранных
    позже неё, а удаление непроведённой игры навсегда оставляло дыру в
    нумерации. Здесь id приводится к тому, чем его и читают -- к позиции игры
    в хронологии.

    Возвращает {старый id: новый id} только для реально переехавших игр:
    вызывающий код держит объекты, чьи первичные ключи после этого недействительны,
    и обязан перечитать их по новому id (все роутеры так и делают -- сразу
    после db.commit(), который и так сбрасывает состояние объектов).

    Порядок -- (дата, момент создания, текущий id): у турнирных слотов дата
    одна на весь этап (плейсхолдер по турниру, см. tournament_service), и без
    двух запасных ключей их взаимный порядок скакал бы при каждой
    перенумерации.

    Переезд ключа за собой тянут внешние ключи с ON UPDATE CASCADE
    (миграция c9a2f4e17b58) -- составы, записи, резерв и история рейтинга.
    """
    # Всё, что сессия ещё не записала, должно оказаться в таблице до того, как
    # по ней пойдёт голый SQL: иначе новая игра не попадёт в нумерацию.
    db.flush()

    ids = list(
        db.execute(
            select(models.Game.id).order_by(
                models.Game.starts_at, models.Game.created_at, models.Game.id
            )
        ).scalars()
    )
    mapping = {old: new for new, old in enumerate(ids, start=1) if old != new}

    if mapping:
        # Два прохода, потому что первичный ключ проверяется на уникальность
        # построчно, а не в конце оператора: прямой UPDATE ... = row_number()
        # упёрся бы в уже занятый номер. Сдвиг на max(id) выносит все ключи за
        # пределы занятого диапазона, после чего целевые номера свободны.
        offset = max(ids)
        db.execute(text("UPDATE games SET id = id + :offset"), {"offset": offset})
        db.execute(
            text(
                """
                WITH ordered AS (
                    SELECT id, row_number() OVER (
                        ORDER BY starts_at, created_at, id
                    ) AS rn
                    FROM games
                )
                UPDATE games g SET id = ordered.rn
                FROM ordered
                WHERE g.id = ordered.id
                """
            )
        )

    # Последовательность ушла вперёд на все удалённые и перенумерованные игры;
    # без сброса следующая игра получила бы номер из будущего и первая же
    # перенумерация его отобрала.
    db.execute(
        text(
            "SELECT setval("
            "  pg_get_serial_sequence('games', 'id'),"
            "  COALESCE((SELECT MAX(id) FROM games), 0) + 1,"
            "  false"
            ")"
        )
    )
    return mapping


def resequence_and_reload(db: Session, *, game_ids: list[int]) -> list[models.Game]:
    """Перенумеровать игры, зафиксировать это и перечитать перечисленные игры
    под их новыми номерами -- в том же порядке, в каком их передали.

    Роутеры, меняющие состав или даты игр, вызывают это СРАЗУ ПОСЛЕ своего
    db.commit(): к этому моменту у сессии не остаётся незаписанных изменений,
    а объекты после коммита и так просрочены, так что старые (уже
    недействительные) первичные ключи никто не прочитает. Обычный db.refresh()
    на этом месте пошёл бы в базу за строкой по СТАРОМУ id и её там не нашёл.
    """
    mapping = resequence_game_ids(db)
    db.commit()
    games = []
    for game_id in game_ids:
        game = db.get(models.Game, mapping.get(game_id, game_id))
        if game is not None:
            games.append(game)
    return games


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
        # Страховка на случай, если флаг сняли уже с проведённой игры: статус
        # при этом откатывается в 'scheduled' (см. роутер расписания), но
        # список оценки не должен зависеть от того, отработал ли откат.
        .filter(models.Game.needs_rating.is_(True))
        .order_by(models.Game.starts_at.asc())
        .all()
    )


# Статусы сессии, из которых её ещё можно подтвердить как проведённую.
UNCONFIRMED_STATUSES = ("scheduled", "registration_closed")


def sessions_awaiting_confirmation(db: Session) -> list[models.Game]:
    """Прошедшие сессии, которые админ ещё не подтвердил.

    Раньше этого списка не существовало: фоновая задача сама переводила
    прошедшую игру в 'played', и она немедленно оказывалась в «Ждут оценки» --
    вместе с играми, которые на деле не собрались. Теперь переход делает
    человек, и ему нужно место, где видно всё непподтверждённое, иначе
    забытая игра не всплывёт нигде.

    Игры с needs_rating=False сюда не попадают: у них не будет результата, и
    спрашивать про них «состоялась ли» не за чем -- ответ ни на что не влияет.
    """
    return (
        db.query(models.Game)
        .options(*serializers.session_load_options())
        .filter(models.Game.status.in_(UNCONFIRMED_STATUSES))
        .filter(models.Game.needs_rating.is_(True))
        .filter(models.Game.starts_at < datetime.now(timezone.utc))
        .filter(models.Game.game_type != "tournament")
        .order_by(models.Game.starts_at.asc())
        .all()
    )


def mark_session_played(db: Session, *, game: models.Game) -> models.Game:
    """«Игра проведена»: единственная дорога сессии в «Ждут оценки».

    Турнирные слоты сюда не ходят -- они оцениваются внутри своего этапа,
    минуя 'played' (см. раздел 7 ARCHITECTURE.md).
    """
    if game.game_type == "tournament":
        raise GameValidationError("Турнирные игры оцениваются внутри этапа, а не здесь")
    if not game.needs_rating:
        raise GameValidationError("Игра создана без оценки — подтверждать её проведение не нужно")
    if game.status == "rated":
        raise GameValidationError("Игра уже оценена")
    if game.status == "played":
        raise GameValidationError("Игра уже отмечена как проведённая")
    if game.starts_at > datetime.now(timezone.utc):
        raise GameValidationError("Игра ещё не началась — отметить её проведение пока нечем")
    game.status = "played"
    db.flush()
    return game
