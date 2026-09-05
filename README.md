# Мафия ВМК

Сайт клуба спортивной мафии (`/mafia/*`) и Telegram-бот для записи на игры —
одна система: общий FastAPI-бэкенд и одна база Postgres обслуживают и то, и
другое. Подробное описание того, как это устроено внутри (схема БД, API,
формула рейтинга, турнирная сетка, безопасность, деплой) — в
[ARCHITECTURE.md](ARCHITECTURE.md). Этот файл — только про то, как поднять
проект и где что лежит.

## Состав репозитория

| Каталог | Что это | Стек |
|---|---|---|
| [`backend/`](backend) | Единый API для сайта и бота | FastAPI + SQLAlchemy 2.0 + Postgres 16 |
| [`frontend/`](frontend) | Публичный сайт и веб-админка | Next.js 16 (App Router) + TypeScript |
| [`bot/mafia-tg-bot/`](bot/mafia-tg-bot) | Telegram-бот записи на игры | aiogram 3, тонкий HTTP-клиент к API |

Бот и фронтенд не обращаются к базе напрямую — оба ходят только в backend
API. Поднимать их по отдельности можно, но бот и админка сайта без запущенного
backend не заработают.

## Быстрый старт: всё сразу (Docker Compose)

```bash
cp backend/.env.example backend/.env              # заполнить JWT_SECRET / BOT_SERVICE_TOKEN
cp bot/mafia-tg-bot/.env.example bot/mafia-tg-bot/.env   # заполнить BOT_TOKEN, тот же BOT_SERVICE_TOKEN
docker compose up -d --build
```

Поднимает `postgres`, `redis`, `api`, `frontend`, `bot`, `nginx` — сайт
доступен на `http://localhost`. Дальше нужен первый сайт-админ (эндпоинта для
этого нет намеренно — см. ARCHITECTURE.md, раздел 14):

```bash
docker compose exec api python -m app.scripts.create_admin --nickname "Админ"
```

Скрипт печатает логин и временный пароль — входить на `/mafia/admin/login`.

## Backend отдельно (без Docker)

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env      # DATABASE_URL/JWT_SECRET/BOT_SERVICE_TOKEN — localhost-варианты уже проставлены

alembic upgrade head
uvicorn app.main:app --reload
```

Нужен Postgres 16 и Redis (rate limiting через slowapi) на месте, указанном в
`DATABASE_URL`/`REDIS_URL`. Быстрый локальный Postgres:

```bash
docker run -d --name mafia-pg-dev -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=mafia -p 5432:5432 postgres:16
```

Тесты — против **настоящего** Postgres (модели используют TIMESTAMPTZ/JSONB,
sqlite не подходит), по умолчанию на отдельном порту **55432**, чтобы прогон
(`TRUNCATE` перед каждым тестом) не задел dev-базу:

```bash
docker run -d --name mafia-test-db -p 55432:5432 -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=mafia postgres:16
DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:55432/mafia" python -m alembic upgrade head
python -m pytest tests/ -q
```

Список ключевых тестов и что каждый проверяет — ARCHITECTURE.md, раздел 15.

## Frontend отдельно

```bash
cd frontend
npm install
npm run dev     # http://localhost:3000, ждёт backend на NEXT_PUBLIC_API_URL (по умолчанию http://localhost:8000)
```

`npm run build` — продакшн-сборка (`output: standalone`); `npx tsc --noEmit` и
`npx eslint .` — проверка типов и линт перед коммитом.

## Бот отдельно

```bash
cd bot/mafia-tg-bot
pip install -r requirements.txt
cp .env.example .env      # BOT_TOKEN, API_BASE_URL=http://localhost:8000, тот же BOT_SERVICE_TOKEN, что у backend
python bot.py
```

Работает только вместе с запущенным backend. Права первого бот-админа
выдаются конфигом backend (`SUPERADMIN_TELEGRAM_IDS_RAW` /
`BOOTSTRAP_ADMIN_PHONE_RAW` в `backend/.env`), не в самом боте — так
самопожалование прав невозможно в обход авторизации API.

## Дальше

- [ARCHITECTURE.md](ARCHITECTURE.md) — полное описание архитектуры: схема
  БД, весь API, формула рейтинга, турнирная сетка, безопасность, деплой.
