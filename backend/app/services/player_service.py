from __future__ import annotations

import io
import logging
import os
import uuid

from PIL import Image, UnidentifiedImageError
from sqlalchemy.orm import Session

from app import models, security
from app.config import get_settings
from app.textmatch import ci_equals
from app.services import slug_service

settings = get_settings()
logger = logging.getLogger(__name__)


class PlayerValidationError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


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


def delete_player(db: Session, *, player: models.Player) -> str:
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


def grant_site_access(db: Session, *, player: models.Player, username: str) -> str:
    existing = db.query(models.Player).filter(models.Player.site_username == username).first()
    if existing and existing.id != player.id:
        raise PlayerValidationError("Такой логин уже занят")

    temp_password = security.generate_temp_password()
    player.site_username = username
    player.site_password_hash = security.hash_password(temp_password)
    # A site login currently has exactly one purpose: administering /mafia/admin.
    # If a lower-privilege site account type is ever introduced, split this out
    # into its own flag instead of overloading is_site_admin.
    player.is_site_admin = True
    player.failed_login_attempts = 0
    player.locked_until = None
    db.flush()
    return temp_password


def revoke_site_access(db: Session, *, player: models.Player) -> None:
    player.site_username = None
    player.site_password_hash = None
    player.is_site_admin = False
    db.flush()


ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}


def save_player_photo(db: Session, *, player: models.Player, raw_bytes: bytes) -> str:
    """Валидирует и переconvert'ит фото (снимает потенциальные вредоносные
    метаданные/полиглот-контент), сохраняет под случайным именем."""
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
        image = image.convert("RGB")
        image.thumbnail((800, 800))

        os.makedirs(settings.media_root, exist_ok=True)
        filename = f"{uuid.uuid4().hex}.jpg"
        path = os.path.join(settings.media_root, filename)
        image.save(path, format="JPEG", quality=85)
    except Exception as exc:
        logger.exception("Не удалось обработать фото для игрока id=%s", player.id)
        raise PlayerValidationError(
            "Не удалось обработать изображение — попробуйте другой файл"
        ) from exc

    previous = player.photo_url
    player.photo_url = f"/media/players/{filename}"
    db.flush()
    _delete_photo_file(previous)
    return player.photo_url


def _delete_photo_file(photo_url: str | None) -> None:
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
