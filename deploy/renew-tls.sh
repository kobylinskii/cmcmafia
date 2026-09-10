#!/bin/sh
# Продление сертификата. Ставится в крон root'а раз в неделю:
#
#   0 4 * * 1 /opt/cmcmafia/deploy/renew-tls.sh >> /var/log/cmcmafia-tls.log 2>&1
#
# Скрипт, а не строка в crontab: у крона обрезанный PATH и свой cwd, а тут
# нужны и docker, и каталог проекта -- одна забытая деталь означает молча
# протухший сертификат через три месяца.
#
# certbot сам ничего не делает, если до истечения больше 30 дней, поэтому
# запускать чаще безопасно. Продление идёт через webroot, nginx при этом
# продолжает работать; reload нужен, чтобы он перечитал новый файл (свой
# сертификат он держит в памяти с момента старта).
set -eu

cd "$(dirname "$0")/.."

echo "=== $(date -Is) renew ==="
docker compose run --rm certbot renew --webroot -w /var/www/certbot
docker compose exec nginx nginx -s reload
