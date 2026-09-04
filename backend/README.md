# Mafia Club API

Единый FastAPI-бэкенд для сайта (`/mafia`) и Telegram-бота — см. `../ARCHITECTURE.md` (v3:
единая БД, единый API). Обслуживает три клиентских контура через один процесс:

- `/api/*` и `/api/admin/*` — публичные страницы и веб-админка (JWT-cookie + CSRF);
- `/api/bot/*` и `/api/bot/admin/*` — Telegram-бот (`Authorization: Bearer <BOT_SERVICE_TOKEN>`).

## Запуск локально

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env   # заполнить JWT_SECRET / BOT_SERVICE_TOKEN / DATABASE_URL

alembic upgrade head
uvicorn app.main:app --reload
```

Нужен PostgreSQL 16 (`DATABASE_URL`) и Redis (`REDIS_URL`, rate limiting через slowapi).
Для быстрого локального Postgres:

```bash
docker run -d --name mafia-pg-dev -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=mafia \
  -p 5432:5432 postgres:16
```

## Первый вход в админку сайта

Выдавать доступ на сайт может только уже залогиненный сайт-админ (`POST
/api/admin/players/{id}/site-access`) — значит самого первого нужно завести напрямую:

```bash
# новый игрок + права админа
docker compose exec api python -m app.scripts.create_admin --nickname "Админ"

# либо повысить уже существующего игрока (например, зарегистрированного через бота)
docker compose exec api python -m app.scripts.create_admin --player-id 1
```

Скрипт печатает логин и временный пароль — дальше вход на `/mafia/admin/login`. Сменить
пароль позже — тем же скриптом с `--player-id` и `--password`.

## Тесты

Интеграционный прогон (`tests/test_e2e_flow.py`) гоняется на реальном Postgres — модели
используют Postgres-специфичные типы (JSONB, TIMESTAMPTZ), sqlite не подходит.

```bash
export JWT_SECRET=test-secret BOT_SERVICE_TOKEN=test-bot-token REDIS_URL=memory:// \
       COOKIE_SECURE=false DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:5432/mafia"
alembic upgrade head
python -m pytest tests/ -q
```

## Структура

- `app/models.py` — единая схема (players/games/registrations/reserves/game_participants/
  player_rating/player_rating_history/audit_log).
- `app/services/` — бизнес-логика без привязки к HTTP: `rating_service` (Эло-реплей),
  `registration_service` (запись/резерв/промоушен), `game_service` (CRUD рейтинговых игр),
  `schedule_admin_service` (bulk-создание слотов, конфликты, обзор по дням),
  `admin_grant`/`bootstrap_admin_service` (права бот-админа), `player_service`, `slug_service`.
- `app/routers/` — `public`, `auth`, `admin` (сайт), `bot`, `bot_admin` (бот).
- `app/timeutil.py` — единая точка конвертации UTC ↔ московское время при группировке игр
  по календарному дню (см. docstring внутри — это реальный источник багов, если сделать наивно).
- `alembic/` — миграции.
