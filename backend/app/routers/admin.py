from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.deps import require_site_admin
from app.rate_limit import limiter
from app.schemas.game import GameCreate, GameListItem, GameListOut, GameOut, GameRosterEntry, GameUpdate
from app.schemas.tournament import (
    AddStageGamesIn,
    TournamentAdminOut,
    TournamentCreate,
    TournamentStageAdvancesIn,
    TournamentStageAdvancesOut,
    TournamentStageCreate,
    TournamentStageGameOut,
    TournamentStageOut,
    TournamentStageUpdate,
    TournamentStandingOut,
    TournamentUpdate,
)
from app.schemas.player import (
    PlayerAdminOut,
    PlayerCreate,
    PlayerUpdate,
    SiteAccessGrantOut,
)
from app.schemas.club import (
    PassListEntryOut,
    PassListGameOut,
    PassListOut,
    PassWeekSettingsIn,
    PassWeekSettingsOut,
    PendingPlayerOut,
    PlayerRejectIn,
    ProfileChangeOut,
    ProfileChangeRejectIn,
)
from app import serializers
from app.services import (
    admin_grant,
    game_service,
    pass_list_service,
    player_confirmation_service,
    player_service,
    profile_change_service,
    settings_service,
    slug_service,
    stats_service,
    tournament_service,
)
from app.services.player_confirmation_service import ConfirmationError
from app.services.profile_change_service import ProfileChangeError
from app.services.tournament_service import TournamentValidationError
from app.services.game_service import GameValidationError, ParticipantInput
from app.services.player_service import PlayerValidationError

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_site_admin)])


