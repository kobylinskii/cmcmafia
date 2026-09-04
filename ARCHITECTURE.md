# Архитектура проекта «Мафия»: сайт + Telegram-бот (v3 — единая БД, единый API)

v3 меняет ключевое решение v2: вместо двух Postgres-схем и раздельных путей записи — **одна база, одна схема, один FastAPI-бэкенд**, через который работают и сайт, и бот. Бот перестаёт напрямую обращаться к Postgres и становится тонким клиентом API (архитектуру бота меняем, как и разрешено; приоритет — архитектура сайта).

## 0. Что изменилось относительно v2

| | v2 | v3 |
|---|---|---|
| БД | 2 Postgres-схемы (`bot`, `site`), бот пишет напрямую | 1 схема, 1 набор таблиц, единственный писатель — API |
| Бот | psycopg + собственный `Database`-класс | HTTP-клиент к тому же FastAPI, что и сайт |
| «Игра» | 2 разные сущности: `bot.games` (сессия записи) и `site.games` (результат) + мост `linked_session_id` | 1 таблица `games` с полем `status`, проходит через жизненный цикл `scheduled → played → rated` |
| Админы | `bot.admins` (по tg_id) + `site.admin_users` (логин/пароль) — раздельно | Флаги `is_bot_admin` / `is_site_admin` на одной таблице `players` |
| Синхронизация «оценить игру» | Отдельный bridge-эндпоинт, читающий чужую схему | Не нужна: это одна и та же строка `games`, просто меняет `status` |

---

## 1. Общая архитектура

```
                         ┌───────────────────────┐
                         │      PostgreSQL          │
                         │   (одна схема public)    │
                         └────────────▲──────────────┘
                                      │  единственный писатель
                                      │
                         ┌────────────┴──────────────┐
                         │        Backend API           │
                         │   FastAPI, один процесс       │
                         │  /api/*        — сайт (public) │
                         │  /api/admin/*  — сайт-админка   │
                         │  /api/bot/*    — бот (юзер)      │
                         │  /api/bot/admin/* — бот-админка   │
                         │  RatingService (Эло-реплей)        │
                         └───────▲───────────────────▲──────┘
                                 │ REST/JSON               │ REST/JSON
                                 │ JWT cookie (браузер)     │ Bearer BOT_SERVICE_TOKEN
                                 │                          │ (сервис-к-сервису)
                    ┌────────────┴───────┐      ┌────────────┴────────────┐
                    │     Frontend          │      │     Telegram Bot          │
                    │  Next.js + TypeScript │      │  aiogram — тонкий клиент, │
                    │                        │      │  без прямого доступа к БД  │
                    └───────────────────────┘      └──────────────┬─────────────┘
                                                                     │ long polling /
                                                                     │ webhook
                                                                     ▼
                                                              Telegram Bot API
```

Один Postgres-логин (`api_role`) на всё, одна Alembic-история миграций, один OpenAPI-контракт. Бот и фронтенд — два клиента одного и того же API, различаются только способом авторизации.

---

## 2. Стек технологий (без изменений по составу, меняется роль бота)

| Слой | Технология |
|---|---|
| БД | PostgreSQL 16, одна схема |
| Backend | FastAPI + Pydantic v2 + SQLAlchemy 2.0 + Alembic |
| Auth сайта | argon2id + JWT (httpOnly cookie) + CSRF double-submit |
| Auth бота | `BOT_SERVICE_TOKEN` (Bearer, сервис-к-сервису) — см. раздел 9.1 |
| Rate limiting | slowapi + Redis |
| Frontend | Next.js 14 (App Router) + TypeScript + Tailwind |
| Бот | aiogram 3.x + `httpx.AsyncClient` вместо psycopg; FSM/клавиатуры остаются |
| Фоновые задачи бота | APScheduler внутри процесса бота (напоминания, поллинг «сессии ожидают оценки») |
| Файлы | volume + Nginx (или S3/MinIO — см. допущения) |
| Хостинг | Docker Compose: postgres, redis, api, frontend, bot, nginx |

---

## 3. Единая схема базы данных

