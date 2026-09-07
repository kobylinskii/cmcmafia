from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.deps import get_bot_actor, require_bot_service
from app.rate_limit import limiter
from app.textmatch import ci_equals
from app.serializers import is_session_open, roster_to_out, session_to_out
from app.timeutil import club_day
from app.schemas.bot import (
    BotPlayerProfileOut,
    BotPlayerProfileUpdateIn,
    BotPlayerStatsOut,
    BotPlayerRegisterIn,
    MyRegistrationOut,
    RegisterIn,
    RegistrationOut,
    ReserveIn,
    RosterOut,
    SessionOut,
)
from app.schemas.club import (
    AdminProfileChangeNoticeOut,
    AdminRegistrationNoticeOut,
    BotAdminNotificationsAckIn,
    BotAdminNotificationsOut,
    BotConfirmationAckIn,
    BotConfirmationNotificationOut,
    BotProfileChangeAckIn,
    BotProfileChangeNotificationOut,
)
from app.services import (
    admin_grant,
    admin_notification_service,
    bootstrap_admin_service,
    player_confirmation_service,
    profile_change_service,
    registration_service,
    slug_service,
    stats_service,
)
from app.services.player_confirmation_service import ConfirmationError
from app.services.profile_change_service import ProfileChangeError
from app.services.registration_service import RegistrationError

router = APIRouter(prefix="/api/bot", tags=["bot"])

# Поля профиля, которые PUT не имеет права обнулить: их собирает регистрация,
# и пустыми они делают профиль неполным (а ФИО со статусом прохода -- ещё и
# бесполезным для списка пропусков).
_NON_CLEARABLE_PROFILE_FIELDS = frozenset(
    {"nickname", "salutation", "full_name", "affiliation", "can_play", "can_staff"}
)


def _profile_out(db: Session, player: models.Player) -> BotPlayerProfileOut:
    """Профиль + то, что по нему ждёт решения админа.

    Значения полей остаются прежними до применения правки: в этом и смысл
    модерации (см. app/services/profile_change_service.py).
    """
    out = BotPlayerProfileOut.model_validate(player, from_attributes=True)
    out.pending_changes = {
        change.field: change.new_value
        for change in profile_change_service.pending_for_player(db, player_id=player.id)
    }
    return out


@router.post("/players/register", response_model=BotPlayerProfileOut)
@limiter.limit("20/minute")
def register_player(
    request: Request, data: BotPlayerRegisterIn, db: Session = Depends(get_db), _: None = Depends(require_bot_service)
) -> BotPlayerProfileOut:
    if db.query(models.Player).filter(models.Player.telegram_id == data.telegram_id).first():
        raise HTTPException(409, "Этот Telegram-аккаунт уже зарегистрирован")
    if db.query(models.Player).filter(ci_equals(models.Player.nickname, data.nickname)).first():
        raise HTTPException(409, "Ник уже занят")
    # players.phone UNIQUE: без явной проверки повторный номер долетал до
    # констрейнта и возвращал 500 вместо понятного отказа. Случай не
    # экзотический -- так выглядит попытка завести второй аккаунт на тот же
    # телефон после смены Telegram.
    if data.phone and db.query(models.Player).filter(models.Player.phone == data.phone).first():
        raise HTTPException(409, "Этот номер телефона уже зарегистрирован")

    slug = slug_service.suggest_slug(data.nickname, db)
    player = models.Player(
        telegram_id=data.telegram_id,
        telegram_username=data.telegram_username,
        phone=data.phone,
        nickname=data.nickname,
        slug=slug,
        salutation=data.salutation,
        full_name=data.full_name,
        affiliation=data.affiliation,
        can_play=data.can_play,
        can_staff=data.can_staff,
        # Регистрация в боте открыта кому угодно, поэтому новичок ждёт решения
        # админа: на сайте его пока не видно (см. models.ConfirmationStatus),
        # записываться на игры он при этом может сразу.
        confirmation_status=models.ConfirmationStatus.pending.value,
    )
    db.add(player)
    db.flush()
    admin_grant.consume_pending_admin(db, player=player)
    bootstrap_admin_service.maybe_grant_bootstrap_admin(db, player=player)
    if player.is_bot_admin:
        # Админа клуба некому и незачем подтверждать: права ему дали либо
        # приглашением по @username от действующего админа, либо bootstrap'ом
        # из конфига -- обе проверки строже, чем ручное подтверждение заявки.
        player.confirmation_status = models.ConfirmationStatus.confirmed.value
    db.commit()
    db.refresh(player)
    return _profile_out(db, player)


