#!/bin/sh
# Перенос данных с Railway на этот сервер: база + файлы фото.
#
#   RAILWAY_DATABASE_URL='postgresql://...@...proxy.rlwy.net:PORT/railway' \
#   OLD_SITE_URL='https://web-production-xxxx.up.railway.app' \
#   ./deploy/migrate-from-railway.sh
#
# RAILWAY_DATABASE_URL -- ПУБЛИЧНЫЙ адрес базы (в Railway у сервиса Postgres
# это DATABASE_PUBLIC_URL, переменная с *.proxy.rlwy.net; внутренний
# *.railway.internal снаружи не резолвится).
# OLD_SITE_URL -- адрес ещё живого сайта на Railway: фото тянутся по http,
# потому что том с ними снаружи недоступен. Запускать ДО того, как погасите
# Railway, и до переключения DNS.
#
# Что делает: снимает дамп, восстанавливает его в локальный postgres при
# погашенных api/bot (иначе pg_restore --clean не сможет удалить объекты, за
# которые держится открытое соединение), затем докачивает файлы фото.
# Повторный запуск безопасен: дамп снимается заново, база перезаливается,
# уже перенесённые фото пропускаются.
set -eu

cd "$(dirname "$0")/.."

: "${RAILWAY_DATABASE_URL:?нужен RAILWAY_DATABASE_URL (DATABASE_PUBLIC_URL из Railway)}"
: "${OLD_SITE_URL:?нужен OLD_SITE_URL (адрес сайта на Railway, ещё работающего)}"

DUMP=deploy/railway.dump
PG_IMAGE=${PG_IMAGE:-postgres:16}

echo "==> Версия базы на Railway"
# Клиент pg_dump старше сервера -- отказ с явным сообщением, поэтому версию
# лучше увидеть заранее. Если тут major больше 16, поднимите PG_IMAGE и image
# сервиса postgres в docker-compose.yml до той же версии, иначе дамп либо не
# снимется, либо не восстановится.
docker run --rm "$PG_IMAGE" psql "$RAILWAY_DATABASE_URL" -Atc "select version()" | cut -c1-40

echo "==> Дамп с Railway -> $DUMP"
# --no-owner/--no-privileges: роли на Railway свои, локально всё под postgres.
docker run --rm "$PG_IMAGE" pg_dump \
    --no-owner --no-privileges --format=custom \
    "$RAILWAY_DATABASE_URL" > "$DUMP"
ls -lh "$DUMP"

echo "==> Останавливаем api и bot, поднимаем только базу"
docker compose stop api bot 2>/dev/null || true
docker compose up -d postgres

echo "==> Ждём готовности базы"
i=0
while [ "$i" -lt 30 ]; do
    if docker compose exec -T postgres pg_isready -U postgres -d mafia >/dev/null 2>&1; then
        break
    fi
    i=$((i + 1))
    sleep 2
done
if [ "$i" -ge 30 ]; then
    echo "postgres не поднялся -- смотрите docker compose logs postgres" >&2
    exit 1
fi

echo "==> Восстановление"
# --clean --if-exists: на пустой базе просто ничего не удаляет, а при повторном
# запуске (или если api успел прогнать миграции) сносит прежние объекты и
# заливает дамп поверх. Код возврата не проверяем строго: pg_restore считает
# ошибкой и безобидные NOTICE про отсутствующие объекты при первом заходе.
docker compose exec -T postgres pg_restore \
    --no-owner --no-privileges --clean --if-exists \
    -U postgres -d mafia < "$DUMP" || echo "(pg_restore вернул ненулевой код -- проверьте вывод выше)"

echo "==> Файлы фото со старого сайта"
docker compose run --rm --no-deps \
    -e OLD_SITE_URL="$OLD_SITE_URL" \
    -v "$(pwd)/deploy:/deploy:ro" \
    --entrypoint python api /deploy/copy-railway-photos.py

echo
echo "Данные на месте."
echo "Пока на Railway ещё работает бот -- поднимать стек БЕЗ бота:"
echo "    docker compose up -d nginx"
echo "После того как бот на Railway погашен -- поднять всё, включая бота:"
echo "    docker compose up -d"