```sql
-- ===================== ИГРОКИ / ЛЮДИ =====================
-- Одна таблица на человека: игрок с сайта, пользователь бота, админ бота,
-- админ сайта — всё это флаги/поля одной и той же строки.
CREATE TABLE players (
    id                     SERIAL PRIMARY KEY,

    -- профиль игрока (ТЗ сайта)
    slug                   VARCHAR(50) UNIQUE NOT NULL
                            CHECK (slug ~ '^[a-z0-9][a-z0-9-]{1,48}[a-z0-9]$'),
    nickname               VARCHAR(100) UNIQUE NOT NULL,
    full_name              VARCHAR(150),
    age                    SMALLINT CHECK (age IS NULL OR age BETWEEN 5 AND 100),
    favorite_role          VARCHAR(10) CHECK (favorite_role IS NULL OR favorite_role IN ('mafia','don','sheriff','citizen')),
    experience             TEXT,
    bio                    TEXT,
    photo_url              TEXT,

    -- поля бота (перенесены как есть из bot.users)
    telegram_id            BIGINT UNIQUE,
    telegram_username      VARCHAR(100),
    phone                  VARCHAR(20) UNIQUE,          -- нормализовано, только цифры
    salutation             VARCHAR(20),                 -- обращение
    affiliation            VARCHAR(20) CHECK (affiliation IS NULL OR affiliation IN ('vmk','mgu_no_pass','outside_need_pass')),
    can_play                BOOLEAN NOT NULL DEFAULT TRUE,
    can_staff               BOOLEAN NOT NULL DEFAULT TRUE,

    -- доступ в веб-админку
    site_username           VARCHAR(50) UNIQUE,
    site_password_hash      TEXT,
    is_site_admin            BOOLEAN NOT NULL DEFAULT FALSE,
    failed_login_attempts    SMALLINT NOT NULL DEFAULT 0,
    locked_until              TIMESTAMPTZ,
    last_login_at              TIMESTAMPTZ,

    -- права в боте (замена bot.admins)
    is_bot_admin               BOOLEAN NOT NULL DEFAULT FALSE,

    is_active                  BOOLEAN NOT NULL DEFAULT TRUE,   -- soft-delete
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                   TIMESTAMPTZ NOT NULL DEFAULT now(),

    CHECK (site_username IS NULL OR site_password_hash IS NOT NULL)
);

-- приглашение в бот-админы по username, пока человек не написал боту /start
-- (аналог bot.pending_admins, имя не меняется по сути)
CREATE TABLE pending_bot_admins (
    id           SERIAL PRIMARY KEY,
    username     VARCHAR(100) UNIQUE NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ===================== ИГРЫ (единая сущность: от записи до результата) =====================
CREATE TYPE game_status AS ENUM ('scheduled', 'registration_closed', 'played', 'rated');

CREATE TABLE games (
    id                          SERIAL PRIMARY KEY,
    starts_at                   TIMESTAMPTZ NOT NULL,   -- дата+время; одновременно ключ хронологии для Эло
    location                    VARCHAR(200),
    game_type                   VARCHAR(20) NOT NULL DEFAULT 'tournament'
                                 CHECK (game_type IN ('tournament','funky','training')),
    registration_until          TIMESTAMPTZ,             -- NULL для игр, добавленных сразу как исторические
    max_players                 SMALLINT NOT NULL DEFAULT 10,

    status                      game_status NOT NULL DEFAULT 'scheduled',
    result                      VARCHAR(10) CHECK (result IS NULL OR result IN ('city_win','mafia_win','draw')),
    results_reminder_sent_at    TIMESTAMPTZ,             -- чтобы не спамить админов повторными "оцените игру"

    notes                       TEXT,
    created_by                  INTEGER REFERENCES players(id),
    created_at                   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),

    CHECK (status <> 'rated' OR result IS NOT NULL)
);

-- ===================== ЗАПИСЬ НА ИГРУ (до игры: ведущий/судья/игрок/резерв) =====================
CREATE TABLE registrations (
    id                SERIAL PRIMARY KEY,
    game_id           INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    player_id         INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    role              VARCHAR(10) NOT NULL CHECK (role IN ('host','judge','player')),
    available_from    TEXT,
    available_until   TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (game_id, player_id)
);

CREATE TABLE reserves (
    id           SERIAL PRIMARY KEY,
    game_id      INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    player_id    INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (game_id, player_id)
);

-- ===================== РЕЗУЛЬТАТ ИГРЫ (после игры: 10 мест, ин-гейм роли, баллы) =====================
-- Сознательно отдельная от registrations таблица: до игры человек занимает
-- реальную роль (ведущий/судья/игрок), после — конкретное игровое место
-- с игровой ролью (мафия/мирный/дон/шериф) и баллами. Это разные сущности
-- с разным временем жизни, объединять их в одну — только запутывать данные.
CREATE TABLE game_participants (
    id              SERIAL PRIMARY KEY,
    game_id         INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    player_id       INTEGER NOT NULL REFERENCES players(id) ON DELETE RESTRICT,
    seat_number     SMALLINT NOT NULL CHECK (seat_number BETWEEN 1 AND 10),
    role            VARCHAR(10) NOT NULL CHECK (role IN ('mafia','don','sheriff','citizen')),

    points_win      NUMERIC(4,2) NOT NULL DEFAULT 0,
    points_judge    NUMERIC(4,2) NOT NULL DEFAULT 0,
    lh              NUMERIC(3,2) CHECK (lh IS NULL OR lh BETWEEN 0 AND 1.5),
    ci              NUMERIC(5,2),
    info            VARCHAR(20) CHECK (info IS NULL OR info IN ('first_killed','killed','voted_out')),
    removals        SMALLINT CHECK (removals IS NULL OR removals >= 0),
    ppk             BOOLEAN NOT NULL DEFAULT FALSE,
    zk              NUMERIC(3,1) CHECK (zk IS NULL OR zk >= 0),
    sk              NUMERIC(3,1) CHECK (sk IS NULL OR sk >= 0),

    UNIQUE (game_id, seat_number),
    UNIQUE (game_id, player_id)
);

-- ===================== РЕЙТИНГ =====================
CREATE TABLE player_rating (
    player_id     INTEGER PRIMARY KEY REFERENCES players(id) ON DELETE CASCADE,
    rating         NUMERIC(7,2) NOT NULL DEFAULT 1000,
    games_count    INTEGER NOT NULL DEFAULT 0,
    wins           INTEGER NOT NULL DEFAULT 0,
    losses         INTEGER NOT NULL DEFAULT 0,
    draws          INTEGER NOT NULL DEFAULT 0,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE player_rating_history (
    id                BIGSERIAL PRIMARY KEY,
    player_id         INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    game_id           INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    rating_before     NUMERIC(7,2) NOT NULL,
    rating_after      NUMERIC(7,2) NOT NULL,
    delta             NUMERIC(7,2) NOT NULL,
    k_coefficient     SMALLINT NOT NULL,
    expected_score    NUMERIC(6,4) NOT NULL,
    sa                NUMERIC(5,2) NOT NULL,
    penalty           NUMERIC(5,2) NOT NULL DEFAULT 0,
    UNIQUE (player_id, game_id)
);

-- ===================== АУДИТ (кто и что поменял) =====================
CREATE TABLE audit_log (
    id           BIGSERIAL PRIMARY KEY,
    actor_id     INTEGER REFERENCES players(id),
    actor_kind   VARCHAR(10) NOT NULL CHECK (actor_kind IN ('site','bot')),
    action       VARCHAR(20) NOT NULL,     -- create/update/delete
    entity       VARCHAR(30) NOT NULL,     -- game/player/registration/admin...
    entity_id    INTEGER,
    diff         JSONB,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### 3.1 Индексы

```sql
CREATE INDEX idx_players_active ON players(is_active);
CREATE INDEX idx_players_telegram_id ON players(telegram_id);
CREATE INDEX idx_players_is_bot_admin ON players(is_bot_admin) WHERE is_bot_admin;
CREATE INDEX idx_games_starts_at ON games(starts_at DESC, id DESC);   -- порядок для Эло и списков
CREATE INDEX idx_games_status ON games(status);
CREATE INDEX idx_registrations_player ON registrations(player_id);
CREATE INDEX idx_registrations_game ON registrations(game_id);
CREATE INDEX idx_participants_player ON game_participants(player_id);
CREATE INDEX idx_participants_game ON game_participants(game_id);
CREATE INDEX idx_rating_current ON player_rating(rating DESC);
```

Зарезервированные `slug`: `games, rating, admin, api, login, static, assets, favicon.ico, robots.txt, sitemap.xml, _next, mafia`.

### 3.2 Права доступа

```sql
CREATE ROLE api_role LOGIN PASSWORD '...';
GRANT ALL ON ALL TABLES IN SCHEMA public TO api_role;
-- Больше никто не подключается к Postgres напрямую: ни бот, ни фронтенд.
```

---

## 4. Единый API — полный список эндпоинтов

Один FastAPI-процесс, три уровня авторизации на разных префиксах:

```
# ---------- PUBLIC (сайт, читает кто угодно, только rate limit) ----------
GET  /api/games                         ?limit=&from=&to=&game_type=&result=   (только status=rated)
GET  /api/games/{id}
GET  /api/rating                        ?q=&sort=&page=
GET  /api/rating/formula
GET  /api/players
GET  /api/players/{slug}

