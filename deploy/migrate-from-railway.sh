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

# Заглушки из инструкции, подставленные дословно. Без этой проверки они дают
# «could not translate host name», по которому не догадаться, что дело не в
# сети, а в незаполненной команде.
case "$RAILWAY_DATABASE_URL" in
    *xxx.proxy.rlwy.net*|*postgres:...@*|*'<'*'>'*)
        echo "RAILWAY_DATABASE_URL -- это пример из инструкции, а не ваш адрес." >&2
        echo "Взять настоящий: Railway -> сервис Postgres -> Variables -> DATABASE_PUBLIC_URL" >&2
        exit 1 ;;
esac
case "$OLD_SITE_URL" in
    *web-production-xxxx*|*'<'*'>'*)
        echo "OLD_SITE_URL -- это пример из инструкции, а не ваш адрес." >&2
        echo "Взять настоящий: Railway -> сервис web -> Settings -> Domains" >&2
        exit 1 ;;
esac

# Неподставленный шаблон Railway: в интерфейсе переменные показываются
# ссылками ${{PGPASSWORD}} и т.п., которые платформа раскрывает только у себя.
# Скопированные как есть, они дают «invalid integer value ... for connection
# option port» -- сообщение, по которому причину не угадать.
case "$RAILWAY_DATABASE_URL" in
    *'${{'*)
        echo "В строке остались ссылки Railway вида \${{PGPASSWORD}} -- это шаблон," >&2
        echo "а не готовый адрес. Нужно значение с подставленными данными:" >&2
        echo "  Railway -> сервис Postgres -> вкладка Connect -> Public Network," >&2
        echo "  либо собрать вручную из переменных на вкладке Variables:" >&2
        echo "  postgresql://<PGUSER>:<PGPASSWORD>@<RAILWAY_TCP_PROXY_DOMAIN>:<RAILWAY_TCP_PROXY_PORT>/<PGDATABASE>" >&2
        exit 1 ;;
esac

# Внутренний адрес Railway. Резолвится только внутри их сети, и снаружи даёт
# ровно то же «could not translate host name», что и опечатка -- поэтому
# называем причину прямо.
case "$RAILWAY_DATABASE_URL" in
    *railway.internal*)
        echo "Это ВНУТРЕННИЙ адрес Railway -- снаружи он не резолвится." >&2
        echo "Нужен DATABASE_PUBLIC_URL: Railway -> сервис Postgres -> Variables." >&2
        echo "В нём хост вида *.proxy.rlwy.net и порт, отличный от 5432." >&2
        exit 1 ;;
esac

# Адрес сайта без схемы: urllib из copy-railway-photos.py на таком падает с
# «unknown url type», причём уже после того, как база восстановлена. Дешевле
# дописать схему здесь, чем ловить это в конце переноса.
case "$OLD_SITE_URL" in
    http://*|https://*) ;;
    *)  OLD_SITE_URL="https://$OLD_SITE_URL"
        export OLD_SITE_URL
        echo "==> OLD_SITE_URL был без схемы, использую $OLD_SITE_URL" ;;
esac

DUMP=deploy/railway.dump

die() { echo "$1" >&2; exit 1; }

echo "==> Версия базы на Railway"
# Клиент pg_dump старше сервера -- отказ с явным сообщением, поэтому версию
# лучше увидеть заранее. Если тут major больше 16, поднимите PG_IMAGE и image
# сервиса postgres в docker-compose.yml до той же версии, иначе дамп либо не
# снимется, либо не восстановится.
#
# Без промежуточной переменной здесь был конвейер `psql | cut`, а код возврата
# конвейера -- это код ПОСЛЕДНЕЙ команды, то есть всегда успешного cut. Ошибка
# подключения проглатывалась, и скрипт бодро шёл дальше к дампу.
# postgres:18 -- только чтобы задать первый вопрос: psql к серверу другой
# major-версии подключается спокойно (в отличие от pg_dump), и этого хватает,
# чтобы узнать настоящую версию и дальше взять клиента под неё.
PG_VERSION=$(docker run --rm postgres:18 psql "$RAILWAY_DATABASE_URL" -Atc "select version()")
echo "$PG_VERSION" | cut -c1-40

# pg_dump отказывается работать с сервером другой major-версии -- значит образ
# клиента должен ей соответствовать. Раньше версия была зашита числом, и при
# любом обновлении Postgres на той стороне перенос падал на ровном месте.
RAILWAY_MAJOR=$(echo "$PG_VERSION" | sed -n 's/^PostgreSQL \([0-9]*\).*/\1/p')
[ -n "$RAILWAY_MAJOR" ] || die "не удалось разобрать версию Postgres: $PG_VERSION"
PG_IMAGE=${PG_IMAGE:-postgres:$RAILWAY_MAJOR}
echo "    клиент для дампа: $PG_IMAGE"

echo "==> Дамп с Railway -> $DUMP"
# Пишем во временный файл и переименовываем: при обрыве связи посреди дампа
# редирект оставил бы обрезанный файл на месте прежнего, годного.
# --no-owner/--no-privileges: роли на Railway свои, локально всё под postgres.
docker run --rm "$PG_IMAGE" pg_dump \
    --no-owner --no-privileges --format=custom \
    "$RAILWAY_DATABASE_URL" > "$DUMP.part"
mv "$DUMP.part" "$DUMP"
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

# Дамп из более новой базы в старую не восстановится: pg_restore упрётся в
# конструкции, которых прежняя версия не знает. Дешевле остановиться здесь,
# чем на половине залитой схемы.
LOCAL_VERSION=$(docker compose exec -T postgres psql -U postgres -d mafia -Atc "show server_version" 2>/dev/null || echo "")
LOCAL_MAJOR=$(echo "$LOCAL_VERSION" | sed -n 's/^\([0-9]*\).*/\1/p')
if [ -n "$LOCAL_MAJOR" ] && [ "$LOCAL_MAJOR" != "$RAILWAY_MAJOR" ]; then
    echo "Версии не совпадают: на Railway $RAILWAY_MAJOR, локально $LOCAL_MAJOR." >&2
    echo "Поправьте image: postgres:$RAILWAY_MAJOR у сервиса postgres в docker-compose.yml." >&2
    echo "Если том базы уже создан прежней версией, его придётся удалить" >&2
    echo "(данных в нём ещё нет): docker compose down && docker volume rm cmcmafia_postgres_data" >&2
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
