#!/bin/sh
# Разовый выпуск сертификата Let's Encrypt для сайта. Запускать ОДИН раз,
# после того как A-запись домена уже указывает на этот сервер:
#
#   ./deploy/init-tls.sh
#
# Продление потом делает deploy/renew-tls.sh по крону, этот скрипт больше не
# нужен (повторный запуск безопасен, но выпишет сертификат заново и съест
# недельную квоту Let's Encrypt на домен).
#
# Курица и яйцо: nginx не стартует, если файла сертификата нет (ssl_certificate
# -- фатальная ошибка конфига), а сертификат не выписать, пока nginx не отвечает
# на :80 для ACME-проверки. Поэтому сначала кладём самоподписанную заглушку,
# поднимаем на ней nginx, и только потом просим настоящий. Удалить заглушку
# можно, не останавливая nginx: он держит сертификат в памяти, а не читает
# файл на каждом соединении.
set -eu

cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
    echo "Нет корневого .env -- скопируйте .env.example и заполните" >&2
    exit 1
fi

read_env_file() { grep -E "^$2=" "$1" 2>/dev/null | tail -1 | cut -d= -f2- ; }
read_env()      { read_env_file .env "$1" ; }

DOMAIN=$(read_env DOMAIN)
EMAIL=$(read_env LETSENCRYPT_EMAIL)

# Проверка всех .env разом, а не только двух переменных для certbot: это
# последний шаг перед тем, как стек станет доступен из интернета, и дешевле
# упереться здесь, чем искать потом причину, по которой «сайт работает, а бот
# молчит». Выпуск сертификата к тому же расходует квоту Let's Encrypt, так что
# лезть за ним с недозаполненным конфигом смысла нет.
PROBLEMS=""
note() { PROBLEMS="$PROBLEMS\n  - $1"; }

check() {  # файл, ключ, значение-заглушка, подсказка
    value=$(read_env_file "$1" "$2")
    if [ -z "$value" ] || [ "$value" = "$3" ]; then
        note "$1: не заполнен $2 -- $4"
    fi
}

# if, а не `[ ... ] && note ...`: при set -e ложное условие делает весь
# AND-список неуспешным, и скрипт молча вышел бы прямо здесь.
if [ -z "$DOMAIN" ]; then
    note ".env: не заполнен DOMAIN -- домен сайта без схемы и без www"
fi
if [ -z "$EMAIL" ]; then
    note ".env: не заполнен LETSENCRYPT_EMAIL -- почта для писем о продлении"
fi

check .env POSTGRES_PASSWORD "" "пароль базы; сгенерировать: openssl rand -hex 24"
check .env NEXT_PUBLIC_BOT_USERNAME "" "username бота без @"
check backend/.env JWT_SECRET "change-me-to-a-random-64-char-secret" "при переезде -- значение со старого хостинга"
check backend/.env BOT_SERVICE_TOKEN "change-me-to-a-random-64-char-secret" "при переезде -- значение со старого хостинга"
check bot/.env BOT_TOKEN "your_bot_token_here" "токен от @BotFather"
check bot/.env BOT_SERVICE_TOKEN "change-me-to-a-random-64-char-secret" "тот же, что в backend/.env"

# Оба заполнены, но разные -- самая коварная ошибка во всей настройке: сайт
# при ней работает идеально, а бот получает от API 401 на каждый запрос и
# молчит, не говоря о причине ни слова.
API_SVC=$(read_env_file backend/.env BOT_SERVICE_TOKEN)
BOT_SVC=$(read_env_file bot/.env BOT_SERVICE_TOKEN)
if [ -n "$API_SVC" ] && [ -n "$BOT_SVC" ] && [ "$API_SVC" != "$BOT_SVC" ]; then
    note "BOT_SERVICE_TOKEN в backend/.env и bot/.env НЕ совпадают -- бот будет молчать"
fi

if [ -n "$PROBLEMS" ]; then
    echo "Конфигурация не готова:" >&2
    printf '%b\n' "$PROBLEMS" >&2
    echo "" >&2
    echo "Заполните перечисленное и запустите скрипт снова." >&2
    exit 1