@router.get("/players/me", response_model=BotPlayerProfileOut)
@limiter.limit("20/minute")
def get_my_profile(
    request: Request,
    telegram_username: str | None = None,
    db: Session = Depends(get_db),
    actor: models.Player = Depends(get_bot_actor),
) -> BotPlayerProfileOut:
    # Оппортунистическая синхронизация username при каждом /start — телеграм
    # не уведомляет бэкенд о смене username, поэтому бот просто присылает
    # текущее значение при каждом обращении. Заодно переоцениваем bootstrap-права
    # (см. bootstrap_admin_service) — конфиг мог измениться после регистрации игрока.
    changed = False
    if telegram_username is not None and telegram_username != actor.telegram_username:
        actor.telegram_username = telegram_username
        changed = True
    if admin_grant.consume_pending_admin(db, player=actor):
        changed = True
    if bootstrap_admin_service.maybe_grant_bootstrap_admin(db, player=actor):
        changed = True
    if changed:
        db.commit()
        db.refresh(actor)
    return _profile_out(db, actor)


@router.put("/players/me", response_model=BotPlayerProfileOut)
@limiter.limit("20/minute")
def update_my_profile(
    request: Request,
    data: BotPlayerProfileUpdateIn,
    db: Session = Depends(get_db),
    actor: models.Player = Depends(get_bot_actor),
) -> BotPlayerProfileOut:
    """Правка профиля из бота.

    Поля свободного ввода подтверждённого игрока сохраняются не сразу: они
    уходят в очередь на проверку админу, а в профиле остаётся прежнее
    значение. Кнопочные поля (обращение, статус прохода, роли, любимая роль)
    применяются немедленно -- варианты в них задаёт сам бот.
    """
    if data.nickname and data.nickname.lower() != actor.nickname.lower():
        if db.query(models.Player).filter(ci_equals(models.Player.nickname, data.nickname)).first():
            raise HTTPException(409, "Ник уже занят")

    # exclude_unset отличает «поле не прислали» от «прислали null»: второе --
    # осознанная очистка анкетного поля («убрать из профиля возраст»), и она
    # должна сохраниться. Поля из NON_CLEARABLE обнулить нельзя: без них
    # профиль перестаёт быть валидным.
    for field, value in data.model_dump(exclude_unset=True).items():
        if value is None and field in _NON_CLEARABLE_PROFILE_FIELDS:
            continue
        if profile_change_service.requires_moderation(actor, field):
            try:
                profile_change_service.submit(db, player=actor, field=field, value=value)
            except ProfileChangeError as exc:
                db.rollback()
                raise HTTPException(409, exc.message) from exc
            continue
        setattr(actor, field, value)
    db.commit()
    db.refresh(actor)
    return _profile_out(db, actor)


@router.get("/players/me/stats", response_model=BotPlayerStatsOut)
@limiter.limit("20/minute")
def get_my_stats(
    request: Request, db: Session = Depends(get_db), actor: models.Player = Depends(get_bot_actor)
) -> BotPlayerStatsOut:
    """Свою статистику игрок видит независимо от модерации: скрытие касается
    публичной части сайта, а не собственной карточки в боте."""
    stats = stats_service.compute_player_stats(db, actor.id)
    return BotPlayerStatsOut(
        total_games=stats.total_games,
        wins=stats.wins,
        win_rate=stats.win_rate,
        rating=stats.rating,
        rating_games_count=stats.rating_games_count,
        rank=stats.rank,
    )


