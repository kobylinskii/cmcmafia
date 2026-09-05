# Архитектура «Мафия ВМК»

Клуб спортивной мафии ведёт сайт (`/mafia/*`) и Telegram-бота одной системой:
**один FastAPI-бэкенд, одна база Postgres, один источник правды** для всего —
рейтинга, статистики, записи на игры и турнирной сетки. Сайт и бот — два
клиента одного и того же API, различаются только способом авторизации.

Этот документ описывает систему **как она есть сейчас** (реальный код, а не
план). Как запустить каждую часть — см. корневой [README.md](README.md).

---

## Оглавление

1. [Общая схема](#1-общая-схема)
2. [Стек технологий](#2-стек-технологий)
3. [Схема базы данных](#3-схема-базы-данных)
4. [Единый API](#4-единый-api)
5. [Жизненный цикл игры](#5-жизненный-цикл-игры)
6. [Рейтинг (Эло)](#6-рейтинг-эло)
7. [Турниры и этапы](#7-турниры-и-этапы)
8. [Статистика игрока](#8-статистика-игрока)
9. [Backend — структура кода](#9-backend--структура-кода)
10. [Frontend — структура кода](#10-frontend--структура-кода)
11. [Telegram-бот — структура кода](#11-telegram-бот--структура-кода)
12. [Фоновые задачи](#12-фоновые-задачи)
13. [Безопасность](#13-безопасность)
14. [Деплой (Docker Compose + nginx)](#14-деплой-docker-compose--nginx)
15. [Тестирование](#15-тестирование)

---

## 1. Общая схема

```
                         ┌───────────────────────────┐
                         │        PostgreSQL 16          │
                         │      (одна схема public)      │
                         └──────────────▲─────────────────┘
                                        │ единственный писатель
                         ┌──────────────┴─────────────────┐
                         │           Backend API              │
                         │      FastAPI, один процесс          │
                         │  /api/*            — сайт (public)   │
                         │  /api/auth/*       — вход/сессия сайта│
                         │  /api/admin/*      — сайт-админка      │
                         │  /api/bot/*        — бот (пользователь) │
                         │  /api/bot/admin/*  — бот-админка         │
                         │  rating_service (Эло-реплей)              │
                         │  фоновая задача: scheduled/played → played│
                         └──────▲──────────────────────────▲────────┘
                                │ REST/JSON                    │ REST/JSON
                                │ JWT httpOnly-cookie + CSRF   │ Bearer BOT_SERVICE_TOKEN
                                │ (браузер)                    │ (сервис-к-сервису)
                   ┌────────────┴────────┐         ┌────────────┴─────────────┐
                   │      Frontend           │         │      Telegram-бот         │
                   │  Next.js 16 App Router  │         │  aiogram 3, long polling,  │
                   │  + TypeScript + Tailwind│         │  тонкий HTTP-клиент к API,  │
                   └────────────────────────┘         │  сам в Postgres не ходит    │
                                                        └──────────────┬────────────┘
                                                                       │
                                                                       ▼
                                                                Telegram Bot API
```

Один Postgres-логин на всё, одна Alembic-история миграций, один набор
Pydantic-схем. Бот **не имеет доступа к БД напрямую** — вся его логика идёт
через `/api/bot/*`, авторизованные общим сервисным токеном.

---

## 2. Стек технологий

| Слой | Технология | Версия (см. lock-файлы) |
|---|---|---|
| БД | PostgreSQL | 16 |
| Backend | FastAPI + Pydantic v2 + SQLAlchemy 2.0 (declarative `Mapped`) + Alembic | fastapi 0.115, sqlalchemy 2.0.36, alembic 1.14 |
| Auth сайта | argon2id (`argon2-cffi`) + JWT (`python-jose`, HS256) в httpOnly-cookie + CSRF double-submit | — |
| Auth бота | `BOT_SERVICE_TOKEN` — статичный Bearer-секрет, сверяется constant-time | — |
| Rate limiting | `slowapi` + Redis-хранилище счётчиков | slowapi 0.1.9, redis 5.2 |
| Фото | Pillow (валидация по содержимому, решейп, конвертация в JPEG) | Pillow 11 |
| Frontend | Next.js 16 (App Router, Turbopack) + React 19 + TypeScript 5 + Tailwind CSS 4 | next 16.3.4, react 19.2 |
| Бот | aiogram 3.x, `httpx.AsyncClient` вместо psycopg | aiogram ≥3.6 |
| Веб-сервер | nginx (реверс-прокси перед frontend и API, раздаёт `/media/players` напрямую с volume) | nginx:alpine |
| Хостинг | Docker Compose: `postgres`, `redis`, `api`, `frontend`, `bot`, `nginx` | — |

Next.js 16 заменил файловый `middleware.ts` на `src/proxy.ts` (`export function
proxy(...)`) — если гуглите старый API `middleware`, он в этой версии не
работает.

---

## 3. Схема базы данных

Все таблицы живут в одной схеме `public`, модели — `backend/app/models.py`
(SQLAlchemy 2.0, `Mapped[...]`), актуальная DDL — цепочка миграций в
`backend/alembic/versions/`.

### 3.1 Люди

```sql
-- Одна таблица на человека: игрок с сайта, пользователь бота, бот-админ,
-- сайт-админ — всё это флаги/поля одной и той же строки.
players (
    id                     SERIAL PRIMARY KEY,

    -- профиль (публичная карточка игрока на сайте)
    slug                   VARCHAR(50) UNIQUE NOT NULL CHECK (slug ~ '^[a-z0-9][a-z0-9-]{1,48}[a-z0-9]$'),
    nickname               VARCHAR(100) UNIQUE NOT NULL,
    full_name              VARCHAR(150),
    age                    SMALLINT,
    favorite_role          VARCHAR(10),        -- mafia|don|sheriff|citizen
    experience             TEXT,
    bio                    TEXT,
    photo_url              TEXT,

    -- поля бота
    telegram_id            BIGINT UNIQUE,
    telegram_username      VARCHAR(100),
    phone                  VARCHAR(20) UNIQUE, -- нормализовано, только цифры
    salutation             VARCHAR(20),
    affiliation            VARCHAR(20),        -- vmk|mgu_no_pass|outside_need_pass
    can_play               BOOLEAN NOT NULL DEFAULT TRUE,
    can_staff              BOOLEAN NOT NULL DEFAULT TRUE,

    -- доступ в веб-админку
    site_username          VARCHAR(50) UNIQUE,
    site_password_hash     TEXT,               -- argon2id
    is_site_admin          BOOLEAN NOT NULL DEFAULT FALSE,
    failed_login_attempts  SMALLINT NOT NULL DEFAULT 0,
    locked_until           TIMESTAMPTZ,
    last_login_at          TIMESTAMPTZ,

    -- права в боте
    is_bot_admin           BOOLEAN NOT NULL DEFAULT FALSE,

    is_active              BOOLEAN NOT NULL DEFAULT TRUE,  -- soft-delete
    created_at, updated_at TIMESTAMPTZ
);

-- Приглашение в бот-админы по @username, пока человек не написал боту /start
-- (заявка выдаётся автоматически при регистрации, см. admin_grant.consume_pending_admin).
pending_bot_admins (id, username UNIQUE, created_at)
```

`is_site_admin` сейчас означает ровно одно — «может входить в `/mafia/admin`»;
отдельной низкопривилегированной сайт-роли нет.

### 3.2 Турниры

```sql
tournaments (
    id, slug UNIQUE, name UNIQUE, description, location,
    starts_at TIMESTAMPTZ NOT NULL,   -- период проведения; обязателен у ЛЮБОГО
    ends_at   TIMESTAMPTZ NOT NULL,   -- турнира, даже без этапов (CHECK ends_at >= starts_at)
    created_at, updated_at
)

-- Этап турнира (сетка по олимпийской системе для >10 участников).
-- Существует ТОЛЬКО когда турниру нужна квалификация.
tournament_stages (
    id, tournament_id → tournaments ON DELETE CASCADE,
    name VARCHAR(150),                -- свободный текст ("Отборочный стол 1", "Финал")
    order SMALLINT DEFAULT 1,         -- порядок показа, не обязательно = порядку создания
    is_final BOOLEAN DEFAULT FALSE,   -- максимум один true на турнир
    created_at, updated_at,
    UNIQUE (tournament_id, name)
)

-- Кто прошёл с этапа дальше. Наличие строки и значит "прошёл" — ставится
-- админом вручную одним разом по всей сводной таблице этапа.
tournament_stage_advances (stage_id, player_id, created_at, PK (stage_id, player_id))
```

### 3.3 Игры

```sql
games (
    id,
    starts_at              TIMESTAMPTZ NOT NULL,  -- дата+время; также ключ хронологии для Эло
    location               VARCHAR(200),
    game_type              VARCHAR(20) DEFAULT 'tournament', -- tournament|funky|training
    registration_until     TIMESTAMPTZ,           -- NULL для игр, заведённых сразу как исторические
    max_players            SMALLINT DEFAULT 10,

    status                 VARCHAR(30) DEFAULT 'scheduled', -- см. раздел 5
    result                 VARCHAR(10),           -- city_win|mafia_win|draw
    results_reminder_sent_at TIMESTAMPTZ,         -- зарезервировано, сейчас не используется ботом

    notes                  TEXT,
    tournament_id → tournaments ON DELETE RESTRICT,  -- NULL для funky/training
    stage_id      → tournament_stages ON DELETE RESTRICT, -- NULL, если у турнира нет сеток
    created_by → players,
    created_at, updated_at,

    CHECK (status <> 'rated' OR result IS NOT NULL),
    CHECK (status <> 'rated' OR game_type <> 'tournament' OR tournament_id IS NOT NULL)
)

-- Запись на игру ДО неё (кто поведёт/посудит/сыграет). Одна строка на человека.
registrations (id, game_id ON DELETE CASCADE, player_id ON DELETE CASCADE, role, available_from, available_until, created_at,
               UNIQUE (game_id, player_id))
reserves       (id, game_id ON DELETE CASCADE, player_id ON DELETE CASCADE, created_at, UNIQUE (game_id, player_id))

-- Результат ПОСЛЕ игры: 10 мест, игровые роли, баллы. Сознательно отдельная
-- от registrations таблица — до игры человек занимает организационную роль
-- (ведущий/судья/игрок), после — конкретное место с игровой ролью и баллами.
game_participants (
    id, game_id ON DELETE CASCADE, player_id ON DELETE RESTRICT,
    seat_number SMALLINT CHECK (1..10),
    role        VARCHAR(10),          -- mafia|don|sheriff|citizen

    points_win   NUMERIC(4,2) DEFAULT 0,
    points_judge NUMERIC(4,2) DEFAULT 0,
    lh           NUMERIC(3,2),        -- ПОПАДАНИЯ ЛХ (0/0.5/1/1.5 = 0/3..3/3 названных чёрных), не баллы!
    ci           NUMERIC(5,2),        -- компенсация
    info         VARCHAR(20),         -- first_killed|killed|voted_out
    removals     SMALLINT,
    ppk          BOOLEAN DEFAULT FALSE,
    zk           NUMERIC(3,1),        -- штраф "ЖК"
    sk           NUMERIC(3,1),        -- штраф "СК"

    UNIQUE (game_id, seat_number), UNIQUE (game_id, player_id)
)
```

`player_id` в `game_participants` — `ON DELETE RESTRICT`: игрока с историей
сыгранных игр нельзя удалить из базы физически, только `soft-delete`
(`is_active = false`, см. `player_service.delete_player`).

### 3.4 Рейтинг и аудит

```sql
player_rating (player_id PK, rating NUMERIC(7,2) DEFAULT 1000, games_count, wins, losses, draws, updated_at)

player_rating_history (
    id, player_id, game_id,
    rating_before, rating_after, delta,
    k_coefficient, expected_score, sa, penalty,
    UNIQUE (player_id, game_id)
)

audit_log (id, actor_id, actor_kind ('site'|'bot'), action, entity, entity_id, diff JSONB, created_at)
```

`player_rating`/`player_rating_history` полностью **перестраиваются** при
каждом пересчёте (`DELETE` + заново), а не обновляются инкрементально — см.
раздел 6. Таблица `audit_log` определена в схеме, но на данный момент в неё
никто не пишет — задел на будущее, не действующий механизм.

### 3.5 Индексы (основные)

```sql
idx_players_active, idx_players_is_bot_admin (partial WHERE is_bot_admin)
idx_games_starts_at (starts_at, id), idx_games_status, idx_games_tournament, idx_games_stage
idx_registrations_player, idx_registrations_game
idx_participants_player, idx_participants_game
idx_rating_current (rating)
```

### 3.6 Зарезервированные `slug`

Игроки и турниры используют человекочитаемые URL (`/mafia/<slug>`,
`/mafia/tournaments/<slug>`), поэтому часть значений зарезервирована системой
(`slug_service.RESERVED_SLUGS`): `games, rating, admin, api, login, static,
assets, favicon.ico, robots.txt, sitemap.xml, _next, mafia, tournaments`.

---

## 4. Единый API

Один FastAPI-процесс (`app/main.py`), пять роутеров с разными моделями
авторизации.

```
# ================= PUBLIC (app/routers/public.py) — читает кто угодно, только rate limit =================
GET  /api/games                    ?limit=&offset=&date_from=&date_to=&game_type=&player_slug=&tournament_slug=
GET  /api/games/{id}
GET  /api/rating                   ?q=&limit=&offset=
GET  /api/rating/formula           — формула и текущие коэффициенты, вычисленные из тех же функций, что реплей
GET  /api/stats                    — счётчики для главной (игр/игроков/турниров)
GET  /api/tournaments
GET  /api/tournaments/{slug}       — общая таблица + таблицы этапов + is_final + пронумерованные игры этапа
GET  /api/players
GET  /api/players/{slug}           — профиль + PlayerStats (см. раздел 8)

# ================= AUTH (app/routers/auth.py) =================
POST /api/auth/login               — 5/мин/IP; блокировка на N минут после 5 неверных попыток
POST /api/auth/refresh             — обменивает refresh-cookie на новую пару access+refresh+csrf
POST /api/auth/logout
POST /api/auth/password            — смена пароля себе (требует текущий пароль)
GET  /api/auth/me

# ================= SITE ADMIN (app/routers/admin.py; JWT-cookie + CSRF, is_site_admin=true) =================
GET    /api/admin/games                              — только funky/training, оценённые (турнирные — см. ниже)
POST   /api/admin/games                               — создать funky/training игру сразу как rated
GET    /api/admin/games/pending-review                — бот-сессии: status='played', результат ещё не внесён
GET    /api/admin/games/{id}
PUT    /api/admin/games/{id}                           — правка/оценка (played → rated при вводе результата)
DELETE /api/admin/games/{id}

GET/POST/PUT/DELETE /api/admin/tournaments[/{id}]      — CRUD турнира (name, slug, даты, описание, место)
GET  /api/admin/tournaments/slug-suggestion
GET  /api/admin/tournaments/{id}/games                 — слоты БЕЗ этапа (простой турнир, см. раздел 7)
POST /api/admin/tournaments/{id}/games                 — добавить N пустых слотов
GET/POST/PUT/DELETE /api/admin/tournaments/{id}/stages[/{stage_id}]  — CRUD этапа (games_count, is_final)
GET  /api/admin/tournaments/{id}/stages/{stage_id}/games              — слоты этапа
POST /api/admin/tournaments/{id}/stages/{stage_id}/games              — добавить ещё N слотов
GET  /api/admin/tournaments/{id}/stages/{stage_id}/standings          — сводная + кто уже отмечен прошедшим
PUT  /api/admin/tournaments/{id}/stages/{stage_id}/advances           — заменить список прошедших дальше

GET/POST/PUT/DELETE /api/admin/players[/{id}]
GET  /api/admin/players/slug-suggestion
POST /api/admin/players/{id}/photo
POST/DELETE /api/admin/players/{id}/site-access        — выдать/отозвать сайт-логин
GET/POST/DELETE /api/admin/bot-admins[/{player_id}]     — {telegram_id | username}

# ================= TELEGRAM USER (app/routers/bot.py; Bearer BOT_SERVICE_TOKEN + telegram_id в теле/query) =================
POST /api/bot/players/register
GET/PUT /api/bot/players/me
GET  /api/bot/game-days                ?game_type=&telegram_id=
GET  /api/bot/sessions/open            ?game_type=&day=
GET  /api/bot/sessions/{id}
POST /api/bot/sessions/{id}/register   — {telegram_id, role_kind: player|staff}
POST /api/bot/sessions/{id}/reserve
DELETE /api/bot/sessions/{id}/registration — авто-промоушен из резерва, ответ несёт promoted_telegram_id
GET  /api/bot/sessions/{id}/roster
GET  /api/bot/registrations/mine

# ================= TELEGRAM ADMIN (app/routers/bot_admin.py; тот же токен + is_bot_admin у переданного telegram_id) =================
POST/PUT/DELETE /api/bot/admin/sessions[/{id}]     — funky/training ТОЛЬКО (game_type='tournament' отклоняется 422)
POST /api/bot/admin/sessions/bulk                   — пачка слотов на день
POST /api/bot/admin/sessions/check-conflicts
GET  /api/bot/admin/sessions/day-cards              ?game_type=
GET  /api/bot/admin/sessions/by-day                 ?day=
GET  /api/bot/admin/sessions/pending-review
GET  /api/bot/admin/players/by-username | by-phone
GET/POST/DELETE /api/bot/admin/admins[...]           — тот же admin_grant.grant_bot_admin, что и с сайта
```

`POST /api/admin/bot-admins` и `POST /api/bot/admin/admins` вызывают **один и
тот же** сервисный метод `admin_grant.grant_bot_admin(...)` — правами бот-админа
можно управлять и с сайта, и из чата бота, потому что под капотом это ровно
одна операция над одной таблицей.

Важно: **турнирные игры нельзя создать ни через `/api/admin/games`, ни через
бота** — единственный путь описан в разделе 7.

---

## 5. Жизненный цикл игры

```
scheduled ──► (registration_closed, не используется сейчас) ──► played ──► rated
```

- **scheduled** — слот создан (ботом как сессия для записи, либо на сайте как
  пустой турнирный слот), `starts_at` в будущем.
- **registration_closed** — значение определено в модели и проверяется в
  `CHECK`, но на практике сейчас ничем не выставляется — зарезервировано под
  будущую фичу «закрыть запись раньше начала игры».
- **played** — фоновая задача (`app/tasks.py`) перевела прошедший `scheduled`
  в `played`, когда `starts_at` в прошлом. Турнирные слоты этим свипом
  специально **не трогаются** (см. `game_service.mark_past_sessions_as_played`)
  — они не проходят через "ждут оценки" на общей вкладке, у них своя очередь
  внутри этапа/турнира.
- **rated** — результат внесён (`game_participants` заполнены, `result`
  проставлен), рейтинг пересчитан. Обратного пути из `rated` нет, кроме
  повторного `PUT` с новыми данными или `DELETE`.

Два независимых способа попасть в `rated`:

1. **Бот-игра**: `POST /api/bot/admin/sessions` (funky/training) → игроки
   записываются через `registrations`/`reserves` → фоновая задача переводит в
   `played`, когда время прошло → сайт-админ открывает
   `/mafia/admin/games/{id}/edit`, видит уже подставленный состав (roster) из
   записей бота и расставляет 10 реальных мест/ролей/баллов → `PUT`
   переводит `played → rated`.
2. **Турнирная игра**: слот создаётся сразу на сайте, без всякой записи (см.
   раздел 7) → тот же экран оценки (`GameOut.roster` для турнирного слота
   всегда пуст — расставлять некого) → `PUT` переводит `scheduled → rated`
   напрямую.
3. **Полностью историческая игра** (её не было ни в боте, ни как турнирный
   слот): `POST /api/admin/games` создаёт funky/training игру сразу как
   `rated`, минуя запись.

---

## 6. Рейтинг (Эло)

Формула — `backend/app/services/rating_service.py`, полный реплей истории
(не инкремент): рейтинг зависит от хронологического порядка, поэтому при
любом `create/update/delete` рейтинговой игры `rating_service.recompute_all()`
удаляет `player_rating`/`player_rating_history` целиком и строит их заново по
`games WHERE status='rated' ORDER BY starts_at, id`, в одной транзакции с
изменением игры.

```
R'a = Ra + weight(game_type) · [ K · (Sa − E · M) / M − O ]

Sa = points_win + points_judge + lh_points(lh) + ci
M  = 7                                     — размер команды
E  = clamp(1 / (1 + 10^((R_opp − R_own)/400)), 0.3, 0.7)
     считается ОТДЕЛЬНО для каждой из двух команд (по среднему рейтингу ДО игры),
     поэтому E_own + E_opp не обязаны давать ровно 1 — оба со своим clamp.

K (по числу рейтинговых игр игрока и его рейтингу ДО игры):
    games_before < 30           → 40
    games_before ≥ 30, R ≤ 2000  → 20
    games_before ≥ 30, R > 2000  → 10

O = removals · removal_rate + (ppk ? ppk_rate : 0), где (removal_rate, ppk_rate):
    games_before < 30           → (8, 15)
    games_before ≥ 30, R ≤ 2000  → (5, 10)
    games_before ≥ 30, R > 2000  → (3, 5)

weight(game_type):  tournament = 1.0,  funky = 0.3,  training = 0.0 (не участвует вовсе)
```

Команды: чёрные = `mafia + don`, красные = `citizen + sheriff`.

`lh` хранит **попадания** легендарного хода, а не баллы: 0 / 0.5 / 1 / 1.5 в
БД означают 0/3, 1/3, 2/3, 3/3 названных чёрных. В очки они переводятся так:
0/3 и 1/3 → 0 баллов, 2/3 → 0.5, 3/3 → 1 (`rating_service.LH_POINTS`, зеркало —
`stats_service._LH_POINTS_SQL`, держать в синхроне вручную).

**Обучающие игры (`training`) не участвуют в реплее вообще** — не только не
двигают рейтинг, но и не увеличивают `games_count`, от которого зависит K.
Раньше нулевой вес без исключения из реплея всё равно косвенно «взрослил»
игрока. В личной статистике (`/api/players/{slug}`) они при этом учитываются.

`GET /api/rating/formula` отдаёт текст и таблицу коэффициентов, **вычисленные
теми же функциями**, что и сам реплей (`_k_coefficient`, `_penalty_rates`,
`GAME_TYPE_WEIGHT`) — правки порогов в одном месте не могут разойтись с
текстом на сайте.

---

## 7. Турниры и этапы

Полная модель — `backend/app/services/tournament_service.py` +
`app/routers/admin.py` (раздел «Турниры») + публичная страница
`/mafia/tournaments/[slug]`.

### 7.1 Турнир

У каждого турнира обязателен период проведения (`starts_at`/`ends_at`,
`ends_at >= starts_at`) — даже у самого простого, однодневного. Это не только
информация для посетителей: `starts_at` служит **плейсхолдер-датой** для
только что созданных игровых слотов, точную дату каждой конкретной игры админ
проставляет потом вручную (турнир обычно идёт несколько дней подряд или с
недельным интервалом).

### 7.2 Два формата турнирной таблицы

- **Простой турнир** (≤10 участников, играется одна серия из N игр): слоты
  добавляются прямо на турнир, без этапа (`GET/POST
  /api/admin/tournaments/{id}/games`, `Game.stage_id = NULL`). Публичная
  страница показывает одну общую таблицу.
- **Турнир с сеткой** (>10 участников, отбор + финал по олимпийской системе):
  заводятся этапы (`TournamentStage`), каждый — со своим свободным названием,
  порядком показа и числом игр. Как только у турнира есть **хотя бы один**
  этап, каждая его игра обязана принадлежать конкретному этапу — иначе
  сводная таблица снова смешала бы несопоставимые составы (см.
  `game_service._resolve_stage`).

### 7.3 Слоты создаются заранее, оцениваются потом

Турнирную игру нельзя создать одним запросом с готовым результатом — сначала
заводится **пустой слот**:

```
POST /api/admin/tournaments/{id}/games                {"count": N}         — без этапа
POST /api/admin/tournaments/{id}/stages               {"name", "games_count": N, "is_final"} — сразу с N слотами
POST /api/admin/tournaments/{id}/stages/{sid}/games    {"count": N}         — добавить ещё слотов
```

Каждый слот — обычная строка `games` (`game_type='tournament'`,
`status='scheduled'`, `starts_at` = дата турнира-плейсхолдер, без участников).
Оценивается он той же самой общей формой/ручкой, что и игра из бота —
`PUT /api/admin/games/{id}` с участниками и результатом. Разница только в
том, что у турнирного слота `GameOut.roster` всегда пуст (расставлять
некого — состав вводится сразу целиком).

Привязка слота к турниру/этапу **фиксируется один раз, при создании**, и
дальше неизменна: `game_service.update_rated_game` игнорирует
`tournament_id`/`stage_id` в теле запроса, если игра уже `game_type='tournament'`.
Переставить оценённую игру на другой этап через эту форму нельзя — только
удалить слот и создать заново в нужном месте (пустой слот с `status='scheduled'`
удаляется свободно, `DELETE /api/admin/games/{id}`; рейтинг при этом не
трогается, т.к. `was_rated=False`).

### 7.4 Единый состав на всю таблицу

Все игры одной турнирной таблицы (сам турнир без сеток — или конкретный
этап) обязаны собирать **один и тот же состав из 10 игроков**. Первая
оценённая игра таблицы неявно фиксирует состав; при оценке любой следующей
игры этой же таблицы `game_service._validate_tournament_roster_consistency`
сверяет набор `player_id` с любой уже оценённой игрой-соседкой и отклоняет
422, если состав отличается хоть одним игроком. Без этого сумма очков по
таблице теряла бы смысл — кто-то сыграл бы 3 игры, кто-то одну.

### 7.5 Финальный этап и кто прошёл дальше

Ровно один этап турнира может быть отмечен `is_final=true`
(`tournament_service._unset_other_final_stages` снимает флаг с остальных при
установке нового). На публичной странице турнира таблица финального этапа
развёрнута по умолчанию, остальные этапы свёрнуты в отдельные окошки
(`frontend/src/components/tournaments/stage-accordion.tsx`); внутри
развёрнутого этапа отдельной кнопкой поднимается пронумерованный список его
игр (сыгранные ведут на карточку игры, ещё не сыгранные просто занимают
номер в очереди).

Кто прошёл с этапа дальше — отмечает администратор вручную, разом по всей
сводной таблице этапа (`PUT .../stages/{id}/advances`, заменяет весь список
целиком), когда все игры этапа уже сыграны. Автоматического правила прохода
нет.

### 7.6 Удаление турнира/этапа

Турнир или этап с уже **оценёнными** играми удалить нельзя (сначала
переносят игры в другой турнир/этап — `ON DELETE RESTRICT` в БД плюс явная
проверка в сервисе с понятным текстом ошибки). Ещё не оценённые
(`scheduled`) слоты — просто пустые заготовки, они удаляются вместе с
турниром/этапом безо всякого переноса.

### 7.7 Бот турниры больше не видит

С момента введения этой модели турнирная сетка целиком живёт на сайте.
Бот (`app/schemas/bot.py`, `GAME_TYPES = {"funky", "training"}`) физически
не может создать сессию с `game_type='tournament'` — попытка получает 422 на
уровне Pydantic-валидатора. Регистрация на игру и bulk-создание слотов дня
(`registration_service.list_open_sessions`,
`schedule_admin_service.day_cards/games_by_day`) явно исключают турнирные
слоты фильтром `game_type != 'tournament'`, иначе плейсхолдер-слоты этапа
(со статусом `scheduled` и датой, которая может уже быть в прошлом) попали бы
в список открытых для записи игр или в список дня в боте.

---

## 8. Статистика игрока

`GET /api/players/{slug}` — один агрегирующий SQL-запрос
(`stats_service.compute_player_stats`) с `COUNT(...) FILTER (WHERE ...)` по
`game_participants JOIN games WHERE status='rated'`, плюс отдельно текущий
рейтинг/ранг из `player_rating`. Считает: игры/победы/поражения/ничьи по
командам и отдельно по ролям дона/шерифа, число раз «убит первым», разбивку
попаданий ЛХ (0/3..3/3) отдельно от начисленных за них баллов, средний балл
за игру (`_SCORE_SQL`) и средний дополнительный балл (`_BONUS_SQL` — только
судейские + ЛХ, без Ci — это компенсация, а не заработанный балл).

Та же `_SCORE_SQL` используется и в `tournament_standings` (сумма даёт
колонку «Итог» турнирной таблицы) — формула линейна по каждому слагаемому,
поэтому сумма итогов по играм турнира равна итогу от суммы колонок, эта
формула не переписывается для турнирной таблицы отдельно.

---

## 9. Backend — структура кода

```
backend/app/
  main.py            — сборка FastAPI-приложения, CORS, lifespan (запуск фоновой задачи),
                        подключение всех роутеров, /health
  config.py          — Settings (pydantic-settings, .env)
  database.py        — engine/SessionLocal/Base, get_db() dependency
  models.py          — единая SQLAlchemy-схема (раздел 3)
  security.py        — argon2id, JWT encode/decode, CSRF-токен, сверка bot-токена
  deps.py            — FastAPI-зависимости авторизации: get_current_site_user,
                        require_csrf, require_site_admin, require_bot_service,
                        get_bot_actor, require_bot_admin_actor
  rate_limit.py       — slowapi Limiter с единой key-функцией (IP / telegram_id / сессия
                        сайта — см. раздел 13)
  timeutil.py         — единая точка конвертации UTC ↔ Europe/Moscow при группировке
                        игр по календарному дню
  tasks.py            — фоновая задача перевода прошедших игр в 'played' (раздел 12)

  routers/
    public.py         — /api/* (не требует авторизации)
    auth.py            — /api/auth/*
    admin.py           — /api/admin/* (сайт-админка)
    bot.py              — /api/bot/* (пользователь бота)
    bot_admin.py         — /api/bot/admin/*

  services/            — бизнес-логика без привязки к HTTP
    player_service.py    — CRUD игрока, фото, выдача/отзыв сайт-доступа
    slug_service.py       — транслитерация/валидация/резерв slug'ов
    game_service.py        — CRUD рейтинговой игры, resolve турнира/этапа, свип
                              past-sessions, проверка единого состава таблицы
    tournament_service.py  — CRUD турнира и этапов, bulk-создание слотов, is_final
    registration_service.py— запись/резерв/отмена с авто-промоушеном (для бота)
    schedule_admin_service.py — bulk-создание слотов дня, конфликты, обзор по дням (бот)
    rating_service.py       — Эло-реплей (раздел 6)
    stats_service.py         — публичные списки игр, рейтинг-таблица, турнирные
                                таблицы, персональная статистика
    admin_grant.py            — выдача/отзыв бот-админства (общий код для сайта и бота)
    bootstrap_admin_service.py — первый бот-админ по конфигу (SUPERADMIN_TELEGRAM_IDS /
                                  BOOTSTRAP_ADMIN_PHONE), без этого — самопожалование прав

  schemas/              — Pydantic v2, по одному модулю на предметную область
    auth.py, player.py, game.py, tournament.py, rating.py, bot.py

  scripts/
    create_admin.py     — единственный способ завести самого первого сайт-админа
                            (CLI, см. README.md)
```

---

## 10. Frontend — структура кода

Next.js 16 App Router, `/mafia` — префикс всего сайта (namespace, чтобы
уживаться с прочими проектами на том же домене).

```
frontend/src/
  proxy.ts                    — гейт по наличию refresh-cookie перед /mafia/admin/*
                                 (не источник истины — сервер всё равно проверяет каждый
                                 запрос через require_site_admin; только не мигает админкой
                                 анонимному посетителю)
  lib/api.ts                   — clientFetch(): fetch с credentials:"include",
                                  CSRF-заголовком на мутациях, авто-refresh при 401
                                  (конкурентные 401 шарят один refresh-запрос)
  lib/api-server.ts             — serverGet(): прямой fetch с сервера Next.js к API по
                                   внутреннему docker-адресу (API_INTERNAL_URL), без cookie
  lib/format.ts                  — форматирование дат в клубной таймзоне (Europe/Moscow),
                                    конвертация значений <input type="date"> туда и обратно

  app/mafia/(site)/               — публичные страницы (Server Components, всегда свежие)
    page.tsx                       — главная
    games/, games/[gameId]/         — список и карточка игры
    rating/                          — таблица рейтинга + описание формулы
    [slug]/                          — профиль игрока
    tournaments/, tournaments/[slug]/ — список турниров и страница турнира (аккордеон этапов)

  app/mafia/admin/                 — админка (Client Components, сессия через cookie)
    login/                          — форма входа (единственная страница вне гейта proxy.ts)
    (dashboard)/                    — всё остальное: обзор, игры, турниры, игроки, смена пароля

  components/
    admin/                          — game-form, tournament-form, tournament-stages-manager,
                                       player-form, player-combobox, admin-shell, confirm-dialog…
    games/, home/, player/, rating/, tournaments/, ui/ — публичные виджеты
```

Ключевые тонкости, которые легко сломать заново:

- `next.config.ts`'ы `NEXT_PUBLIC_API_URL`-фоллбэк обязан совпадать с
  `lib/api.ts`'ым — иначе `next/image`-оптимизатор отказывается грузить
  фотографии игроков (не в allow-list удалённых хостов).
- Даты турнира — `<input type="date">` (не `datetime-local`): это плейсхолдер
  периода, а не точное время; `lib/format.ts` конвертирует в/из ISO через
  фиксированное смещение Москвы (+03:00, без перехода на летнее время с 2014).
- Форма игры (`GameForm`) на вкладке «Игры» создаёт и редактирует только
  funky/training; для существующей турнирной игры турнир/этап показываются
  read-only — переставить их оттуда нельзя (см. раздел 7.3).

---

## 11. Telegram-бот — структура кода

`aiogram 3`, long polling (`Dispatcher.start_polling`, без вебхука). Бот —
тонкий клиент: вся работа с данными идёт через `ApiClient` (`httpx`), сам он
Postgres не видит.

```
bot/mafia-tg-bot/
  bot.py                    — точка входа: конфиг, Bot/Dispatcher, регистрация роутеров,
                               подавление безобидных ошибок Telegram API (устаревший callback)
  app/config.py               — BOT_TOKEN / API_BASE_URL / BOT_SERVICE_TOKEN из .env
  app/api_client.py            — HTTP-клиент ко всем /api/bot/* и /api/bot/admin/* эндпоинтам
  app/states.py                 — aiogram FSM-состояния (регистрация, редактирование профиля)
  app/keyboards/inline.py, reply.py — клавиатуры; GAME_TYPE_LABELS теперь без "Турнир"
  app/handlers/
    common.py                   — /start, общий fallback
    registration.py               — первичная регистрация нового пользователя
    profile.py                     — просмотр/редактирование своего профиля
    schedule.py                     — запись на игру (фанки/обучающие), резерв, свои
                                       регистрации со сменой этапа/отменой
    admin.py                        — админ-меню: создание/редактирование/удаление игровых
                                       дней (тоже только фанки/обучающие), назначение и снятие
                                       бот-админов
```

Бот **больше не создаёт и не показывает турнирные игры** — ни в меню записи,
ни в админской пачке слотов дня: вся сетка турниров ведётся на сайте (раздел
7). Раздел «Статистика» в боте — просто ссылка на сайт клуба, полная
статистика и рейтинг ведутся только там.

Разработанный, но сейчас неиспользуемый метод `ApiClient.admin_sessions_pending_review` —
задел под будущее автонапоминание «оцените игру» в чат; сейчас администратор
просто сам заходит на `/mafia/admin` и видит список «Ждут оценки».

---

## 12. Фоновые задачи

Одна задача, живёт **внутри процесса API** (не в боте) через `lifespan` в
`app/main.py`: `app/tasks.py:sweep_loop()` каждые 5 минут переводит
`scheduled`/`registration_closed` игры с `starts_at` в прошлом в `played` —
кроме турнирных слотов (см. раздел 5). Синхронная функция вызывается через
`asyncio.to_thread`, чтобы не блокировать event loop; исключение в одной
итерации логируется и не убивает цикл — БД может быть временно недоступна.

Статус переводится в `API`, а не в боте, потому что это состояние данных, а
не сообщение в Telegram — переводить его обязан единственный писатель в БД.

---

## 13. Безопасность

### 13.1 Модель доверия бот ↔ API

Бот — доверенный сервисный клиент, а не конечный пользователь: каждый вызов
`/api/bot/*` подписан `Authorization: Bearer <BOT_SERVICE_TOKEN>` (сверка —
`hmac.compare_digest`, constant-time). Сам `telegram_id` действующего
пользователя бот передаёт в теле/query запроса без дополнительной подписи —
это безопасно, потому что подлинность `telegram_id` уже проверена на границе
Telegram Bot API → бот, а бэкенд доверяет самому боту как единственному
владельцу токена. Отсюда следствия:

- токен ходит только по внутренней docker-сети (`api` не публикуется наружу,
  только `nginx`, порт 8000 наружу не пробрасывается);
- `/api/bot/*` рейт-лимитится **по `telegram_id`**, а не по IP — весь трафик
  бота идёт с одного IP сервера бота, лимит по IP схлопнулся бы в одну
  корзину на всех пользователей бота разом (`rate_limit._rate_limit_key`).

### 13.2 Auth сайта

- Пароли — argon2id (`argon2-cffi`, дефолтные параметры библиотеки).
- Сессия — пара JWT (HS256) в httpOnly-cookie: access 15 минут, refresh 7
  дней; `SameSite=Lax` (не `Strict` — иначе переход по внешней ссылке на
  `/mafia/admin/games/{id}/edit` требовал бы повторного логина, хотя сессия
  жива). От CSRF защищает не `SameSite`, а отдельный double-submit токен.
- **У refresh-токенов нет серверного списка отзыва** — `/api/auth/refresh`
  просто проверяет подпись и срок действия и выдаёт новую пару; logout лишь
  стирает cookie на клиенте. Скомпрометированный refresh-токен действителен
  до истечения (до 7 дней), если его не поменять принудительно (сброс пароля
  этого не делает).
- CSRF — double-submit: `csrf_token` в НЕ-httpOnly cookie, копируется клиентом
  в заголовок `X-CSRF-Token` на каждой мутации, сверяется `hmac.compare_digest`
  (`deps.require_csrf`). Актуально только для `/api/admin/*` и части
  `/api/auth/*` — у `/api/bot/*` нет cookie/браузера, это server-to-server.
- 5 неудачных попыток логина или смены пароля подряд → блокировка аккаунта на
  N минут (`login_max_attempts`/`login_lockout_minutes`).
- Фото — валидация по реальному содержимому (Pillow `.verify()`, allow-list
  форматов JPEG/PNG/WEBP), обязательное перекодирование в JPEG со сбросом
  метаданных, а не просто проверка расширения файла.

### 13.3 Rate limiting (`slowapi` + Redis, ключ — `rate_limit._rate_limit_key`)

| Префикс/эндпоинт | Ключ | Лимит |
|---|---|---|
| `/api/auth/login`, `/api/auth/password` | IP | 5/мин |
| Публичные `GET /api/*` | IP | 60/мин |
| `/api/admin/*` | сессия (access-cookie) | 30/мин |
| `/api/bot/*`, `/api/bot/admin/*` | `telegram_id` из query | 20–30/мин |

Ключ по IP доверяет `request.client.host`, который за nginx — это адрес
самого nginx, если не настроен `FORWARDED_ALLOW_IPS`. В компоузе
`FORWARDED_ALLOW_IPS=*` безопасен ровно потому, что порт API наружу не
пробрасывается: единственный, кто может подставить `X-Forwarded-For`, — сам
nginx, который прописывает туда `$remote_addr`, а не
`$proxy_add_x_forwarded_for` (иначе клиент мог бы дописать себе подложный
адрес и получить персональную корзину лимита, см. комментарий в
`nginx/nginx.conf`).

### 13.4 Прочее

SQL-инъекции — исключены построением (SQLAlchemy Core/ORM, ни одного
конкатенированного запроса). XSS — React экранирует по умолчанию + Pydantic
валидирует все входящие поля. Один Postgres-логин с полными правами на схему
(`api_role`) — сегментация ролей целиком на уровне приложения
(`is_site_admin`/`is_bot_admin`/`require_bot_service`), а не на уровне
грантов БД: единственный писатель в БД — сам API-процесс, разделять роли
Postgres было бы имитацией защиты.

---

## 14. Деплой (Docker Compose + nginx)

`docker-compose.yml` в корне репозитория поднимает шесть сервисов:
`postgres`, `redis`, `api` (backend), `bot`, `frontend`, `nginx`. Наружу
пробрасывается только порт `nginx` (`80`) — ни `api`, ни `frontend`, ни
`postgres`/`redis` не видны снаружи docker-сети.

```
nginx (только сервис с портом наружу, :80)
 ├─ /api/*            → api:8000        (X-Forwarded-For = $remote_addr, см. 13.3)
 ├─ /media/players/*  → отдаётся напрямую с общего volume, не через API
 └─ /*                → frontend:3000

api      — читает backend/.env, но DATABASE_URL/REDIS_URL/COOKIE_SECURE/
           FORWARDED_ALLOW_IPS переопределены в environment: (compose-сеть,
           а не localhost, на который рассчитан файл при запуске на хосте)
frontend — собирается с NEXT_PUBLIC_API_URL="" (тот же origin, что и сайт,
           через nginx) и API_INTERNAL_URL=http://api:8000 (сервер Next.js
           обращается к бэкенду напрямую, минуя nginx)
bot      — читает bot/mafia-tg-bot/.env, API_BASE_URL переопределён на
           http://api:8000
```

Стек по умолчанию поднят по HTTP (`COOKIE_SECURE=false`) — браузер выбрасывает
`Secure`-куки на http-origin, поэтому включать `COOKIE_SECURE=true` можно
только после того, как перед nginx появится TLS. Первый сайт-админ заводится
не через API (эндпоинта для этого умышленно нет — выдавать сайт-доступ может
только уже залогиненный админ), а разовым CLI-скриптом на хосте:

```bash
docker compose exec api python -m app.scripts.create_admin --nickname "Админ"
```

Подробные шаги запуска (локально и через compose) — в [README.md](README.md).

---

## 15. Тестирование

Backend — `pytest` (`backend/tests/`) против **настоящего Postgres**, не
sqlite: модели используют Postgres-специфичные типы (`TIMESTAMPTZ`, JSONB).
`tests/conftest.py` сам выставляет переменные окружения и чистит БД
(`TRUNCATE`) перед каждым тестом; по умолчанию ждёт отдельную базу на порту
**55432**, чтобы прогон не снёс dev-базу на 5432.

Ключевые файлы:

- `test_e2e_flow.py` — сквозной прогон: админка заводит игроков и турнирную
  игру через слот, публичное API отдаёт рейтинг и статистику, бот
  регистрируется, создаёт сессию, записывается/резервируется/отменяет с
  авто-промоушеном.
- `test_review_flow.py` — цикл «сессия из бота → played → форма оценки на
  сайте → rated».
- `test_tournament_stages.py` / `test_tournament_standings.py` — вся модель
  раздела 7: bulk-создание слотов, единый состав таблицы, финальный этап,
  immutable-привязка слота, отказ бота от турнирных игр.
- `test_scoring.py` — формула среднего балла/бонуса, конвертация попаданий ЛХ
  в очки, обучающие игры вне реплея.
- `test_admin_validation.py`, `test_photo_upload.py`, `test_password_change.py` —
  валидация slug/полей, загрузка фото, смена пароля.

Frontend — `npx tsc --noEmit`, `npx eslint`, `npm run build` (Next.js
типизирует и собирает страницы статически/динамически по разметке в
`app/**/page.tsx`); отдельного unit-рантайма для компонентов сейчас нет,
проверка — сборка + ручная/браузерная верификация ключевых потоков.
