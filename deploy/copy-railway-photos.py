"""Перенос файлов фото игроков со старого сайта в том media_players.

Запускается внутри контейнера api (см. deploy/migrate-from-railway.sh): там уже
есть psycopg, DATABASE_URL на новую базу и смонтированный том с фотографиями.

Список файлов берётся из БАЗЫ, а не обходом каталога на старом хосте: том на
Railway недоступен снаружи, зато каждое фото упомянуто в players.photo_url, а
HTTP-адрес совпадает с этим значением. Ожидающие модерации правки фото
(player_profile_changes) -- второй источник: их файл уже загружен и лежит в том
же томе, а photo_url игрока пока указывает на старый. Без них принятая после
переезда правка подставила бы битую картинку.

Порядок: сначала восстановить базу, потом запускать это -- список берётся
из уже восстановленных таблиц.
"""

import os
import sys
import urllib.request

MEDIA_DIR = "/app/media/players"

PHOTO_SOURCES = """
    SELECT photo_url FROM players WHERE photo_url IS NOT NULL
    UNION
    SELECT new_value FROM player_profile_changes
     WHERE field = 'photo_url' AND new_value IS NOT NULL
"""


def local_name(photo_url: str) -> str:
    """Имя файла в томе из значения photo_url ('/media/players/<uuid>.jpg')."""
    return photo_url.rsplit("/", 1)[-1]


def selfcheck() -> None:
    assert local_name("/media/players/abc123.jpg") == "abc123.jpg"
    # Пустое имя и путь наружу -- в базе таких быть не должно, но если появятся,
    # они не должны превратиться в запись мимо каталога.
    assert local_name("/media/players/") == ""
    assert local_name("../../etc/passwd") == "passwd"
    print("selfcheck ok")


def main() -> int:
    import psycopg

    base = os.environ["OLD_SITE_URL"].rstrip("/")
    # DATABASE_URL приходит в SQLAlchemy-виде, psycopg такую схему не понимает.
    dsn = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")

    with psycopg.connect(dsn) as conn:
        urls = [row[0] for row in conn.execute(PHOTO_SOURCES).fetchall()]

    copied = skipped = failed = 0
    for url in urls:
        name = local_name(url)
        if not name:
            print(f"пропуск: не разобрать имя файла в {url!r}", file=sys.stderr)
            failed += 1
            continue
        dst = os.path.join(MEDIA_DIR, name)
        if os.path.exists(dst):
            skipped += 1
            continue
        try:
            # Скачиваем во временное имя и переименовываем: прерванная загрузка
            # иначе оставила бы обрезанный файл, который при повторном запуске
            # выглядит как уже перенесённый и молча остался бы битым.
            tmp = dst + ".part"
            urllib.request.urlretrieve(base + url, tmp)
            os.replace(tmp, dst)
            copied += 1
        except Exception as exc:  # noqa: BLE001 -- одна битая ссылка не повод рвать перенос
            print(f"не скачалось {base + url}: {exc}", file=sys.stderr)
            failed += 1

    print(f"фото: перенесено {copied}, уже было {skipped}, ошибок {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        selfcheck()
    else:
        sys.exit(main())