@router.post("/players/me/resubmit", response_model=BotPlayerProfileOut)
@limiter.limit("20/minute")
def resubmit_my_profile(
    request: Request, db: Session = Depends(get_db), actor: models.Player = Depends(get_bot_actor)
) -> BotPlayerProfileOut:
    """Отклонённый игрок поправил анкету и просит проверить заново."""
    try:
        player_confirmation_service.resubmit(db, player=actor)
        db.commit()
    except ConfirmationError as exc:
        db.rollback()
        raise HTTPException(409, exc.message) from exc
    db.refresh(actor)
    return _profile_out(db, actor)


@router.get("/players/confirmation-notifications", response_model=list[BotConfirmationNotificationOut])
@limiter.limit("60/minute")
def list_confirmation_notifications(
    request: Request, db: Session = Depends(get_db), _: None = Depends(require_bot_service)
) -> list[models.Player]:
    """Очередь решений админа, о которых игрок ещё не знает.

    Бэкенд сам в Telegram не пишет -- токен бота живёт только в боте, и
    заводить его второй копией в API ради одного сообщения значит расширять
    поверхность утечки. Поэтому доставка устроена опросом: бот забирает
    очередь, рассылает и подтверждает ack'ом (ниже).
    """
    return player_confirmation_service.pending_notifications(db)


@router.post("/players/confirmation-notifications/ack")
@limiter.limit("60/minute")
def ack_confirmation_notifications(
    request: Request,
    data: BotConfirmationAckIn,
    db: Session = Depends(get_db),
    _: None = Depends(require_bot_service),
) -> dict:
    marked = player_confirmation_service.mark_notified(db, player_ids=data.player_ids)
    db.commit()
    return {"marked": marked}


@router.get(
    "/players/profile-change-notifications", response_model=list[BotProfileChangeNotificationOut]
)
@limiter.limit("60/minute")
def list_profile_change_notifications(
    request: Request, db: Session = Depends(get_db), _: None = Depends(require_bot_service)
) -> list[BotProfileChangeNotificationOut]:
    """Решения по правкам профиля, о которых игрок ещё не знает.

    Очередь отдельная от решений по заявкам: сообщения разные, и подтверждать
    доставку надо независимо -- иначе одно недоставленное решение держало бы
    второе.
    """
    return [
        BotProfileChangeNotificationOut(
            change_id=change.id,
            telegram_id=change.player.telegram_id,
            field_label=profile_change_service.FIELD_LABELS.get(change.field, change.field),
            new_value=change.new_value,
            status=change.status,
            rejection_reason=change.rejection_reason,
        )
        for change in profile_change_service.pending_notifications(db)
    ]


@router.post("/players/profile-change-notifications/ack")
@limiter.limit("60/minute")
def ack_profile_change_notifications(
    request: Request,
    data: BotProfileChangeAckIn,
    db: Session = Depends(get_db),
    _: None = Depends(require_bot_service),
) -> dict:
    marked = profile_change_service.mark_notified(db, change_ids=data.change_ids)
    db.commit()
    return {"marked": marked}


@router.get("/admin-notifications", response_model=BotAdminNotificationsOut)
@limiter.limit("60/minute")
def list_admin_notifications(
    request: Request, db: Session = Depends(get_db), _: None = Depends(require_bot_service)
) -> BotAdminNotificationsOut:
    """Что появилось на проверку и кому из админов сайта об этом написать.

    Зеркало очередей решений выше: там сайт копит решения, бот разносит их
    игрокам; здесь бот копит новые pending-строки и разносит их админам.
    Бэкенд в Telegram не пишет -- токен бота живёт только в боте.
    """
    return BotAdminNotificationsOut(
        recipients=[p.telegram_id for p in admin_notification_service.admin_recipients(db)],
        registrations=[
            AdminRegistrationNoticeOut(
                player_id=player.id,
                nickname=player.nickname,
                full_name=player.full_name,
                affiliation=player.affiliation,
                telegram_username=player.telegram_username,
                created_at=player.created_at,
            )
            for player in admin_notification_service.pending_registrations(db)
        ],
        profile_changes=[
            AdminProfileChangeNoticeOut(
                change_id=change.id,
                player_nickname=change.player.nickname,
                telegram_username=change.player.telegram_username,
                field_label=profile_change_service.FIELD_LABELS.get(change.field, change.field),
                current_value=profile_change_service.current_value(change.player, change.field),
                new_value=change.new_value,
                created_at=change.created_at,
            )
            for change in admin_notification_service.pending_profile_changes(db)
        ],
    )