def _to_participant_inputs(items: list) -> list[ParticipantInput]:
    return [
        ParticipantInput(
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
        for p in items
    ]


# Порядок ролей в составе: сначала те, кто ведёт стол, потом игроки.
_ROSTER_ROLE_ORDER = {"host": 0, "judge": 1, "player": 2}


def _game_to_out(game: models.Game) -> GameOut:
    """То же представление игры, что и на публичной ручке, плюс roster: форма
    оценки открывается с уже подставленным составом из бота."""
    roster = sorted(
        game.registrations,
        key=lambda r: (_ROSTER_ROLE_ORDER.get(r.role, 9), r.created_at),
    )
    return serializers.game_to_out(
        game,
        roster=[
            GameRosterEntry(player_id=r.player_id, nickname=r.player.nickname, role=r.role)
            for r in roster
        ],
    )


@router.get("/games", response_model=GameListOut)
@limiter.limit("30/minute")
def list_games(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> GameListOut:
    """Оценённые игры для вкладки «Игры»: только бот-форматы (фанки/обучающие)
    -- турнирные игры теперь смотрят и оценивают во вкладке «Турниры», внутри
    своего этапа, а не тут (см. game_service.create_rated_game)."""
    rows, total = stats_service.list_rated_games(db, limit=limit, offset=offset, exclude_game_type="tournament")
    return GameListOut(items=[GameListItem.model_validate(g) for g in rows], total=total)


@router.post("/games", response_model=GameOut)
@limiter.limit("30/minute")
def create_game(
    request: Request, data: GameCreate, db: Session = Depends(get_db), actor: models.Player = Depends(require_site_admin)
) -> GameOut:
    try:
        game = game_service.create_rated_game(
            db,
            starts_at=data.starts_at,
            location=data.location,
            game_type=data.game_type,
            tournament_id=data.tournament_id,
            stage_id=data.stage_id,
            result=data.result,
            notes=data.notes,
            created_by=actor.id,
            participants=_to_participant_inputs(data.participants),
        )
        db.commit()
    except GameValidationError as exc:
        db.rollback()
        raise HTTPException(422, exc.message) from exc
    # Номер игры -- её место в хронологии, а не порядок внесения: игра,
    # внесённая задним числом, встаёт между уже сыгранными и сдвигает
    # последующие. См. game_service.resequence_game_ids.
    game = game_service.resequence_and_reload(db, game_ids=[game.id])[0]
    return _game_to_out(game)


@router.get("/games/pending-review", response_model=list[GameListItem])
@limiter.limit("30/minute")
def games_pending_review(request: Request, db: Session = Depends(get_db)) -> list[models.Game]:
    return game_service.games_pending_review(db)


@router.get("/games/{game_id}", response_model=GameOut)
@limiter.limit("30/minute")
def get_game(request: Request, game_id: int, db: Session = Depends(get_db)) -> GameOut:
    game = db.get(models.Game, game_id)
    if game is None:
        raise HTTPException(404, "Игра не найдена")
    return _game_to_out(game)


@router.put("/games/{game_id}", response_model=GameOut)
@limiter.limit("30/minute")
def update_game(request: Request, game_id: int, data: GameUpdate, db: Session = Depends(get_db)) -> GameOut:
    game = db.get(models.Game, game_id)
    if game is None:
        raise HTTPException(404, "Игра не найдена")
    try:
        game = game_service.update_rated_game(
            db,
            game=game,
            starts_at=data.starts_at,
            location=data.location,
            game_type=data.game_type,
            tournament_id=data.tournament_id,
            stage_id=data.stage_id,
            result=data.result,
            notes=data.notes,
            participants=_to_participant_inputs(data.participants) if data.participants is not None else None,
            allow_roster_change=data.allow_roster_change,
        )
        db.commit()
    except GameValidationError as exc:
        db.rollback()
        raise HTTPException(422, exc.message) from exc
    # Дату игры правят прямо здесь, а вместе с датой меняется и её место в
    # нумерации.
    game = game_service.resequence_and_reload(db, game_ids=[game.id])[0]
    return _game_to_out(game)


@router.delete("/games/{game_id}")
@limiter.limit("30/minute")
def delete_game(request: Request, game_id: int, db: Session = Depends(get_db)) -> dict:
    game = db.get(models.Game, game_id)
    if game is None:
        raise HTTPException(404, "Игра не найдена")
    game_service.delete_game(db, game=game)
    db.commit()
    # Удаление не оставляет дыру в нумерации: все игры после удалённой
    # сдвигаются на номер назад.
    game_service.resequence_and_reload(db, game_ids=[])
    return {"ok": True}


def _tournament_to_out(tournament: models.Tournament, games_count: int) -> TournamentAdminOut:
    out = TournamentAdminOut.model_validate(tournament)
    out.games_count = games_count
    return out


@router.get("/tournaments", response_model=list[TournamentAdminOut])
@limiter.limit("30/minute")
def list_tournaments(request: Request, db: Session = Depends(get_db)) -> list[TournamentAdminOut]:
    counts = tournament_service.games_count_map(db)
    return [
        _tournament_to_out(t, counts.get(t.id, 0))
        for t in tournament_service.list_tournaments(db)
    ]


@router.post("/tournaments", response_model=TournamentAdminOut)
@limiter.limit("30/minute")
def create_tournament(request: Request, data: TournamentCreate, db: Session = Depends(get_db)) -> TournamentAdminOut:
    try:
        tournament = tournament_service.create_tournament(db, **data.model_dump())
        db.commit()
    except TournamentValidationError as exc:
        db.rollback()
        raise HTTPException(422, exc.message) from exc
    db.refresh(tournament)
    return _tournament_to_out(tournament, 0)


# Объявлен до /tournaments/{tournament_id}: иначе "slug-suggestion" уедет в
# path-параметр и не смэтчится как int.
@router.get("/tournaments/slug-suggestion")
@limiter.limit("30/minute")
def suggest_tournament_slug(request: Request, name: str, db: Session = Depends(get_db)) -> dict:
    # scope='tournament': свободным slug должен быть среди ТУРНИРОВ, а не
    # среди игроков -- это разные пространства имён (/mafia/tournaments/[slug]
    # против /mafia/[slug]). См. slug_service.suggest_slug.
    return {"slug": slug_service.suggest_slug(name, db, scope="tournament")}


@router.get("/tournaments/{tournament_id}", response_model=TournamentAdminOut)
@limiter.limit("30/minute")
def get_tournament(request: Request, tournament_id: int, db: Session = Depends(get_db)) -> TournamentAdminOut:
    tournament = db.get(models.Tournament, tournament_id)
    if tournament is None:
        raise HTTPException(404, "Турнир не найден")
    return _tournament_to_out(tournament, tournament_service.games_count_map(db).get(tournament.id, 0))


@router.put("/tournaments/{tournament_id}", response_model=TournamentAdminOut)
@limiter.limit("30/minute")
def update_tournament(
    request: Request, tournament_id: int, data: TournamentUpdate, db: Session = Depends(get_db)
) -> TournamentAdminOut:
    tournament = db.get(models.Tournament, tournament_id)
    if tournament is None:
        raise HTTPException(404, "Турнир не найден")
    try:
        tournament = tournament_service.update_tournament(
            db, tournament=tournament, **data.model_dump(exclude_unset=True)
        )
        db.commit()
    except TournamentValidationError as exc:
        db.rollback()
        raise HTTPException(422, exc.message) from exc
    db.refresh(tournament)
    return _tournament_to_out(tournament, tournament_service.games_count_map(db).get(tournament.id, 0))


@router.delete("/tournaments/{tournament_id}")
@limiter.limit("30/minute")
def delete_tournament(request: Request, tournament_id: int, db: Session = Depends(get_db)) -> dict:
    tournament = db.get(models.Tournament, tournament_id)
    if tournament is None:
        raise HTTPException(404, "Турнир не найден")
    try:
        tournament_service.delete_tournament(db, tournament=tournament)
        db.commit()
    except TournamentValidationError as exc:
        db.rollback()
        raise HTTPException(422, exc.message) from exc
    # Вместе с турниром удаляются его неоценённые слоты -- нумерацию сжимаем.
    game_service.resequence_and_reload(db, game_ids=[])
    return {"ok": True}


@router.get("/tournaments/{tournament_id}/games", response_model=list[TournamentStageGameOut])
@limiter.limit("30/minute")
def list_flat_tournament_games(
    request: Request, tournament_id: int, db: Session = Depends(get_db)
) -> list[TournamentStageGameOut]:
    """Слоты турнира без этапа -- для простого турнира (≤10 участников) без
    сетки. Как только у турнира завели этап, новые игры создаются уже там
    (см. list_stage_games), а эта ручка остаётся показывать то, что было
    добавлено до появления сеток."""
    _get_tournament_or_404(db, tournament_id)
    games = tournament_service.list_tournament_games(db, tournament_id=tournament_id)
    return [TournamentStageGameOut.model_validate(g) for g in games]


@router.post("/tournaments/{tournament_id}/games", response_model=list[TournamentStageGameOut])
@limiter.limit("30/minute")
def add_flat_tournament_games(
    request: Request,
    tournament_id: int,
    data: AddStageGamesIn,
    db: Session = Depends(get_db),
    actor: models.Player = Depends(require_site_admin),
) -> list[TournamentStageGameOut]:
    tournament = _get_tournament_or_404(db, tournament_id)
    games = tournament_service.add_tournament_games(db, tournament=tournament, count=data.count, created_by=actor.id)
    db.commit()
    games = game_service.resequence_and_reload(db, game_ids=[g.id for g in games])
    return [TournamentStageGameOut.model_validate(g) for g in games]


# ===================== Этапы турнира (сетка) =====================


def _get_tournament_or_404(db: Session, tournament_id: int) -> models.Tournament:
    tournament = db.get(models.Tournament, tournament_id)
    if tournament is None:
        raise HTTPException(404, "Турнир не найден")
    return tournament


def _get_stage_or_404(db: Session, tournament_id: int, stage_id: int) -> models.TournamentStage:
    stage = tournament_service.get_stage(db, stage_id=stage_id)
    if stage is None or stage.tournament_id != tournament_id:
        raise HTTPException(404, "Этап не найден")
    return stage


def _stage_to_out(stage: models.TournamentStage, games_count: int = 0) -> TournamentStageOut:
    return TournamentStageOut(
        id=stage.id, tournament_id=stage.tournament_id, name=stage.name, order=stage.order,
        is_final=stage.is_final, games_count=games_count,
    )



@router.get("/tournaments/{tournament_id}/stages", response_model=list[TournamentStageOut])
@limiter.limit("30/minute")
def list_tournament_stages(request: Request, tournament_id: int, db: Session = Depends(get_db)) -> list[TournamentStageOut]:
    _get_tournament_or_404(db, tournament_id)
    stages = tournament_service.list_stages(db, tournament_id=tournament_id)
    counts: dict[int, int] = {}
    for stage in stages:
        counts[stage.id] = (
            db.query(models.Game).filter(models.Game.stage_id == stage.id, models.Game.status == "rated").count()
        )
    return [_stage_to_out(s, counts.get(s.id, 0)) for s in stages]


@router.post("/tournaments/{tournament_id}/stages", response_model=TournamentStageOut)
@limiter.limit("30/minute")
def create_tournament_stage(
    request: Request,
    tournament_id: int,
    data: TournamentStageCreate,
    db: Session = Depends(get_db),
    actor: models.Player = Depends(require_site_admin),
) -> TournamentStageOut:
    _get_tournament_or_404(db, tournament_id)
    try:
        stage = tournament_service.create_stage(
            db, tournament_id=tournament_id, created_by=actor.id, **data.model_dump()
        )
        db.commit()
    except TournamentValidationError as exc:
        db.rollback()
        raise HTTPException(422, exc.message) from exc
    db.refresh(stage)
    # Только что созданные слоты не оценены -- games_count тут исторически
    # значит "оценённых игр", как и везде в этом файле (см. list_tournament_stages).
    return _stage_to_out(stage, 0)


@router.put("/tournaments/{tournament_id}/stages/{stage_id}", response_model=TournamentStageOut)
@limiter.limit("30/minute")
def update_tournament_stage(
    request: Request, tournament_id: int, stage_id: int, data: TournamentStageUpdate, db: Session = Depends(get_db)
) -> TournamentStageOut:
    stage = _get_stage_or_404(db, tournament_id, stage_id)
    try:
        stage = tournament_service.update_stage(db, stage=stage, **data.model_dump(exclude_unset=True))
        db.commit()
    except TournamentValidationError as exc:
        db.rollback()
        raise HTTPException(422, exc.message) from exc
    db.refresh(stage)
    games_count = db.query(models.Game).filter(models.Game.stage_id == stage.id, models.Game.status == "rated").count()
    return _stage_to_out(stage, games_count)


@router.delete("/tournaments/{tournament_id}/stages/{stage_id}")
@limiter.limit("30/minute")
def delete_tournament_stage(request: Request, tournament_id: int, stage_id: int, db: Session = Depends(get_db)) -> dict:
    stage = _get_stage_or_404(db, tournament_id, stage_id)
    try:
        tournament_service.delete_stage(db, stage=stage)
        db.commit()
    except TournamentValidationError as exc:
        db.rollback()
        raise HTTPException(422, exc.message) from exc
    # То же, что и при удалении турнира: этап уносит с собой пустые слоты.
    game_service.resequence_and_reload(db, game_ids=[])
    return {"ok": True}


@router.get(
    "/tournaments/{tournament_id}/stages/{stage_id}/games",
    response_model=list[TournamentStageGameOut],
)
@limiter.limit("30/minute")
def list_stage_games(
    request: Request, tournament_id: int, stage_id: int, db: Session = Depends(get_db)
) -> list[TournamentStageGameOut]:
    """Список игровых слотов этапа для панели админки: и уже оценённые
    (status='rated', есть result), и ещё пустые -- их оценивают через общую
    ручку PUT /admin/games/{id} (та же форма, что и для игр бота)."""
    _get_stage_or_404(db, tournament_id, stage_id)
    games = tournament_service.list_stage_games(db, stage_id=stage_id)
    return [TournamentStageGameOut.model_validate(g) for g in games]


@router.post(
    "/tournaments/{tournament_id}/stages/{stage_id}/games",
    response_model=list[TournamentStageGameOut],
)
@limiter.limit("30/minute")
def add_stage_games(
    request: Request,
    tournament_id: int,
    stage_id: int,
    data: AddStageGamesIn,
    db: Session = Depends(get_db),
    actor: models.Player = Depends(require_site_admin),
) -> list[TournamentStageGameOut]:
    """Донабрать ещё слотов в уже созданный этап -- когда изначального числа
    игр не хватило (см. пояснение пользователя: "можно добавить/удалить
    позже")."""
    stage = _get_stage_or_404(db, tournament_id, stage_id)
    games = tournament_service.add_stage_games(db, stage=stage, count=data.count, created_by=actor.id)
    db.commit()
    games = game_service.resequence_and_reload(db, game_ids=[g.id for g in games])
    return [TournamentStageGameOut.model_validate(g) for g in games]


@router.get(
    "/tournaments/{tournament_id}/stages/{stage_id}/standings",
    response_model=list[TournamentStandingOut],
)
@limiter.limit("30/minute")
def get_stage_standings(
    request: Request, tournament_id: int, stage_id: int, db: Session = Depends(get_db)
) -> list[TournamentStandingOut]:
    """Сводная таблица этапа для админки -- то же, что видно на публичной
    странице турнира, плюс уже проставленные отметки прохода (чтобы форма
    отметки открывалась с текущим состоянием, а не с чистого листа)."""
    stage = _get_stage_or_404(db, tournament_id, stage_id)
    rows = stats_service.tournament_standings(db, tournament_id=tournament_id, stage_id=stage.id)
    advanced_ids = tournament_service.get_stage_advances(db, stage_id=stage.id)
    return serializers.standing_rows_to_out(rows, advanced_ids)


@router.put("/tournaments/{tournament_id}/stages/{stage_id}/advances", response_model=TournamentStageAdvancesOut)
@limiter.limit("30/minute")
def set_stage_advances(
    request: Request, tournament_id: int, stage_id: int, data: TournamentStageAdvancesIn, db: Session = Depends(get_db)
) -> TournamentStageAdvancesOut:
    """Заменяет разом весь список прошедших дальше по итогам этапа. Никакого
    автоматического правила прохода нет -- список выбирает администратор
    вручную, глядя на сводную таблицу этапа (см. ARCHITECTURE.md)."""
    stage = _get_stage_or_404(db, tournament_id, stage_id)
    valid_ids = {
        pid for (pid,) in db.query(models.Player.id).filter(models.Player.id.in_(data.player_ids)).all()
    }
    unknown = set(data.player_ids) - valid_ids
    if unknown:
        raise HTTPException(422, f"Неизвестные игроки: {sorted(unknown)}")
    tournament_service.set_stage_advances(db, stage_id=stage.id, player_ids=valid_ids)
    db.commit()
    return TournamentStageAdvancesOut(player_ids=sorted(valid_ids))


@router.get("/players", response_model=list[PlayerAdminOut])
@limiter.limit("30/minute")
def list_players(request: Request, db: Session = Depends(get_db)) -> list[models.Player]:
    return db.query(models.Player).order_by(models.Player.nickname.asc()).all()


@router.post("/players", response_model=PlayerAdminOut)
@limiter.limit("30/minute")
def create_player(request: Request, data: PlayerCreate, db: Session = Depends(get_db)) -> models.Player:
    try:
        player = player_service.create_player(db, **data.model_dump())
        db.commit()
    except PlayerValidationError as exc:
        db.rollback()
        raise HTTPException(422, exc.message) from exc
    db.refresh(player)
    return player


@router.get("/players/slug-suggestion")
@limiter.limit("30/minute")
def suggest_slug(request: Request, nickname: str, db: Session = Depends(get_db)) -> dict:
    return {"slug": slug_service.suggest_slug(nickname, db)}


@router.get("/players/pending", response_model=list[PendingPlayerOut])
@limiter.limit("30/minute")
def list_pending_players(request: Request, db: Session = Depends(get_db)) -> list[models.Player]:
    """Заявки из бота, ждущие решения админа.

    Экрана под это на сайте больше нет: решение принимается в Telegram,
    кнопками под уведомлением бота (раздел 3.8). Ручка осталась аварийным
    доступом к очереди -- уведомление можно удалить из чата, и другого способа
    увидеть незакрытые заявки тогда не остаётся.
    """
    return player_confirmation_service.list_pending(db)


@router.post("/players/{player_id}/confirm", response_model=PlayerAdminOut)
@limiter.limit("30/minute")
def confirm_player(request: Request, player_id: int, db: Session = Depends(get_db)) -> models.Player:
    player = db.get(models.Player, player_id)
    if player is None:
        raise HTTPException(404, "Игрок не найден")
    try:
        player_confirmation_service.confirm(db, player=player)
        db.commit()
    except ConfirmationError as exc:
        db.rollback()
        raise HTTPException(422, exc.message) from exc
    db.refresh(player)
    return player


@router.post("/players/{player_id}/reject", response_model=PlayerAdminOut)
@limiter.limit("30/minute")
def reject_player(
    request: Request, player_id: int, data: PlayerRejectIn, db: Session = Depends(get_db)
) -> models.Player:
    player = db.get(models.Player, player_id)
    if player is None:
        raise HTTPException(404, "Игрок не найден")
    try:
        player_confirmation_service.reject(db, player=player, reason=data.reason)
        db.commit()
    except ConfirmationError as exc:
        db.rollback()
        raise HTTPException(422, exc.message) from exc
    db.refresh(player)
    return player


def _profile_change_out(change: models.PlayerProfileChange) -> ProfileChangeOut:
    return ProfileChangeOut(
        id=change.id,
        player_id=change.player_id,
        player_nickname=change.player.nickname,
        player_slug=change.player.slug,
        telegram_username=change.player.telegram_username,
        field=change.field,
        field_label=profile_change_service.FIELD_LABELS.get(change.field, change.field),
        current_value=profile_change_service.current_value(change.player, change.field),
        new_value=change.new_value,
        created_at=change.created_at,
    )


@router.get("/players/profile-changes", response_model=list[ProfileChangeOut])
@limiter.limit("30/minute")
def list_profile_changes(request: Request, db: Session = Depends(get_db)) -> list[ProfileChangeOut]:
    """Правки профилей из бота, ждущие решения.

    Как и очередь заявок выше -- без экрана на сайте, аварийным доступом.
    """
    return [_profile_change_out(change) for change in profile_change_service.list_pending(db)]


@router.post("/players/profile-changes/{change_id}/apply", response_model=PlayerAdminOut)
@limiter.limit("30/minute")
def apply_profile_change(request: Request, change_id: int, db: Session = Depends(get_db)) -> models.Player:
    change = db.get(models.PlayerProfileChange, change_id)
    if change is None:
        raise HTTPException(404, "Правка не найдена")
    try:
        profile_change_service.apply(db, change=change)
        db.commit()
    except ProfileChangeError as exc:
        db.rollback()
        raise HTTPException(422, exc.message) from exc
    db.refresh(change.player)
    return change.player


@router.post("/players/profile-changes/{change_id}/reject", response_model=PlayerAdminOut)
@limiter.limit("30/minute")
def reject_profile_change(
    request: Request, change_id: int, data: ProfileChangeRejectIn, db: Session = Depends(get_db)
) -> models.Player:
    change = db.get(models.PlayerProfileChange, change_id)
    if change is None:
        raise HTTPException(404, "Правка не найдена")
    try:
        profile_change_service.reject(db, change=change, reason=data.reason)
        db.commit()
    except ProfileChangeError as exc:
        db.rollback()
        raise HTTPException(422, exc.message) from exc
    db.refresh(change.player)
    return change.player


@router.get("/players/{player_id}", response_model=PlayerAdminOut)
@limiter.limit("30/minute")
def get_player(request: Request, player_id: int, db: Session = Depends(get_db)) -> models.Player:
    player = db.get(models.Player, player_id)
    if player is None:
        raise HTTPException(404, "Игрок не найден")
    return player


@router.put("/players/{player_id}", response_model=PlayerAdminOut)
@limiter.limit("30/minute")
def update_player(request: Request, player_id: int, data: PlayerUpdate, db: Session = Depends(get_db)) -> models.Player:
    player = db.get(models.Player, player_id)
    if player is None:
        raise HTTPException(404, "Игрок не найден")
    try:
        # exclude_unset: отличаем «поле не прислали» от «прислали null».
        # Второе -- осознанная очистка поля в форме, и она должна сохраниться
        # (см. player_service.update_player).
        player = player_service.update_player(db, player=player, **data.model_dump(exclude_unset=True))
        db.commit()
    except PlayerValidationError as exc:
        db.rollback()
        raise HTTPException(422, exc.message) from exc
    db.refresh(player)
    return player


@router.delete("/players/{player_id}")
@limiter.limit("30/minute")
def delete_player(request: Request, player_id: int, db: Session = Depends(get_db)) -> dict:
    player = db.get(models.Player, player_id)
    if player is None:
        raise HTTPException(404, "Игрок не найден")
    status_ = player_service.delete_player(db, player=player)
    db.commit()
    return {"status": status_}


@router.post("/players/{player_id}/photo")
@limiter.limit("30/minute")
async def upload_photo(request: Request, player_id: int, file: UploadFile, db: Session = Depends(get_db)) -> dict:
    player = db.get(models.Player, player_id)
    if player is None:
        raise HTTPException(404, "Игрок не найден")
    raw = await file.read()
    try:
        photo_url = player_service.save_player_photo(db, player=player, raw_bytes=raw)
        db.commit()
    except PlayerValidationError as exc:
        db.rollback()
        raise HTTPException(422, exc.message) from exc
    return {"photo_url": photo_url}


@router.post("/players/{player_id}/site-access", response_model=SiteAccessGrantOut)
@limiter.limit("30/minute")
def grant_site_access(request: Request, player_id: int, username: str, db: Session = Depends(get_db)) -> SiteAccessGrantOut:
    player = db.get(models.Player, player_id)
    if player is None:
        raise HTTPException(404, "Игрок не найден")
    try:
        temp_password = player_service.grant_site_access(db, player=player, username=username)
        db.commit()
    except PlayerValidationError as exc:
        db.rollback()
        raise HTTPException(422, exc.message) from exc
    return SiteAccessGrantOut(site_username=player.site_username, temp_password=temp_password)


@router.delete("/players/{player_id}/site-access")
@limiter.limit("30/minute")
def revoke_site_access(request: Request, player_id: int, db: Session = Depends(get_db)) -> dict:
    player = db.get(models.Player, player_id)
    if player is None:
        raise HTTPException(404, "Игрок не найден")
    player_service.revoke_site_access(db, player=player)
    db.commit()
    return {"ok": True}


@router.get("/bot-admins", response_model=list[PlayerAdminOut])
@limiter.limit("30/minute")
def list_bot_admins(request: Request, db: Session = Depends(get_db)) -> list[models.Player]:
    return db.query(models.Player).filter(models.Player.is_bot_admin.is_(True)).all()


@router.post("/bot-admins")
@limiter.limit("30/minute")
def add_bot_admin(
    request: Request, telegram_id: int | None = None, username: str | None = None, db: Session = Depends(get_db)
) -> dict:
    try:
        return admin_grant.grant_bot_admin(db, telegram_id=telegram_id, username=username)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.delete("/bot-admins/{player_id}")
@limiter.limit("30/minute")
def remove_bot_admin(request: Request, player_id: int, db: Session = Depends(get_db)) -> dict:
    player = db.get(models.Player, player_id)
    if player is None:
        raise HTTPException(404, "Игрок не найден")
    player_service.set_bot_admin(db, player=player, is_admin=False)
    db.commit()
    return {"ok": True}


@router.get("/pass-list", response_model=PassListOut)
@limiter.limit("30/minute")
def get_pass_list(request: Request, db: Session = Depends(get_db)) -> PassListOut:
    """ФИО тех, кому нужен пропуск на текущую пропускную неделю.

    Коммит здесь есть намеренно: settings_service может лениво создать строку
    настроек, если базу чистили в обход миграции.
    """
    result = pass_list_service.build_pass_list(db)
    db.commit()
    return PassListOut(
        week_start=result.week_start,
        week_end=result.week_end,
        rollover_weekday=result.rollover_weekday,
        rollover_time=result.rollover_time,
        entries=[
            PassListEntryOut(
                player_id=entry.player_id,
                nickname=entry.nickname,
                full_name=entry.full_name,
                phone=entry.phone,
                confirmation_status=entry.confirmation_status,
                games=[
                    PassListGameOut(
                        game_id=game.game_id,
                        starts_at=game.starts_at,
                        game_type=game.game_type,
                        location=game.location,
                        role=game.role,
                    )
                    for game in entry.games
                ],
            )
            for entry in result.entries
        ],
    )


@router.get("/settings/pass-week", response_model=PassWeekSettingsOut)
@limiter.limit("30/minute")
def get_pass_week_settings(request: Request, db: Session = Depends(get_db)) -> models.ClubSettings:
    settings = settings_service.get_settings(db)
    db.commit()
    return settings


@router.put("/settings/pass-week", response_model=PassWeekSettingsOut)
@limiter.limit("30/minute")
def update_pass_week_settings(
    request: Request, data: PassWeekSettingsIn, db: Session = Depends(get_db)
) -> models.ClubSettings:
    settings = settings_service.update_settings(
        db,
        pass_week_rollover_weekday=data.pass_week_rollover_weekday,
        pass_week_rollover_time=data.pass_week_rollover_time,
    )
    db.commit()
    db.refresh(settings)
    return settings
