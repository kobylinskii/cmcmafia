from __future__ import annotations

import io
import logging
import os
import uuid

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy.orm import Session

from app import models, security
from app.config import get_settings
from app.errors import ServiceError
from app.textmatch import ci_equals
from app.services import slug_service

settings = get_settings()
logger = logging.getLogger(__name__)


class PlayerValidationError(ServiceError):
    pass


# Поля, которые нельзя обнулить через PUT: без них строка игрока невалидна.
_NON_NULLABLE_FIELDS = frozenset({"nickname", "slug"})


def _validate_slug(slug: str) -> None:
    """slug_service -- общий модуль и кидает голый ValueError; роутеры ловят
    только PlayerValidationError, поэтому без этой обёртки зарезервированный
    или кривой slug превращался в 500 вместо понятного 422."""
    try:
        slug_service.validate_slug(slug)
    except ValueError as exc:
        raise PlayerValidationError(str(exc)) from exc


def create_player(
    db: Session,
    *,
    nickname: str,
    slug: str,
    full_name: str | None = None,
    age: int | None = None,
    favorite_role: str | None = None,
    experience: str | None = None,
    bio: str | None = None,
    telegram_id: int | None = None,
    telegram_username: str | None = None,
    phone: str | None = None,
) -> models.Player:
    _validate_slug(slug)
    if slug_service.is_slug_taken(slug, db):
        raise PlayerValidationError(f"Slug «{slug}» уже занят")
    if db.query(models.Player).filter(ci_equals(models.Player.nickname, nickname)).first():
        raise PlayerValidationError("Ник уже занят")

    player = models.Player(
        nickname=nickname,
        slug=slug,
        full_name=full_name,
        age=age,
        favorite_role=favorite_role,
        experience=experience,
        bio=bio,
        telegram_id=telegram_id,
        telegram_username=telegram_username,
        phone=phone,
    )
    db.add(player)
    db.flush()
    return player


def update_player(db: Session, *, player: models.Player, **fields) -> models.Player:
    if "slug" in fields and fields["slug"] is not None:
        new_slug = fields["slug"]
        _validate_slug(new_slug)
        if slug_service.is_slug_taken(new_slug, db, exclude_player_id=player.id):
            raise PlayerValidationError(f"Slug «{new_slug}» уже занят")

    if "nickname" in fields and fields["nickname"] is not None:
        existing = (
            db.query(models.Player)
            .filter(ci_equals(models.Player.nickname, fields["nickname"]), models.Player.id != player.id)
            .first()
        )
        if existing:
            raise PlayerValidationError("Ник уже занят")

    # Роутер отдаёт только те поля, что реально пришли в теле запроса
    # (exclude_unset), поэтому явный null здесь -- это осознанная очистка
    # поля, а не «не трогать». Раньше все None отбрасывались, и стереть
    # био/возраст/имя через админку было невозможно: форма молча сохраняла
    # старое значение.
    for key, value in fields.items():
        if not hasattr(player, key):
            continue
        if value is None and key in _NON_NULLABLE_FIELDS:
            raise PlayerValidationError(f"Поле «{key}» нельзя оставить пустым")
        setattr(player, key, value)

    db.flush()
    return player


def delete_player(db: Session, *, player: models.Player, actor: models.Player | None = None) -> str:
    # Удаление админа -- это тот же отзыв прав (мягко удалённый в админку уже не
    # войдёт), поэтому обе проверки те же, что и у revoke_site_access.
    ensure_can_manage_site_admin(db, actor=actor, target=player)
    ensure_not_last_site_admin(db, player=player)
    _promote_grantees(db, player=player)
    has_games = (
        db.query(models.GameParticipant).filter(models.GameParticipant.player_id == player.id).first()
        is not None
    )
    if has_games:
        player.is_active = False
        db.flush()
        return "soft_deleted"

    db.delete(player)
    db.flush()
    return "deleted"


def grant_site_access(
    db: Session, *, player: models.Player, username: str, actor: models.Player | None = None
) -> str:
    # Перевыдача доступа действующему админу -- это смена его пароля, то есть
    # захват учётки: прав на неё нужно ровно столько же, сколько на отзыв.
    ensure_can_manage_site_admin(db, actor=actor, target=player)

    existing = db.query(models.Player).filter(models.Player.site_username == username).first()
    if existing and existing.id != player.id:
        raise PlayerValidationError("Такой логин уже занят")

    temp_password = security.generate_temp_password()
    player.site_username = username
    player.site_password_hash = security.hash_password(temp_password)
    # Родитель в цепочке проставляется только при первой выдаче: иначе
    # перевыдача пароля переподчиняла бы действующего админа тому, кто её
    # сделал, и права поднимались бы вверх по дереву.
    if not player.is_site_admin and actor is not None and actor.id != player.id:
        player.site_admin_granted_by_id = actor.id
    # A site login currently has exactly one purpose: administering /admin.
    # If a lower-privilege site account type is ever introduced, split this out
    # into its own flag instead of overloading is_site_admin.
    player.is_site_admin = True
    player.failed_login_attempts = 0
    player.locked_until = None
    db.flush()
    return temp_password


