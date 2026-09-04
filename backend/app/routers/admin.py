from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.deps import require_site_admin
from app.rate_limit import limiter
from app.schemas.game import GameCreate, GameListItem, GameOut, GameUpdate, ParticipantOut
from app.schemas.player import (
    PlayerAdminOut,
    PlayerCreate,
    PlayerUpdate,
    SiteAccessGrantOut,
)
from app.services import admin_grant, game_service, player_service, slug_service
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


def _game_to_out(game: models.Game) -> GameOut:
    participants = sorted(game.participants, key=lambda p: p.seat_number)
    return GameOut(
        id=game.id,
        starts_at=game.starts_at,
        location=game.location,
        game_type=game.game_type,
        status=game.status,
        result=game.result,
        notes=game.notes,
        participants=[
            ParticipantOut(
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
            for p in participants
        ],
    )


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
            result=data.result,
            notes=data.notes,
            created_by=actor.id,
            participants=_to_participant_inputs(data.participants),
        )
        db.commit()
    except GameValidationError as exc:
        db.rollback()
        raise HTTPException(422, exc.message) from exc
    db.refresh(game)
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
            result=data.result,
            notes=data.notes,
            participants=_to_participant_inputs(data.participants) if data.participants is not None else None,
        )
        db.commit()
    except GameValidationError as exc:
        db.rollback()
        raise HTTPException(422, exc.message) from exc
    db.refresh(game)
    return _game_to_out(game)


@router.delete("/games/{game_id}")
@limiter.limit("30/minute")
def delete_game(request: Request, game_id: int, db: Session = Depends(get_db)) -> dict:
    game = db.get(models.Game, game_id)
    if game is None:
        raise HTTPException(404, "Игра не найдена")
    game_service.delete_game(db, game=game)
    db.commit()
    return {"ok": True}


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
        player = player_service.update_player(db, player=player, **data.model_dump())
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
