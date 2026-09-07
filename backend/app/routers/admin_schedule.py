"""Планировщик игр в админке сайта: `/api/admin/schedule/*`.

Это переехавшая целиком админка бота. В боте от неё остались только вещи,
которые без Telegram не работают: выдача прав и две рассылки (см.
`routers/bot_admin.py`). Всё, что касается слотов -- создание дня,
правка, удаление, подтверждение проведения -- живёт здесь, за
`require_site_admin`, вместе с оценкой игр.
"""

# Без `from __future__ import annotations`: slowapi оборачивает обработчик, и
# FastAPI разбирает строковые аннотации в глобалях обёртки, а не этого модуля --
# тело запроса тогда молча уезжает в query-параметры. Остальные роутеры не
# импортируют его по той же причине.

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import models, serializers
from app.database import get_db
from app.deps import require_site_admin
from app.rate_limit import limiter
from app.schemas.bot import SessionOut
from app.schemas.schedule import (
    ScheduleDayOut,
    ScheduleSessionOut,
    ScheduleSessionUpdateIn,
    SchedulePlanIn,
    SchedulePlanPreviewOut,
)
from app.services import game_service, schedule_admin_service
from app.services.game_service import GameValidationError
from app.timeutil import club_day_time

router = APIRouter(
    prefix="/api/admin/schedule",
    tags=["admin-schedule"],
    dependencies=[Depends(require_site_admin)],
)


def _get_session_or_404(db: Session, session_id: int) -> models.Game:
    game = db.get(models.Game, session_id)
    if game is None:
        raise HTTPException(404, "Игра не найдена")
    if game.game_type == "tournament":
        # Турнирный слот в расписание не попадает по построению; отдельная
        # 404 понятнее, чем молчаливая правка игры не из этого раздела.
        raise HTTPException(404, "Турнирные игры ведутся во вкладке «Турниры»")
    return game


def _session_out(game: models.Game) -> ScheduleSessionOut:
    return ScheduleSessionOut(
        **serializers.session_to_out(game).model_dump(),
        roster=serializers.roster_to_out(game),
    )


@router.get("/days", response_model=list[ScheduleDayOut])
@limiter.limit("60/minute")
def list_days(request: Request, game_type: str | None = None, db: Session = Depends(get_db)) -> list[dict]:
    return schedule_admin_service.day_cards(db, game_type=game_type)


@router.get("/sessions", response_model=list[SessionOut])
@limiter.limit("60/minute")
def list_sessions_by_day(request: Request, day: str, db: Session = Depends(get_db)) -> list[SessionOut]:
    """Игры одного дня. `day` -- «ДД.ММ.ГГГГ» по московскому времени."""
    try:
        games = schedule_admin_service.games_by_day(db, day=day)
    except ValueError as exc:
        raise HTTPException(422, "Дата должна быть в формате ДД.ММ.ГГГГ") from exc
    return [serializers.session_to_out(g) for g in games]


@router.post("/plan/preview", response_model=SchedulePlanPreviewOut)
# Втрое щедрее остальных: форма планирования дёргает предпросмотр на каждую
# правку полей (с задержкой), и общий лимит 60/мин упирался бы в обычную
# перенастройку часа и шага, а сама ручка ничего не пишет.
@limiter.limit("180/minute")
def preview_plan(request: Request, data: SchedulePlanIn, db: Session = Depends(get_db)) -> SchedulePlanPreviewOut:
    starts = schedule_admin_service.planned_starts(
        first=data.starts_at, count=data.count, step_minutes=data.step_minutes
    )
    return SchedulePlanPreviewOut(
        starts_at_list=starts,
        conflicts=schedule_admin_service.check_conflicts(db, starts_at_list=starts),
    )


@router.post("/plan", response_model=list[SessionOut])
@limiter.limit("30/minute")
def create_plan(
    request: Request,
    data: SchedulePlanIn,
    db: Session = Depends(get_db),
    actor: models.Player = Depends(require_site_admin),
) -> list[SessionOut]:
    starts = schedule_admin_service.planned_starts(
        first=data.starts_at, count=data.count, step_minutes=data.step_minutes
    )
    conflicts = schedule_admin_service.check_conflicts(db, starts_at_list=starts)
    if conflicts:
        # Пересечение по времени -- почти всегда повторное создание уже
        # заведённого дня, а не намерение посадить два стола разом.
        raise HTTPException(
            409,
            "На это время игры уже созданы: "
            + ", ".join(club_day_time(c) for c in conflicts),
        )
    ids = schedule_admin_service.bulk_create_sessions(
        db,
        starts_at_list=starts,
        location=data.location,
        game_type=data.game_type,
        created_by=actor.id,
        needs_rating=data.needs_rating,
    )
    db.commit()
    # Слоты нумеруются по времени начала, а не по порядку создания, и уже
    # созданные игры сдвигаются, если вечер поставили в прошлое.
    created = game_service.resequence_and_reload(db, game_ids=ids)
    return [serializers.session_to_out(g) for g in created]