@router.post("/admin-notifications/ack")
@limiter.limit("60/minute")
def ack_admin_notifications(
    request: Request,
    data: BotAdminNotificationsAckIn,
    db: Session = Depends(get_db),
    _: None = Depends(require_bot_service),
) -> dict:
    marked_registrations = admin_notification_service.mark_registrations_notified(
        db, player_ids=data.registration_player_ids
    )
    marked_profile_changes = admin_notification_service.mark_profile_changes_notified(
        db, change_ids=data.profile_change_ids
    )
    db.commit()
    return {
        "marked_registrations": marked_registrations,
        "marked_profile_changes": marked_profile_changes,
    }


@router.get("/game-days")
@limiter.limit("20/minute")
def list_game_days(
    request: Request,
    telegram_id: int,
    game_type: str | None = None,
    db: Session = Depends(get_db),
    actor: models.Player = Depends(get_bot_actor),
) -> list[str]:
    sessions = registration_service.list_open_sessions(db, game_type=game_type, exclude_player_id=actor.id)
    days = sorted({club_day(s.starts_at) for s in sessions})
    return days


@router.get("/sessions/open", response_model=list[SessionOut])
@limiter.limit("20/minute")
def list_open_sessions(
    request: Request,
    telegram_id: int,
    game_type: str | None = None,
    day: str | None = None,
    db: Session = Depends(get_db),
    actor: models.Player = Depends(get_bot_actor),
) -> list[SessionOut]:
    sessions = registration_service.list_open_sessions(db, game_type=game_type, exclude_player_id=actor.id)
    if day:
        sessions = [s for s in sessions if club_day(s.starts_at) == day]
    return [session_to_out(s) for s in sessions]


@router.get("/sessions/{session_id}", response_model=SessionOut)
@limiter.limit("20/minute")
def get_session(
    request: Request, session_id: int, telegram_id: int, db: Session = Depends(get_db), _: models.Player = Depends(get_bot_actor)
) -> SessionOut:
    game = db.get(models.Game, session_id)
    if game is None:
        raise HTTPException(404, "Сессия не найдена")
    return session_to_out(game)


@router.post("/sessions/{session_id}/register", response_model=RegistrationOut)
@limiter.limit("20/minute")
def register_for_session(
    request: Request, session_id: int, data: RegisterIn, db: Session = Depends(get_db), _: None = Depends(require_bot_service)
) -> RegistrationOut:
    actor = db.query(models.Player).filter(models.Player.telegram_id == data.telegram_id).one_or_none()
    if actor is None:
        raise HTTPException(404, "Игрок не найден")

    game = db.get(models.Game, session_id)
    if game is None or not is_session_open(game):
        raise HTTPException(404, "Сессия недоступна для записи")

    try:
        result = registration_service.register_for_kind(
            db, game=game, player=actor, role_kind=data.role_kind
        )
        db.commit()
    except RegistrationError as exc:
        db.rollback()
        return RegistrationOut(ok=False, message=exc.message, reason=exc.reason)

    if result.reserved:
        # Отказа «мест нет» больше нет: стол собирается первым, следующие
        # встают в очередь тем же нажатием (registration_service.JoinResult).
        return RegistrationOut(
            ok=True,
            message=f"Основной состав уже собран — вы в резерве, №{result.position}",
            role=result.role,
            is_reserve=True,
            reserve_position=result.position,
        )
    # Уход за стол -> в штаб освобождает место игрока, и очередь сдвигается
    # прямо здесь. Боту нужно кому написать -- те же поля, что и у отмены.
    if result.promoted is not None:
        db.refresh(result.promoted)
        return RegistrationOut(
            ok=True,
            message="Вы успешно записаны",
            role=result.role,
            promoted_telegram_id=result.promoted.telegram_id,
            promoted_nickname=result.promoted.nickname,
        )
    return RegistrationOut(ok=True, message="Вы успешно записаны", role=result.role)


