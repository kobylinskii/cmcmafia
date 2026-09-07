FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends libpq5 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/media/players

# Railway прокидывает порт через $PORT; вне Railway (docker-compose) его нет и
# слушаем привычные 8000. Хост "::" -- это IPv6 с dual-stack: принимает и IPv4
# (edge-прокси Railway, docker-compose), и IPv6 (приватная сеть Railway,
# *.railway.internal, по которой к api ходит бот -- она IPv6-only). С
# "0.0.0.0" приватные запросы падали с ConnectError.
# --proxy-headers + доверие всем X-Forwarded-* нужно, чтобы rate limit
# считался по реальному IP клиента, а не по адресу прокси (см. app/rate_limit.py).
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host :: --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips=*"]