@router.get("/awaiting-confirmation", response_model=list[SessionOut])
@limiter.limit("60/minute")
def awaiting_confirmation(request: Request, db: Session = Depends(get_db)) -> list[SessionOut]:
    """Прошедшие игры, про которые ещё не сказано, состоялись ли они."""
    return [serializers.session_to_out(g) for g in game_service.sessions_awaiting_confirmation(db)]


@router.get("/locations", response_model=list[str])
@limiter.limit("60/minute")
def recent_locations(request: Request, db: Session = Depends(get_db)) -> list[str]:
    return schedule_admin_service.recent_locations(db)


@router.get("/sessions/{session_id}", response_model=ScheduleSessionOut)
@limiter.limit("60/minute")
def get_session(request: Request, session_id: int, db: Session = Depends(get_db)) -> ScheduleSessionOut:
    return _session_out(_get_session_or_404(db, session_id))


@router.put("/sessions/{session_id}", response_model=ScheduleSessionOut)
@limiter.limit("30/minute")
def update_session(
    request: Request, session_id: int, data: ScheduleSessionUpdateIn, db: Session = Depends(get_db)
) -> ScheduleSessionOut:
    game = _get_session_or_404(db, session_id)
    if game.status == "rated":
        raise HTTPException(409, "Игра уже оценена — правьте её во вкладке «Оценённые»")

    moved = data.starts_at is not None and data.starts_at != game.starts_at
    if moved:
        conflicts = schedule_admin_service.check_conflicts(
            db, starts_at_list=[data.starts_at], exclude_session_ids={game.id}
        )
        if conflicts:
            raise HTTPException(409, "На это время игра уже создана")
        # registration_until идёт за временем игры, пока админ не задал свой
        # дедлайн: планировщик ставит их равными при создании, и отставший
        # дедлайн молча закрыл бы запись на перенесённую вперёд игру.
        if game.registration_until == game.starts_at:
            game.registration_until = data.starts_at
        game.starts_at = data.starts_at
    if data.location is not None:
        game.location = data.location
    if data.game_type is not None:
        game.game_type = data.game_type
    if data.needs_rating is not None and data.needs_rating != game.needs_rating:
        game.needs_rating = data.needs_rating
        if not data.needs_rating and game.status == "played":
            # Проведение подтверждали ради оценки; раз оценки не будет,
            # игре нечего делать в «Ждут оценки» -- возвращаем её в
            # исходный статус, иначе она зависла бы там навсегда.
            game.status = "scheduled"

    db.commit()
    # Перенумеровываем только когда игра реально переехала по времени:
    # переименование места её номера не касается, а перенумерация трогает
    # всю таблицу.
    if moved:
        game = game_service.resequence_and_reload(db, game_ids=[game.id])[0]
    else:
        db.refresh(game)
    return _session_out(game)


@router.delete("/sessions/{session_id}")
@limiter.limit("30/minute")
def delete_session(request: Request, session_id: int, db: Session = Depends(get_db)) -> dict:
    game = _get_session_or_404(db, session_id)
    game_service.delete_game(db, game=game)
    db.commit()
    # Непроведённая игра удаляется из базы целиком, а нумерация сжимается.
    game_service.resequence_and_reload(db, game_ids=[])
    return {"ok": True}


@router.post("/sessions/{session_id}/played", response_model=ScheduleSessionOut)
@limiter.limit("30/minute")
def mark_played(request: Request, session_id: int, db: Session = Depends(get_db)) -> ScheduleSessionOut:
    """«Игра проведена» -- единственный вход сессии в «Ждут оценки».

    Фоновой задачи, делавшей это самой, больше нет (см. app/main.py), а кнопка
    переехала из бота сюда.
    """
    game = _get_session_or_404(db, session_id)
    try:
        game_service.mark_session_played(db, game=game)
        db.commit()
    except GameValidationError as exc:
        db.rollback()
        raise HTTPException(409, exc.message) from exc
    db.refresh(game)
    return _session_out(game)