def ensure_can_manage_site_admin(
    db: Session, *, actor: models.Player | None, target: models.Player
) -> None:
    """Иерархия отзыва: снять права можно только с того, кому ты их выдал.

    Цепочка хранится в players.site_admin_granted_by_id. Если админ 1 назначил
    админа 2, а тот -- админа 3, то 1 снимает права с обоих, 2 -- только с 3,
    3 -- ни с кого. Себя разжаловать можно всегда (упереться остаётся только в
    ensure_not_last_site_admin).

    Корень цепочки (granted_by IS NULL: первый админ из scripts/create_admin.py
    и все, кто был админом до этой миграции) неприкосновенен для остальных --
    иначе назначенный админ мог бы разжаловать назначившего.

    actor=None -- вызов не из HTTP (скрипт на сервере, сиды): там проверять
    нечего, прямой доступ к базе и так сильнее любых прав в интерфейсе.
    """
    if actor is None or actor.id == target.id or not target.is_site_admin:
        return

    # ponytail: подъём по цепочке -- по запросу на звено; звеньев тут единицы.
    # Рекурсивный CTE, если дерево админов когда-нибудь станет глубоким.
    # seen страхует от цикла: 1 назначил 2, 1 разжалован, 2 назначил 1 обратно.
    seen = {target.id}
    parent_id = target.site_admin_granted_by_id
    while parent_id is not None and parent_id not in seen:
        if parent_id == actor.id:
            return
        seen.add(parent_id)
        parent_id = (
            db.query(models.Player.site_admin_granted_by_id)
            .filter(models.Player.id == parent_id)
            .scalar()
        )

    raise PlayerValidationError(
        "Права этому администратору выдавали не вы — снять их может только тот, кто выдал"
    )


def _promote_grantees(db: Session, *, player: models.Player) -> None:
    """Назначенных разжалованным админом наследует тот, кто назначил его самого.

    Без этого они остались бы корневыми (а при жёстком удалении строки их
    обнулил бы ON DELETE SET NULL), то есть неприкосновенными для всех, кроме
    себя, -- и снять с них права было бы уже некому.
    """
    db.query(models.Player).filter(models.Player.site_admin_granted_by_id == player.id).update(
        {models.Player.site_admin_granted_by_id: player.site_admin_granted_by_id},
        synchronize_session=False,
    )


def ensure_not_last_site_admin(db: Session, *, player: models.Player) -> None:
    """Не дать снять права с ПОСЛЕДНЕГО админа сайта.

    Эндпоинта «сделать себя админом» нет намеренно (см. ARCHITECTURE.md,
    раздел 14): первый доступ выдаётся только скриптом на сервере. Обратная
    сторона -- снять с себя доступ или удалить свою учётку админ мог, и если
    он был единственным, войти в /admin становилось нечем: ни кнопки,
    ни ручки, только `python -m app.scripts.create_admin` по SSH.
    """
    if not player.is_site_admin:
        return
    others = (
        db.query(models.Player.id)
        .filter(models.Player.is_site_admin.is_(True), models.Player.id != player.id)
        .first()
    )
    if others is None:
        raise PlayerValidationError(
            "Это единственный администратор сайта — сначала выдайте доступ кому-то ещё"
        )


def revoke_site_access(
    db: Session, *, player: models.Player, actor: models.Player | None = None
) -> None:
    ensure_can_manage_site_admin(db, actor=actor, target=player)
    ensure_not_last_site_admin(db, player=player)
    _promote_grantees(db, player=player)
    player.site_username = None
    player.site_password_hash = None
    player.is_site_admin = False
    player.site_admin_granted_by_id = None
    db.flush()


ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}

# Перекодировать фото приходится в любом случае -- это и есть защита от
# метаданных и полиглот-контента, -- поэтому цена ошибки в этих трёх числах
# видна на каждом аватаре, и подобраны они под то, как фото показывается.
#
# 1024, а не 800: на странице игрока фото занимает 160 CSS-пикселей, то есть
# до 480 физических на телефоне с DPR 3, и оптимизатор Next пережимает наш
# файл ещё раз. Чем меньше запас над этими 480, тем заметнее второй проход.
# Апскейла не бывает: thumbnail только уменьшает.
PHOTO_BOX = (1024, 1024)
# 92 вместо 85 стоит примерно вдвое больше байт (150 КБ против 80) и снимает
# ровно ту «замыленность», на которую жаловались: файл один на игрока.
PHOTO_QUALITY = 92