# ---------- AUTH сайта ----------
POST /api/auth/login
POST /api/auth/refresh
POST /api/auth/logout

# ---------- SITE ADMIN (JWT cookie + CSRF, is_site_admin=true) ----------
POST   /api/admin/games                     — создать игру сразу как rated (полный шаблон, 10 участников)
PUT    /api/admin/games/{id}                — правка (в т.ч. played -> rated при вводе результатов)
DELETE /api/admin/games/{id}
GET    /api/admin/games/pending-review      — status='played' — «сыграны, результат не внесён»
POST   /api/admin/players
PUT    /api/admin/players/{id}
DELETE /api/admin/players/{id}              — soft-delete, hard только при 0 игр
POST   /api/admin/players/{id}/photo
POST   /api/admin/players/{id}/site-access  — выдать/отозвать сайт-логин (генерирует временный пароль)
GET    /api/admin/bot-admins                — список is_bot_admin=true
POST   /api/admin/bot-admins                — {telegram_id | username}
DELETE /api/admin/bot-admins/{player_id}

# ---------- TELEGRAM USER (Bearer BOT_SERVICE_TOKEN + telegram_id в теле запроса) ----------
POST   /api/bot/players/register            — регистрация нового игрока
GET    /api/bot/players/me                  ?telegram_id=
PUT    /api/bot/players/me                  — редактирование профиля
GET    /api/bot/game-days                   ?game_type=&telegram_id=      — открытые дни, за вычетом уже занятых
GET    /api/bot/sessions/open               ?game_type=&day=
GET    /api/bot/sessions/{id}
POST   /api/bot/sessions/{id}/register      — {telegram_id, role_kind: player|staff, available_from?, available_until?}
POST   /api/bot/sessions/{id}/reserve       — {telegram_id}
DELETE /api/bot/sessions/{id}/registration  — {telegram_id}  -> при отмене авто-промоушен из резерва,
                                               ответ содержит {promoted: {telegram_id, nickname} | null}