@router.post("/sessions/{session_id}/reserve", response_model=RegistrationOut)
@limiter.limit("20/minute")
def reserve_for_session(
    request: Request, session_id: int, data: ReserveIn, db: Session = Depends(get_db), _: None = Depends(require_bot_service)
) -> RegistrationOut:
    """Явная постановка в очередь.

    Обычный путь другой: /register сам отправляет в резерв всех, кто пришёл
    после того, как стол собрался (registration_service.register_for_kind) --
    отдельного экрана «мест нет» в боте больше нет. Ручка осталась как прямой
    способ встать в очередь, не пытаясь занять место за столом.
    """
    actor = db.query(models.Player).filter(models.Player.telegram_id == data.telegram_id).one_or_none()
    if actor is None:
        raise HTTPException(404, "Игрок не найден")

    game = db.get(models.Game, session_id)
    if game is None or not is_session_open(game):
        raise HTTPException(404, "Сессия недоступна для записи")

    try:
        registration_service.add_to_reserve(db, game_id=session_id, player_id=actor.id)
        db.commit()
    except RegistrationError as exc:
        db.rollback()
        return RegistrationOut(ok=False, message=exc.message, reason=exc.reason)
    return RegistrationOut(ok=True, message="Вы записаны в резерв")


@router.get("/sessions/{session_id}/roster", response_model=RosterOut)
@limiter.limit("20/minute")
def get_session_roster(
    request: Request, session_id: int, telegram_id: int, db: Session = Depends(get_db), _: models.Player = Depends(get_bot_actor)
) -> RosterOut:
    game = db.get(models.Game, session_id)
    if game is None:
        raise HTTPException(404, "Сессия не найдена")
    return roster_to_out(game)


@router.delete("/sessions/{session_id}/registration", response_model=RegistrationOut)
@limiter.limit("20/minute")
def cancel_registration(
    request: Request, session_id: int, telegram_id: int, db: Session = Depends(get_db), actor: models.Player = Depends(get_bot_actor)
) -> RegistrationOut:
    promoted = registration_service.unregister(db, game_id=session_id, player_id=actor.id)
    db.commit()
    if promoted:
        db.refresh(promoted)
        return RegistrationOut(
            ok=True,
            message="Запись отменена",
            promoted_telegram_id=promoted.telegram_id,
            promoted_nickname=promoted.nickname,
        )
    return RegistrationOut(ok=True, message="Запись отменена")


@router.get("/registrations/mine", response_model=list[MyRegistrationOut])
@limiter.limit("20/minute")
def my_registrations(
    request: Request, telegram_id: int, db: Session = Depends(get_db), actor: models.Player = Depends(get_bot_actor)
) -> list[MyRegistrationOut]:
    return _actor_registrations(db, actor.id)


def _actor_registrations(db: Session, player_id: int) -> list[MyRegistrationOut]:
    out: list[MyRegistrationOut] = []
    regs = db.query(models.Registration).filter(models.Registration.player_id == player_id).all()
    for r in regs:
        out.append(
            MyRegistrationOut(
                game_id=r.game_id,
                starts_at=r.game.starts_at,
                location=r.game.location,
                game_type=r.game.game_type,
                role=r.role,
                is_reserve=False,
            )
        )
    reserves = db.query(models.Reserve).filter(models.Reserve.player_id == player_id).all()
    for r in reserves:
        out.append(
            MyRegistrationOut(
                game_id=r.game_id,
                starts_at=r.game.starts_at,
                location=r.game.location,
                game_type=r.game.game_type,
                role="reserve",
                is_reserve=True,
            )
        )
    return sorted(out, key=lambda x: x.starts_at)
