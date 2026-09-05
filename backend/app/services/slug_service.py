from __future__ import annotations

import re

from slugify import slugify
from sqlalchemy.orm import Session

from app import models

RESERVED_SLUGS = {
    "games",
    "rating",
    "admin",
    "api",
    "login",
    "static",
    "assets",
    "favicon.ico",
    "robots.txt",
    "sitemap.xml",
    "_next",
    "mafia",
    # /mafia/tournaments -- отдельный раздел, он не должен перекрываться
    # игроком с таким slug (страницы игроков живут прямо в /mafia/[slug]).
    "tournaments",
}


def suggest_slug(nickname: str, db: Session) -> str:
    """Транслитерирует ник в черновой slug. Это только предложение по умолчанию —
    ТЗ явно требует смыслового перевода («Шеф» -> chef), который транслитерация
    не даёт, поэтому итоговое значение всегда редактируется вручную в форме."""
    base = slugify(nickname, max_length=48) or "player"
    if base in RESERVED_SLUGS:
        base = f"{base}-player"

    candidate = base
    suffix = 2
    while is_slug_taken(candidate, db):
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def is_slug_taken(slug: str, db: Session, exclude_player_id: int | None = None) -> bool:
    query = db.query(models.Player).filter(models.Player.slug == slug)
    if exclude_player_id is not None:
        query = query.filter(models.Player.id != exclude_player_id)
    return query.first() is not None


def validate_slug(slug: str) -> None:
    if slug in RESERVED_SLUGS:
        raise ValueError(f"Slug «{slug}» зарезервирован системой")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,48}[a-z0-9]", slug):
        raise ValueError("Slug должен состоять из латинских букв, цифр и дефисов (3-50 символов)")