GET    /api/bot/registrations/mine          ?telegram_id=

# ---------- TELEGRAM ADMIN (тот же токен + сервер проверяет is_bot_admin для переданного telegram_id) ----------
POST   /api/bot/admin/sessions              — создать сессию (дата/время, место, тип)
PUT    /api/bot/admin/sessions/{id}
DELETE /api/bot/admin/sessions/{id}
GET    /api/bot/admin/sessions/{id}/roster  — состав + резерв
GET    /api/bot/admin/sessions/pending-review — те же, что и /api/admin/games/pending-review — повод прислать "Оценить игру"
POST   /api/bot/admin/admins                — {telegram_id | username} -> is_bot_admin=true (или pending_bot_admins)
DELETE /api/bot/admin/admins/{player_id}
```

`POST /api/admin/bot-admins` и `POST /api/bot/admin/admins` вызывают **один и тот же** сервисный метод `AdminService.grant_bot_admin(...)` — управлять правами бот-админа можно и с сайта, и из чата бота, потому что под капотом это ровно одна и та же операция над одной и той же таблицей. Это и есть смысл «единого API».

---

## 5. Движок рейтинга — Эло (как в v2, порядок теперь проще)

Формула и алгоритм полного реплея — без изменений по сути (см. предыдущую версию, раздел «Эло»). Единственное упрощение: раз `games.starts_at` теперь `TIMESTAMPTZ` (а не `DATE` + отдельный `day_sequence`), хронологический порядок для реплея — это просто `ORDER BY starts_at ASC, id ASC`. Отдельное поле для ручного упорядочивания игр в один день больше не нужно.

`RatingService.recompute_all()` берёт `games WHERE status = 'rated'`, остальные (`scheduled`/`played`) в реплее не участвуют. Пересчёт запускается синхронно, в одной транзакции, при любом `create/update/delete` игры со статусом `rated` через `/api/admin/games/*`.

Формула:

```
R'a = Ra + K * (Sa − E * M) / M − O
Sa = points_win + points_judge + COALESCE(lh,0) + COALESCE(ci,0)
M = 7
E = clamp(1 / (1 + 10^((R_соперники − R_своя_команда)/400)), 0.3, 0.7)
K: games_count<30 → 40; иначе rating>2000 → 10; иначе 20   (по состоянию ДО игры)
O = removals * O_removal(tier) + (ppk ? O_ppk(tier) : 0)
    tier<30 игр: 8/15;  rating>2000: 3/5;  иначе: 5/10
```

Команды: чёрные = `mafia+don`, красные = `citizen+sheriff`.

---

## 6. Персональная статистика игрока (`/api/players/{slug}`)

Без изменений относительно v2 — один SQL-запрос с `FILTER (WHERE ...)` по `game_participants JOIN games` плюс `player_rating`. См. раздел 6 предыдущей версии (структура полностью переносится, меняются только имена таблиц — они теперь без префикса схемы).

---

## 7. Frontend — структура страниц

Без изменений относительно v2 (раздел 7): `/mafia`, `/mafia/games[/[gameId]]`, `/mafia/rating`, `/mafia/[slug]`, `/mafia/admin/*` с проверкой JWT в `middleware.ts`, страница не в навигации/sitemap.

---

## 8. Админка — 4 функции + синхронизация с ботом (упрощена)

Функции 1–4 (добавить/изменить/удалить игру, добавить/изменить/удалить игрока) — как в v2, раздел 8, через `/api/admin/*`.

### Синхронизация «запись в боте → результат на сайте» — теперь без моста

Поскольку игра — **одна и та же строка** от момента создания сессии до внесения результата, никакого отдельного bridge-эндпоинта не нужно:

1. Игра создаётся ботом (`POST /api/bot/admin/sessions`) со статусом `scheduled`. Игроки записываются как раньше.
2. Фоновая задача в API (или периодический воркер) переводит игру в `played`, когда `starts_at` в прошлом, а статус ещё не `rated`.
3. Бот (свой APScheduler, поллинг раз в несколько минут) вызывает `GET /api/bot/admin/sessions/pending-review`, и для игр без `results_reminder_sent_at` шлёт бот-админам кнопку **«📝 Оценить игру»** → `inline URL button` на `https://<site>/mafia/admin/games/{id}/edit`, затем помечает `results_reminder_sent_at` (через `PUT`).
4. Админ логинится на сайте, открывает `/mafia/admin/games/{id}/edit` — там уже есть дата/место/состав (из `registrations`), нужно только доставить игровые роли и баллы по 10 участникам.
5. Сохранение переводит `status: played → rated`, задним числом заполняет `game_participants`, запускает пересчёт рейтинга.

Если админ вместо этого добавляет **полностью историческую** игру (которой не было в боте) — использует `POST /api/admin/games` и создаёт её сразу с `status=rated`, минуя запись/резерв.

---

## 9. Безопасность

### 9.1 Модель доверия бот ↔ API

Бот — доверенный сервисный клиент (не конечный пользователь): все вызовы `/api/bot/*` подписываются заголовком `Authorization: Bearer <BOT_SERVICE_TOKEN>` (случайный секрет ≥32 байт, хранится в `.env`, сверяется constant-time-сравнением). Сам `telegram_id` действующего пользователя бот передаёт в теле запроса — это безопасно, потому что подлинность `telegram_id` уже проверена на границе Telegram Bot API → бот (Telegram сам гарантирует, от кого апдейт), а бэкенд доверяет самому боту как единственному владельцу токена. Компрометация токена = компрометация бота целиком, поэтому:
- токен передаётся только по внутренней docker-сети (сервис `api` не публикуется наружу, только `nginx`);
- ротация токена не требует миграции БД (просто ENV);
- `/api/bot/*` дополнительно рейт-лимитится **по `telegram_id` из тела**, а не только по IP — иначе один пользователь бота сможет исчерпать лимит для всех (весь трафик бота идёт с одного IP).

### 9.2 Остальные пункты — как в v2 (без изменений по сути)

SQLi — только параметризованные запросы (SQLAlchemy); XSS — React-экранирование + Pydantic-валидация полей; CSRF — актуален только для `/api/admin/*` и `/api/auth/*` (JWT-cookie флоу), для `/api/bot/*` неприменим (нет cookie/браузера — это server-to-server); XXE/SSRF — векторы отсутствуют по построению (нет XML-парсинга, нет исходящих запросов по пользовательским URL); argon2id + блокировка после 5 неудачных попыток; JWT access 15 мин + refresh с ротацией; фото — валидация по содержимому + решейп через Pillow.

### 9.3 Rate limiting (обновлено)

- `/api/auth/login` — 5/мин/IP, 10/час/username;
- публичные `GET /api/*` — 60/мин/IP;
- `/api/admin/*` — 30/мин/пользователь (по JWT `sub`);
- `/api/bot/*` — 20/мин/`telegram_id` (не по IP — см. 9.1);
- `/api/bot/admin/*` — 30/мин/`telegram_id`.

### 9.4 Least privilege

Один `api_role` в Postgres с полными правами на единственную схему — сегментация ролей внутри системы теперь целиком на уровне приложения (`is_site_admin`/`is_bot_admin`), а не на уровне грантов БД, потому что писатель в БД теперь один (API). Это осознанный компромисс: проще эксплуатировать, но при компрометации самого API-процесса потенциальный blast radius больше, чем при раздельных ролях v2. Раз приоритет — единая архитектура, риск снимается на уровне приложения: строгая проверка авторизации в каждом эндпоинте (dependency `require_site_admin` / `require_bot_service` / `require_bot_admin`) плюс тесты на них.

---

## 10. Деплой (Docker Compose)

```yaml
services:
  postgres:
    image: postgres:16
    volumes: [pgdata:/var/lib/postgresql/data]

  redis:
    image: redis:7

  api:
    build: ./backend
    depends_on: [postgres, redis]
    environment:
      - DATABASE_URL       # api_role
      - JWT_SECRET
      - BOT_SERVICE_TOKEN
      - REDIS_URL
    # порт наружу НЕ пробрасывается — только через nginx по /api

  frontend:
    build: ./frontend
    depends_on: [api]
    environment: [NEXT_PUBLIC_API_URL]

  bot:
    build: ./bot/mafia-tg-bot
    depends_on: [api]
    environment:
      - BOT_TOKEN
      - API_BASE_URL        # http://api:8000, внутренний docker DNS
      - BOT_SERVICE_TOKEN
      - SITE_ADMIN_GAME_URL_TEMPLATE   # https://.../mafia/admin/games/{id}/edit
    # DB_DSN у бота больше нет вообще

  nginx:
    image: nginx
    ports: ["80:80", "443:443"]
    volumes: [media:/media/players:ro]
    depends_on: [frontend, api]
```

---

## 11. Миграция существующих данных бота (одноразовая, Alembic)

1. `ALTER TABLE users RENAME TO players;` + добавить новые колонки (`slug`, `age`, `favorite_role`, `experience`, `bio`, `photo_url`, `site_username`, `site_password_hash`, `is_site_admin`, `is_bot_admin`, `failed_login_attempts`, `locked_until`, `last_login_at`, `is_active DEFAULT true`).
2. Backfill `slug` транслитерацией ника (с последующей ручной правкой через админку при коллизиях/некрасивых значениях — см. допущение №2).
3. `UPDATE players SET is_bot_admin = true WHERE id IN (SELECT ... FROM admins JOIN ... ON tg_id)`; затем `DROP TABLE admins`.
4. `ALTER TABLE pending_admins RENAME TO pending_bot_admins;`
5. `games`: добавить `status game_status DEFAULT 'scheduled'`, `result`, `results_reminder_sent_at`, `notes`, `created_by`, `max_players`; конвертировать `starts_at`/`registration_until` из текста в `TIMESTAMPTZ` через `to_timestamp(col, 'DD.MM.YYYY HH24:MI')`; проставить `status='played'` для игр, чьё время уже прошло на момент миграции.
6. `registrations`/`reserves` — типы `game_id`/`user_id → player_id` не меняются по значениям, переименовать колонку `user_id → player_id`.
7. Создать новые таблицы: `game_participants`, `player_rating`, `player_rating_history`, `audit_log`.
8. Прогнать `RatingService.recompute_all()` один раз вручную после того, как первые исторические игры будут занесены в `game_participants` (изначально пусто — рейтинг появится по мере ввода результатов).

---

## 12. План реализации (обновлён)

1. Миграция БД (раздел 11).
2. Backend: единый FastAPI-проект, все 4 группы эндпоинтов (раздел 4), `RatingService`, JWT+CSRF для сайта, `BOT_SERVICE_TOKEN`-мидлварь для бота, rate limiting.
3. Bot: заменить `app/db/database.py` на `app/api_client.py` (httpx), прогнать все хэндлеры (`registration.py`, `profile.py`, `schedule.py`, `admin.py`, `common.py`) на вызовы API вместо SQL. Добавить APScheduler-джобу для напоминаний и «Оценить игру».
4. Frontend: публичные страницы (`/mafia`, `/games`, `/rating`, `/[slug]`).
5. Frontend: `/mafia/admin`.
6. Интеграционное тестирование бот↔API↔сайт на одном датасете (запись в боте → «Оценить игру» → результат виден в рейтинге).
7. Нагрузочный прогон `recompute_all()`, аудит-лог, финальный security-ревью.

---

## 13. Открытые вопросы / допущения

1. **«ППК»** (упоминается в PDF рейтинга) — как и в v2, реализовано как булев флаг `ppk` в `game_participants`, вводимый вручную. Подтвердите формулировку/точное определение.
2. **`slug`** — авто-предложение транслитерацией ника при регистрации в боте, редактируется вручную в веб-админке (пример «Шеф» → `chef` — это перевод, не транслит, автоматика его не даст).
3. **Фото** — volume + Nginx по умолчанию, легко заменить на S3/MinIO через интерфейс `PhotoStorage`.
4. **Сайт-логин для не-игроков** — `players.nickname` обязателен, поэтому чистый «системный» сайт-админ без игровой карточки технически должен получить player-строку с ником (например, реальным именем). Если нужны полностью отдельные тех.аккаунты без привязки к игроку — скажите, вынесу `site_admin_users` отдельной таблицей.
5. **Формат уведомлений от бота** («Оценить игру», напоминания за час) реализуется поллингом бота по API (APScheduler), а не пушем от API к боту — так бот остаётся единственным компонентом, знающим про Telegram, а API ничего не знает о боте кроме токена. Если нужна мгновенная доставка без задержки поллинга — можно добавить вебхук API → бот, но это усложнение сверх ТЗ.
