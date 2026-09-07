"""CRUD турниров.

Турнир -- контейнер для турнирных игр: у него своё название, описание и место
проведения. Оценённая игра с game_type='tournament' обязана на него ссылаться
(ограничение в БД, см. миграцию fffc59fca625).
"""

from __future__ import annotations

from collections import defaultdict

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models
from app.services import slug_service
from app.textmatch import ci_equals


class TournamentValidationError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def _validate_slug(slug: str) -> None:
    try:
        slug_service.validate_slug(slug)
    except ValueError as exc:
        raise TournamentValidationError(str(exc)) from exc


def _ensure_unique(db: Session, *, slug: str | None, name: str | None, exclude_id: int | None) -> None:
    if slug is not None:
        query = db.query(models.Tournament).filter(models.Tournament.slug == slug)
        if exclude_id is not None:
            query = query.filter(models.Tournament.id != exclude_id)
        if query.first():
            raise TournamentValidationError(f"Slug «{slug}» уже занят другим турниром")
    if name is not None:
        query = db.query(models.Tournament).filter(ci_equals(models.Tournament.name, name))
        if exclude_id is not None:
            query = query.filter(models.Tournament.id != exclude_id)
        if query.first():
            raise TournamentValidationError("Турнир с таким названием уже есть")


def games_count_map(db: Session) -> dict[int, int]:
    """Число оценённых игр по каждому турниру -- одним запросом, чтобы список
    турниров не превращался в N+1."""
    rows = db.execute(
        select(models.Game.tournament_id, func.count())
        .where(models.Game.tournament_id.is_not(None), models.Game.status == "rated")
        .group_by(models.Game.tournament_id)
    ).all()
    return {tournament_id: count for tournament_id, count in rows}


def list_tournaments(db: Session) -> list[models.Tournament]:
    return db.query(models.Tournament).order_by(models.Tournament.name.asc()).all()


def get_by_slug(db: Session, slug: str) -> models.Tournament | None:
    return db.query(models.Tournament).filter(models.Tournament.slug == slug).one_or_none()


def _validate_date_range(starts_at: datetime, ends_at: datetime) -> None:
    if ends_at < starts_at:
        raise TournamentValidationError("Дата окончания турнира не может быть раньше даты начала")


def create_tournament(
    db: Session,
    *,
    name: str,
    slug: str,
    starts_at: datetime,
    ends_at: datetime,
    description: str | None = None,
    location: str | None = None,
) -> models.Tournament:
    _validate_slug(slug)
    _ensure_unique(db, slug=slug, name=name, exclude_id=None)
    _validate_date_range(starts_at, ends_at)
    tournament = models.Tournament(
        name=name,
        slug=slug,
        starts_at=starts_at,
        ends_at=ends_at,
        description=description,
        location=location,
    )
    db.add(tournament)
    db.flush()
    return tournament


_NON_NULLABLE_FIELDS = frozenset({"name", "slug", "starts_at", "ends_at"})


def update_tournament(db: Session, *, tournament: models.Tournament, **fields) -> models.Tournament:
    if fields.get("slug") is not None:
        _validate_slug(fields["slug"])
    _ensure_unique(
        db,
        slug=fields.get("slug"),
        name=fields.get("name"),
        exclude_id=tournament.id,
    )
    # Диапазон дат может обновляться частично (только начало или только
    # конец) -- сверяем то, что реально будет в базе после применения правки,
    # а не только переданные поля.
    new_starts_at = fields.get("starts_at", tournament.starts_at)
    new_ends_at = fields.get("ends_at", tournament.ends_at)
    if "starts_at" in fields or "ends_at" in fields:
        _validate_date_range(new_starts_at, new_ends_at)
    # Как и у игрока: пришедший явно null -- это очистка поля, а отсутствие
    # ключа -- «не трогать» (роутер отдаёт model_dump(exclude_unset=True)).
    for key, value in fields.items():
        if not hasattr(tournament, key):
            continue
        if value is None and key in _NON_NULLABLE_FIELDS:
            raise TournamentValidationError(f"Поле «{key}» нельзя оставить пустым")
        setattr(tournament, key, value)
    db.flush()
    return tournament


def delete_tournament(db: Session, *, tournament: models.Tournament) -> None:
    """Оценённые игры турнира не удаляем молча -- сначала переносят в другой
    турнир. А вот ещё не оценённые слоты этапов ('scheduled') -- пустые
    заготовки, они и их этапы удаляются вместе с турниром (см. delete_stage)."""
    rated = (
        db.query(models.Game)
        .filter(models.Game.tournament_id == tournament.id, models.Game.status == "rated")
        .count()
    )
    if rated:
        raise TournamentValidationError(
            f"К турниру привязано оценённых игр: {rated}. Сначала перенесите их в другой турнир."
        )
    db.query(models.Game).filter(models.Game.tournament_id == tournament.id).delete()
    db.query(models.TournamentStage).filter(models.TournamentStage.tournament_id == tournament.id).delete()
    db.delete(tournament)
    db.flush()


