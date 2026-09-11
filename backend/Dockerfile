FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends libpq5 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/media/players

# Порт: $PORT, если платформа его задаёт, иначе привычные 8000.
#
# Хост 0.0.0.0, а НЕ "::": dual-stack тут не получается. asyncio при создании
# IPv6-сокета безусловно ставит IPV6_V6ONLY (CPython, base_events.create_server),
# поэтому "::" даёт сокет, к которому по IPv4 не подключиться вовсе -- а
# docker-сеть в compose именно IPv4. С "::" nginx и бот получали от api
# "Connection refused" на 172.x, healthcheck не проходил никогда, и frontend
# (depends_on: service_healthy) не стартовал вообще.
#
# Оговорка на будущее: платформы с IPv6-only приватной сетью (так было на
# Railway) требуют обратного -- "::" вместо 0.0.0.0. Здесь docker-сеть
# обычная, IPv4.
#
# --proxy-headers + доверие всем X-Forwarded-* нужно, чтобы rate limit
# считался по реальному IP клиента, а не по адресу прокси (см. app/rate_limit.py).
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips=*"]