def store_photo_file(raw_bytes: bytes, *, owner_id: int | None = None) -> str:
    """Валидирует и переconvert'ит фото (снимает потенциальные вредоносные
    метаданные/полиглот-контент), сохраняет под случайным именем и отдаёт
    адрес. Игрока не трогает: у фото из бота между записью на диск и
    появлением в профиле стоит проверка админа (profile_change_service), и
    файл на это время лежит ничей."""
    if len(raw_bytes) > settings.max_photo_bytes:
        raise PlayerValidationError("Файл слишком большой")

    try:
        image = Image.open(io.BytesIO(raw_bytes))
        image.verify()
        image = Image.open(io.BytesIO(raw_bytes))  # verify() consumes the file, reopen
    except UnidentifiedImageError as exc:
        raise PlayerValidationError("Файл не является изображением") from exc

    if image.format not in ALLOWED_IMAGE_FORMATS:
        raise PlayerValidationError("Допустимые форматы: JPEG, PNG, WEBP")

    # Всё дальше -- перекодирование и запись на диск -- ловится отдельно и
    # широко: Pillow может упасть на не-UnidentifiedImageError исключении
    # (битый после сигнатуры файл, экзотический режим цвета, полноразмерная
    # анимация), а запись на диск -- на нехватке места или правах доступа.
    # Раньше любое из этого улетало наружу как голый 500 без единого слова
    # о причине -- админ видел просто "не работает".
    try:
        # Ориентация из EXIF -- до всего остального: снятое телефоном боком
        # фото хранит поворот отдельным тегом, а мы этот тег как раз срезаем,
        # и без transpose аватар ложился набок.
        image = ImageOps.exif_transpose(image)
        image = image.convert("RGB")
        # LANCZOS вместо умолчания: на уменьшении в разы он заметно чётче.
        image.thumbnail(PHOTO_BOX, Image.Resampling.LANCZOS)

        os.makedirs(settings.media_root, exist_ok=True)
        filename = f"{uuid.uuid4().hex}.jpg"
        path = os.path.join(settings.media_root, filename)
        # subsampling=0 -- цветовые каналы в полном разрешении. На дефолтном
        # 4:2:0 у лица на аватаре 32px расползаются границы и краснеет кожа.
        image.save(
            path, format="JPEG", quality=PHOTO_QUALITY, subsampling=0, optimize=True
        )
    except Exception as exc:
        logger.exception("Не удалось обработать фото для игрока id=%s", owner_id)
        raise PlayerValidationError(
            "Не удалось обработать изображение — попробуйте другой файл"
        ) from exc

    return f"/media/players/{filename}"


def save_player_photo(db: Session, *, player: models.Player, raw_bytes: bytes) -> str:
    """Записать фото и сразу поставить его в профиль (админка сайта)."""
    photo_url = store_photo_file(raw_bytes, owner_id=player.id)
    previous = player.photo_url
    player.photo_url = photo_url
    db.flush()
    delete_photo_file(previous)
    return photo_url


def delete_photo_file(photo_url: str | None) -> None:
    """Убрать с диска файл, на который больше никто не ссылается.

    Каждая перезагрузка фото писала новый uuid4().hex.jpg и только
    перезаписывала photo_url -- прежний файл оставался в волюме навсегда и
    по-прежнему открывался по прямой ссылке. Волюм рос линейно по числу
    правок, а не по числу игроков.

    Ошибка удаления не должна ронять уже удавшуюся загрузку: новое фото
    сохранено и в базе, и на диске -- потерянный старый файл это в худшем
    случае мусор, а не сломанный профиль.
    """
    if not photo_url:
        return
    # Ожидаем ровно то, что генерирует save_player_photo. Всё остальное
    # (внешний URL, путь с сегментами) не трогаем: удалять по строке из базы
    # можно только там, где эту строку записали мы сами.
    name = photo_url.removeprefix("/media/players/")
    if name == photo_url or "/" in name or name in ("", ".", ".."):
        return
    try:
        os.remove(os.path.join(settings.media_root, name))
    except FileNotFoundError:
        pass
    except OSError:
        logger.warning("Не удалось удалить прежнее фото %s", name, exc_info=True)


def set_bot_admin(db: Session, *, player: models.Player, is_admin: bool) -> models.Player:
    player.is_bot_admin = is_admin
    db.flush()
    return player