def add_tournament_games(
    db: Session, *, tournament: models.Tournament, count: int, created_by: int | None = None
) -> list[models.Game]:
    """Слоты турнира БЕЗ этапа -- для простого турнира (≤10 участников), у
    которого просто играется серия из N игр, никакой сетки не нужно (см.
    ответ пользователя: "если в турнире играет 10 человек, то никаких
    турнирных сеток не надо, просто играется серия из N игр"). Как только
    у турнира появляется хотя бы один этап, новые игры заводят уже через
    add_stage_games -- эта функция для турнира с этапами больше не вызывается
    (см. game_form на фронте: кнопка "Добавить игры" скрыта, если есть этапы)."""
    created: list[models.Game] = []
    for _ in range(count):
        game = models.Game(
            starts_at=tournament.starts_at,
            location=tournament.location,
            game_type="tournament",
            tournament_id=tournament.id,
            stage_id=None,
            status="scheduled",
            created_by=created_by,
        )
        db.add(game)
        created.append(game)
    db.flush()
    return created


def list_tournament_games(db: Session, *, tournament_id: int) -> list[models.Game]:
    """Только "плоские" слоты турнира -- без этапа. У турнира с сетками это
    как раз игры псевдо-этапа "Без этапа" (см. TournamentDetailOut)."""
    return (
        db.query(models.Game)
        .filter(models.Game.tournament_id == tournament_id, models.Game.stage_id.is_(None))
        .order_by(models.Game.starts_at.asc(), models.Game.id.asc())
        .all()
    )


# ===================== Этапы (сетка турнира) =====================
#
# Этап существует ТОЛЬКО когда турниру нужна квалификация (>10 участников,
# несколько отборочных столов + финал). Обычный турнир из ≤10 игроков этапов
# не заводит вообще -- games.stage_id остаётся NULL, и вся публичная логика
# работает как раньше (единая сводная таблица по всем играм турнира,
# stats_service.tournament_standings без фильтра по этапу).


def list_stages(db: Session, *, tournament_id: int) -> list[models.TournamentStage]:
    return (
        db.query(models.TournamentStage)
        .filter(models.TournamentStage.tournament_id == tournament_id)
        .order_by(models.TournamentStage.order.asc(), models.TournamentStage.id.asc())
        .all()
    )


def get_stage(db: Session, *, stage_id: int) -> models.TournamentStage | None:
    return db.get(models.TournamentStage, stage_id)


def _unset_other_final_stages(db: Session, *, tournament_id: int, except_stage_id: int | None) -> None:
    """Финальным может быть отмечен только один этап турнира разом -- на
    публичной странице турнира именно его таблица развёрнута по умолчанию, а
    два "финала" сразу сделали бы этот выбор бессмысленным."""
    query = db.query(models.TournamentStage).filter(
        models.TournamentStage.tournament_id == tournament_id,
        models.TournamentStage.is_final.is_(True),
    )
    if except_stage_id is not None:
        query = query.filter(models.TournamentStage.id != except_stage_id)
    query.update({"is_final": False})


def create_stage(
    db: Session,
    *,
    tournament_id: int,
    name: str,
    games_count: int,
    order: int | None = None,
    is_final: bool = False,
    created_by: int | None = None,
) -> models.TournamentStage:
    existing = (
        db.query(models.TournamentStage)
        .filter(models.TournamentStage.tournament_id == tournament_id, ci_equals(models.TournamentStage.name, name))
        .first()
    )
    if existing:
        raise TournamentValidationError(f"Этап «{name}» уже есть в этом турнире")

    if order is None:
        # По умолчанию -- в конец списка, а не всегда "1": иначе второй и
        # третий этап без явного порядка сваливались бы в начало таблицы.
        max_order = (
            db.query(func.max(models.TournamentStage.order))
            .filter(models.TournamentStage.tournament_id == tournament_id)
            .scalar()
        )
        order = (max_order or 0) + 1

    stage = models.TournamentStage(tournament_id=tournament_id, name=name, order=order, is_final=is_final)
    db.add(stage)
    db.flush()
    if is_final:
        _unset_other_final_stages(db, tournament_id=tournament_id, except_stage_id=stage.id)
    # Сразу создаём N пустых слотов этапа -- ровно столько игр запланировано
    # сыграть на этом этапе. Оценка каждого слота происходит позже, отдельно,
    # через общую ручку PUT /admin/games/{id} (см. app.routers.admin).
    add_stage_games(db, stage=stage, count=games_count, created_by=created_by)
    return stage


def add_stage_games(db: Session, *, stage: models.TournamentStage, count: int, created_by: int | None = None) -> list[models.Game]:
    """Досоздаёт count пустых игровых слотов этапа: без участников, без
    результата, status='scheduled'. Дата и место -- плейсхолдер по турниру,
    правятся потом через тот же PUT /admin/games/{id}, которым слот
    оценивается (см. пояснение в game_service.update_rated_game о том, что
    tournament_id/stage_id при этом не переназначаются)."""
    tournament = stage.tournament
    created: list[models.Game] = []
    for _ in range(count):
        game = models.Game(
            starts_at=tournament.starts_at,
            location=tournament.location,
            game_type="tournament",
            tournament_id=stage.tournament_id,
            stage_id=stage.id,
            status="scheduled",
            created_by=created_by,
        )
        db.add(game)
        created.append(game)
    db.flush()
    return created


