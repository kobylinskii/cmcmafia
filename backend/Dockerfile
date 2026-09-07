FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends libpq5 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/media/players

# Railway прокидывает порт через $PORT; вне Railway (docker-compose) его нет и
# слушаем привычные 8000. --proxy-headers + доверие всем X-Forwarded-* нужно,
# чтобы rate limit считался по реальному IP клиента, а не по адресу
# edge-прокси Railway (см. backend/app/rate_limit.py).
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips=*"]
