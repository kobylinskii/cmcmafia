"""Найти в базе ссылки на фото, которых нет на диске, и очистить их.

Приложение держит базу и диск в согласии само: при замене или удалении фото
прежний файл стирается (player_service.delete_photo_file). Но обратной
проверки нет нигде, и она сознательно не добавлена: photo_url приезжает в семи
схемах ответа, валидатор пришлось бы вешать в каждую, а состояние возникает не
из-за приложения, а из-за операций над сервером -- пересоздали том, удалили
файл руками, не докачался при переносе с прежнего хостинга. Платить за это
проверкой на каждый запрос дороже, чем разово починить данные.

Игрок с битой ссылкой выглядит на сайте сломанной картинкой вместо аккуратной
буквы ника, которая показывается, когда фото нет вовсе. Этот скрипт переводит
первое во второе.

Usage (внутри контейнера api):
    docker compose exec api python -m app.scripts.clean_missing_photos
    docker compose exec api python -m app.scripts.clean_missing_photos --apply

Без --apply только показывает, что нашёл, и ничего не меняет.
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import select

from app import models
from app.config import get_settings
from app.database import SessionLocal

settings = get_settings()


def file_missing(photo_url: str) -> bool:
    """Файла, на который указывает photo_url, нет на диске.

    Разбор совпадает с player_service.delete_photo_file: всё, что не похоже на
    наш собственный /media/players/<имя>, не трогаем вовсе -- это может быть
    внешний адрес, и судить о нём по файловой системе нельзя.
    """
    name = photo_url.removeprefix("/media/players/")
    if name == photo_url or "/" in name or name in ("", ".", ".."):
        return False
    return not os.path.exists(os.path.join(settings.media_root, name))


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Действительно очистить ссылки. Без него -- только показать.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        players = db.scalars(
            select(models.Player).where(models.Player.photo_url.is_not(None))
        ).all()
        broken_players = [p for p in players if file_missing(p.photo_url or "")]

        # Правки фото, ждущие решения админа: файл уже загружен и лежит в том
        # же томе, а photo_url игрока пока указывает на прежний. Если файл
        # правки пропал, применять её нельзя -- она подставит битую ссылку.
        changes = db.scalars(
            select(models.PlayerProfileChange).where(
                models.PlayerProfileChange.field == "photo_url",
                models.PlayerProfileChange.status == "pending",
                models.PlayerProfileChange.new_value.is_not(None),
            )
        ).all()
        broken_changes = [c for c in changes if file_missing(c.new_value or "")]

        if not broken_players and not broken_changes:
            print(f"Проверено фото: {len(players)}. Битых ссылок нет.")
            return 0

        for p in broken_players:
            print(f"  игрок {p.id} ({p.nickname}): {p.photo_url}")
        for c in broken_changes:
            print(f"  правка {c.id} (игрок {c.player_id}): {c.new_value}")

        print(
            f"\nБитых ссылок: {len(broken_players)} у игроков, "
            f"{len(broken_changes)} среди правок на проверке."
        )

        if not args.apply:
            print("Ничего не изменено. Повторите с --apply, чтобы очистить.")
            return 0

        for p in broken_players:
            p.photo_url = None
        for c in broken_changes:
            db.delete(c)
        db.commit()
        print("Очищено. Фото можно загрузить заново через админку или бота.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