def list_stage_games(db: Session, *, stage_id: int) -> list[models.Game]:
    return (
        db.query(models.Game)
        .filter(models.Game.stage_id == stage_id)
        .order_by(models.Game.starts_at.asc(), models.Game.id.asc())
        .all()
    )


def update_stage(db: Session, *, stage: models.TournamentStage, **fields) -> models.TournamentStage:
    new_name = fields.get("name")
    if new_name is not None:
        existing = (
            db.query(models.TournamentStage)
            .filter(
                models.TournamentStage.tournament_id == stage.tournament_id,
                ci_equals(models.TournamentStage.name, new_name),
                models.TournamentStage.id != stage.id,
            )
            .first()
        )
        if existing:
            raise TournamentValidationError(f"Этап «{new_name}» уже есть в этом турнире")

    for key, value in fields.items():
        if not hasattr(stage, key):
            continue
        if value is None and key == "name":
            raise TournamentValidationError("Название этапа нельзя оставить пустым")
        setattr(stage, key, value)
    if fields.get("is_final"):
        _unset_other_final_stages(db, tournament_id=stage.tournament_id, except_stage_id=stage.id)
    db.flush()
    return stage


def delete_stage(db: Session, *, stage: models.TournamentStage) -> None:
    """Оценённые слоты этапа не удаляем молча -- это реальный сыгранный
    результат, RESTRICT в БД тут оправдан. А вот ещё не оценённые слоты
    ('scheduled') -- просто пустые заготовки под будущие игры, ничего
    ценного не несут и при удалении этапа удаляются вместе с ним."""
    rated = (
        db.query(models.Game)
        .filter(models.Game.stage_id == stage.id, models.Game.status == "rated")
        .count()
    )
    if rated:
        raise TournamentValidationError(
            f"К этапу привязано оценённых игр: {rated}. Сначала перенесите их на другой этап."
        )
    db.query(models.Game).filter(models.Game.stage_id == stage.id).delete()
    db.delete(stage)
    db.flush()


def get_stage_advances(db: Session, *, stage_id: int) -> set[int]:
    rows = db.query(models.TournamentStageAdvance.player_id).filter(
        models.TournamentStageAdvance.stage_id == stage_id
    )
    return {player_id for (player_id,) in rows}


def get_advances_map(db: Session, *, tournament_id: int) -> dict[int, set[int]]:
    """Прошедшие дальше СРАЗУ по всем этапам турнира: {stage_id -> {player_id}}.
    Одним запросом вместо вызова get_stage_advances() в цикле по этапам."""
    rows = (
        db.query(models.TournamentStageAdvance.stage_id, models.TournamentStageAdvance.player_id)
        .join(
            models.TournamentStage,
            models.TournamentStage.id == models.TournamentStageAdvance.stage_id,
        )
        .filter(models.TournamentStage.tournament_id == tournament_id)
        .all()
    )
    result: dict[int, set[int]] = defaultdict(set)
    for stage_id, player_id in rows:
        result[stage_id].add(player_id)
    return result


def list_games_by_stage(db: Session, *, tournament_id: int) -> dict[int, list[models.Game]]:
    """Игры СРАЗУ по всем этапам турнира: {stage_id -> игры в порядке показа}.
    Одним запросом вместо list_stage_games() в цикле по этапам."""
    rows = (
        db.query(models.Game)
        .join(models.TournamentStage, models.TournamentStage.id == models.Game.stage_id)
        .filter(models.TournamentStage.tournament_id == tournament_id)
        .order_by(models.Game.starts_at.asc(), models.Game.id.asc())
        .all()
    )
    result: dict[int, list[models.Game]] = defaultdict(list)
    for game in rows:
        result[game.stage_id].append(game)
    return result


def games_count_for(db: Session, *, tournament_id: int) -> int:
    """Число оценённых игр одного турнира. games_count_map() строит карту по
    всем турнирам базы -- для страницы одного турнира это лишняя работа."""
    return (
        db.query(func.count())
        .select_from(models.Game)
        .filter(models.Game.tournament_id == tournament_id, models.Game.status == "rated")
        .scalar()
        or 0
    )


def set_stage_advances(db: Session, *, stage_id: int, player_ids: set[int]) -> None:
    """Заменяет весь список прошедших дальше разом -- одна кнопка "Сохранить"
    под сводной таблицей этапа в админке, а не отдельная отметка на игрока."""
    db.query(models.TournamentStageAdvance).filter(
        models.TournamentStageAdvance.stage_id == stage_id
    ).delete()
    db.add_all(
        models.TournamentStageAdvance(stage_id=stage_id, player_id=player_id) for player_id in player_ids
    )
    db.flush()
