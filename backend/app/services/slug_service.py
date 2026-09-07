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


def suggest_slug(nickname: str, db: Session, *, scope: str = "player") -> str:
    """Транслитерирует ник в черновой slug. Это только предложение по умолчанию —
    ТЗ явно требует смыслового перевода («Шеф» -> chef), который транслитерация
    не даёт, поэтому итоговое значение всегда редактируется вручную в форме.

    scope говорит, СРЕДИ ЧЕГО slug должен быть свободен. Пространства имён два
    и они независимы: игроки живут в /mafia/[slug], турниры -- в
    /mafia/tournaments/[slug]. Раньше занятость проверялась только по игрокам,
    и подсказка для турнира предлагала slug уже существующего турнира: форма
    подставляла его сама, а сохранение падало на «Slug уже занят другим
    турниром» -- причём с полем, которое админ не трогал.
    """
    base = slugify(nickname, max_length=48) or "player"
    if base in RESERVED_SLUGS:
        base = f"{base}-player"
    # ck_players_slug_format требует минимум трёх символов, а ник теперь
    # разрешён и однобуквенный («Я» -> "ia"): без добивки регистрация такого
    # ника падала бы на констрейнте уже в базе.
    if len(base) < 3:
        base = f"{base}-player"

    taken = is_tournament_slug_taken if scope == "tournament" else is_slug_taken
    candidate = base
    suffix = 2
    while taken(candidate, db):
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def is_slug_taken(slug: str, db: Session, exclude_player_id: int | None = None) -> bool:
    query = db.query(models.Player).filter(models.Player.slug == slug)
    if exclude_player_id is not None:
        query = query.filter(models.Player.id != exclude_player_id)
    return query.first() is not None


def is_tournament_slug_taken(slug: str, db: Session, exclude_tournament_id: int | None = None) -> bool:
    query = db.query(models.Tournament).filter(models.Tournament.slug == slug)
    if exclude_tournament_id is not None:
        query = query.filter(models.Tournament.id != exclude_tournament_id)
    return query.first() is not None


def validate_slug(slug: str) -> None:
    if slug in RESERVED_SLUGS:
        raise ValueError(f"Slug «{slug}» зарезервирован системой")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,48}[a-z0-9]", slug):
        raise ValueError("Slug должен состоять из латинских букв, цифр и дефисов (3-50 символов)")