fi

LIVE=/etc/letsencrypt/live/site

echo "==> Самоподписанная заглушка, чтобы nginx смог стартовать"
docker compose run --rm --entrypoint sh certbot -c "
    mkdir -p $LIVE &&
    openssl req -x509 -nodes -newkey rsa:2048 -days 1 \
        -keyout $LIVE/privkey.pem -out $LIVE/fullchain.pem -subj '/CN=$DOMAIN'"

# Именно nginx, а не весь стек: compose поднимет его зависимости (api,
# frontend и дальше postgres, redis), но НЕ бота -- он ни от кого не зависит и
# ни от кого не требуется. Это важно при переезде: пока на Railway живёт
# старый бот, второй с тем же токеном начал бы выхватывать у него апдейты.
# Бот поднимается отдельно, последним шагом переезда.
echo "==> Поднимаем стек (без бота)"
docker compose up -d nginx

echo "==> Ждём nginx на :80"
i=0
while [ "$i" -lt 30 ]; do
    if curl -sf -o /dev/null "http://localhost/.well-known/acme-challenge/" \
        || [ "$(curl -s -o /dev/null -w '%{http_code}' http://localhost/ || true)" != "000" ]; then
        break
    fi
    i=$((i + 1))
    sleep 2
done
if [ "$i" -ge 30 ]; then
    echo "nginx не поднялся за минуту -- смотрите docker compose logs nginx" >&2
    exit 1
fi

# Проверяем связку «certbot пишет в webroot -- nginx отдаёт по http» ДО
# обращения в Let's Encrypt: у них лимит 5 неудачных проверок в час на домен,
# и упереться в него из-за опечатки в томе -- значит ждать час.
echo "==> Проверяем webroot локально"
TOKEN="init-tls-check-$$"
docker compose run --rm --entrypoint sh certbot -c \
    "mkdir -p /var/www/certbot/.well-known/acme-challenge && echo $TOKEN > /var/www/certbot/.well-known/acme-challenge/$TOKEN"
GOT=$(curl -sf "http://localhost/.well-known/acme-challenge/$TOKEN" || true)
docker compose run --rm --entrypoint sh certbot -c \
    "rm -f /var/www/certbot/.well-known/acme-challenge/$TOKEN"
if [ "$GOT" != "$TOKEN" ]; then
    echo "nginx не отдаёт файлы ACME-проверки из общего тома -- дальше идти незачем" >&2
    exit 1
fi

echo "==> Убираем заглушку и просим настоящий сертификат"
docker compose run --rm --entrypoint sh certbot -c \
    "rm -rf /etc/letsencrypt/live/site /etc/letsencrypt/archive/site /etc/letsencrypt/renewal/site.conf"

# www добавляем в сертификат, только если запись РЕАЛЬНО есть в DNS: certbot
# проверяет каждый домен из -d по отдельности, и указанный, но не заведённый
# www завалил бы выпуск целиком -- вместе с попыткой из недельной квоты.
# getent, а не dig: dnsutils на чистой Ubuntu может не стоять.
CERT_DOMAINS="-d $DOMAIN"
if [ -n "$(getent hosts "www.$DOMAIN" || true)" ]; then
    echo "    www.$DOMAIN резолвится -- добавляем в сертификат"
    CERT_DOMAINS="$CERT_DOMAINS -d www.$DOMAIN"
fi

# --cert-name site: имя сертификата не зависит от домена, поэтому путь в
# nginx-tls.conf фиксированный и домен живёт только в .env.
# $CERT_DOMAINS намеренно без кавычек -- это несколько отдельных аргументов.
# shellcheck disable=SC2086
docker compose run --rm certbot certonly \
    --webroot -w /var/www/certbot \
    --cert-name site \
    $CERT_DOMAINS \
    --email "$EMAIL" \
    --agree-tos --no-eff-email --non-interactive

echo "==> Перечитываем конфиг nginx"
docker compose exec nginx nginx -s reload

echo "Готово: https://$DOMAIN"
