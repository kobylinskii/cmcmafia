# Архитектура «Мафия ВМК»

Клуб спортивной мафии ведёт сайт (`/*`) и Telegram-бота одной системой:
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
                         │        PostgreSQL 18          │
                         │      (одна схема public)      │
                         └──────────────▲─────────────────┘
                                        │ единственный писатель
                         ┌──────────────┴─────────────────┐
                         │           Backend API              │
                         │      FastAPI, один процесс          │
                         │  /api/*            — сайт (public)   │
                         │  /api/auth/*       — вход/сессия сайта│
                         │  /api/admin/*      — сайт-админка      │
                         │  /api/admin/schedule/* — планировщик игр │
                         │  /api/bot/*        — бот (пользователь)   │
                         │  /api/bot/admin/*  — права и рассылки бота │
                         │  rating_service (Эло-реплей)                │
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
    -- Ник -- как человека зовут в клубе, а не идентификатор: 1-32 символа,
    -- буквы и пробелы между ними («Я», «Дядя Фёдор»). Проверяет бот
    -- (utils.validate_nickname); slug из короткого ника добивается до трёх
    -- символов, иначе он не проходит CHECK выше (slug_service.suggest_slug).
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
    site_admin_granted_by_id INTEGER REFERENCES players(id) ON DELETE SET NULL,
                                               -- кто выдал права; NULL = корень цепочки
    failed_login_attempts  SMALLINT NOT NULL DEFAULT 0,
    locked_until           TIMESTAMPTZ,
    last_login_at          TIMESTAMPTZ,

    -- права в боте
    is_bot_admin           BOOLEAN NOT NULL DEFAULT FALSE,

    -- модерация регистрации из бота (см. раздел 3.7)
    confirmation_status      VARCHAR(20) NOT NULL DEFAULT 'confirmed'
                             CHECK (confirmation_status IN ('pending','confirmed','rejected')),
    rejection_reason         TEXT,        -- обязателен при 'rejected' (чек-констрейнт)
    confirmation_decided_at  TIMESTAMPTZ, -- когда админ нажал кнопку на сайте
    confirmation_notified_at TIMESTAMPTZ, -- когда бот доставил решение игроку

    is_active              BOOLEAN NOT NULL DEFAULT TRUE,  -- soft-delete
    created_at, updated_at TIMESTAMPTZ
);

-- Приглашение в бот-админы по @username, пока человек не написал боту /start
-- (заявка выдаётся автоматически при регистрации, см. admin_grant.consume_pending_admin).
pending_bot_admins (id, username UNIQUE, created_at)

-- Единственная строка (id=1) с клубными настройками, которые правит админ из
-- интерфейса, а не деплой. Пока настройка одна — рубеж пропускной недели.
club_settings (
    id                        INTEGER PRIMARY KEY CHECK (id = 1),
    pass_week_rollover_weekday SMALLINT NOT NULL DEFAULT 6 CHECK (BETWEEN 0 AND 6), -- 0=пн
    pass_week_rollover_time    VARCHAR(5) NOT NULL DEFAULT '18:00',                 -- 'ЧЧ:ММ' МСК
    updated_at                 TIMESTAMPTZ
)
```

`is_site_admin` сейчас означает ровно одно — «может входить в `/admin`»;
отдельной низкопривилегированной сайт-роли нет.

Отзыв прав иерархичен (`player_service.ensure_can_manage_site_admin`):
`site_admin_granted_by_id` помнит, кто кого назначил, и снять права можно
только с того, кто вырос из твоих, — напрямую или по цепочке. Если админ 1
назначил админа 2, а тот — админа 3, то 1 разжалует обоих, 2 — только третьего,
3 — никого. Себя разжаловать можно всегда (кроме последнего админа,
см. `ensure_not_last_site_admin`). Та же проверка стоит на удалении игрока
(мягко удалённый в админку уже не войдёт) и на ПОВТОРНОЙ выдаче доступа
действующему админу: перевыдача сбрасывает пароль, то есть это захват учётки.
`granted_by = NULL` — корень цепочки: первый админ из `scripts/create_admin.py`
и все, кто был админом до миграции `a9c2e5b71d34`; снять права с корневого
может только он сам. Разжаловали середину — назначенные ею переходят к тому,
кто назначил её саму, иначе снимать права с них было бы уже некому.

### 3.2 Турниры

```sql
tournaments (
    id, slug UNIQUE, name UNIQUE, description, location,
    starts_at TIMESTAMPTZ NOT NULL,   -- период проведения; обязателен у ЛЮБОГО
    ends_at   TIMESTAMPTZ NOT NULL,   -- турнира, даже без этапов (CHECK ends_at >= starts_at)
    awards_published BOOLEAN DEFAULT FALSE,  -- показывать ли блок номинаций на сайте (7.8)
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

-- РУЧНАЯ правка победителя номинации: строка есть только там, где админ не
-- согласился с расчётом. Сами номинации в базе не хранятся — они производная
-- от оценённых игр финального стола и пересчитываются на каждый запрос (7.8).
tournament_awards (
    tournament_id → tournaments ON DELETE CASCADE,
    nomination VARCHAR(20),           -- CHECK по списку из awards_service.NOMINATIONS
    player_id  → players ON DELETE CASCADE,
    created_at,
    PK (tournament_id, nomination)
)
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
    needs_rating           BOOLEAN NOT NULL DEFAULT true,   -- будет ли у игры результат, см. раздел 5
    result                 VARCHAR(10),           -- city_win|mafia_win|draw
    results_reminder_sent_at TIMESTAMPTZ,         -- зарезервировано, сейчас не используется ботом
    day_reminder_sent_at   TIMESTAMPTZ,           -- «сегодня игры» разослано; стоит только
                                                  -- на ПЕРВОЙ игре клубного дня (раздел 12)

    notes                  TEXT,
    tournament_id → tournaments ON DELETE RESTRICT,  -- NULL для funky/training
    stage_id      → tournament_stages ON DELETE RESTRICT, -- NULL, если у турнира нет сеток
    created_by → players,
    created_at, updated_at,

    CHECK (status <> 'rated' OR result IS NOT NULL),
    CHECK (status <> 'rated' OR game_type <> 'tournament' OR tournament_id IS NOT NULL)
)

-- ON UPDATE CASCADE у всех ссылок на games.id -- не украшение: id игры
-- перенумеровывается по дате проведения (раздел 5.2), и ссылающиеся строки
-- обязаны переезжать вместе с ним.

-- Запись на игру ДО неё (кто поведёт/посудит/сыграет). Одна строка на человека.
registrations (id, game_id ON DELETE CASCADE ON UPDATE CASCADE, player_id ON DELETE CASCADE, role, available_from, available_until, created_at,
               UNIQUE (game_id, player_id))
reserves       (id, game_id ON DELETE CASCADE ON UPDATE CASCADE, player_id ON DELETE CASCADE, created_at, UNIQUE (game_id, player_id))

-- Результат ПОСЛЕ игры: 10 мест, игровые роли, баллы. Сознательно отдельная
-- от registrations таблица — до игры человек занимает организационную роль
-- (ведущий/судья/игрок), после — конкретное место с игровой ролью и баллами.
game_participants (
    id, game_id ON DELETE CASCADE ON UPDATE CASCADE, player_id ON DELETE RESTRICT,
    seat_number SMALLINT CHECK (1..10),
    role        VARCHAR(10),          -- mafia|don|sheriff|citizen

    points_win   NUMERIC(4,2) DEFAULT 0,
    points_judge NUMERIC(4,2) DEFAULT 0,
    lh           NUMERIC(3,2),        -- ПОПАДАНИЯ ЛХ (0/0.5/1/1.5 = 0/3..3/3 названных чёрных), не баллы!
    ci           NUMERIC(5,2),        -- компенсация; 0..20 с шагом 0.5, отрицательной не
                                      --   бывает (штрафы — это отдельные zk/sk/removals/ppk).
                                      --   Проверяет схема запроса, а не БД: исторические
                                      --   строки миграция не переписывает
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
idx_players_pending_confirmation (partial WHERE confirmation_status='pending')
idx_players_confirmation_unnotified (partial WHERE решение принято, но не доставлено)
idx_games_starts_at (starts_at, id), idx_games_status, idx_games_tournament, idx_games_stage
idx_registrations_player, idx_registrations_game
idx_participants_player, idx_participants_game
idx_rating_current (rating)
```

### 3.6 Зарезервированные `slug`

Игроки и турниры используют человекочитаемые URL (`/<slug>`,
`/tournaments/<slug>`), поэтому часть значений зарезервирована системой
(`slug_service.RESERVED_SLUGS`): `games, rating, admin, api, login, static,
assets, favicon.ico, robots.txt, sitemap.xml, _next, mafia, tournaments`.

---

### 3.7 Модерация регистраций

Регистрация в боте открыта кому угодно, поэтому новая строка `players`,
созданная ботом, заводится со статусом `pending`, а игрок, заведённый админом
на сайте, — сразу `confirmed` (это `server_default` столбца, `pending`
проставляет явно только `POST /api/bot/players/register`).

Что означает статус:

| | `pending` | `confirmed` | `rejected` |
|---|---|---|---|
| Виден на публичной части сайта | нет | да | нет |
| Может записываться на игры | **да** | да | да |
| В списке на пропуск | да, с пометкой | да | да, с пометкой |
| Правки профиля | сразу | через проверку (3.8) | сразу |

Записываться на игры новичок может сразу и до решения админа: держать
человека в очереди из-за того, что администратор отошёл, — худшее из двух зол,
а на сайте его всё равно нет. Скрытие с публичной части — одно условие в одном
месте, `services/visibility.public_player_criteria()`; им пользуются рейтинг,
список игроков, карточка по slug, счётчики главной и расчёт ранга.

`rejected` обязан нести причину (чек-констрейнт): её текст — единственное, что
игрок увидит в боте, и без неё отказ выглядит как поломка. Отклонённый правит
данные в профиле и жмёт «Отправить на повторную проверку»
(`POST /api/bot/players/me/resubmit`), заявка снова становится `pending`.

**Доставка решения.** Бэкенд в Telegram не пишет — токен бота живёт только в
боте. Решение админа проставляет `confirmation_decided_at`, а бот раз в минуту
забирает очередь (`GET /api/bot/players/confirmation-notifications`),
рассылает и подтверждает `ack`'ом, который и ставит
`confirmation_notified_at`. Пока `ack` не пришёл, строка остаётся в очереди,
поэтому упавший бот ничего не теряет; заблокировавшему бота пользователю
решение помечается доставленным сразу — иначе одна такая строка обрабатывалась
бы на каждом проходе вечно.

**Оповещение админа.** Симметрично: о новой заявке админам тоже пишет бот.
Свежая `pending`-строка с пустым `confirmation_admin_notified_at` — очередь
`GET /api/bot/admin-notifications` (там же `telegram_id` тех, кому писать), бот
рассылает и ставит метку `ack`'ом. `resubmit` метку снимает — повторная подача
для админа новое событие. Получателей нет (ни у одного админа не привязан
Telegram) — очередь не трогается: адресат может появиться позже. Решение
принимается кнопками в самом уведомлении (раздел 3.8).

---

### 3.8 Модерация правок профиля

Профиль игрока — это ФИО в списке на пропуск и ник в рейтинге и составах игр,
то есть то, по чему человека узнают в клубе. Раньше подтверждённый игрок
переписывал их из бота молча, и админ узнавал об этом по расхождению списка на
пропуск с документами.

`PUT /api/bot/players/me` от подтверждённого игрока теперь **не сохраняет поля
свободного ввода сразу**: правка ложится строкой в `player_profile_changes`
(`status='pending'`), а в самом профиле продолжает действовать прежнее
значение. Ответ ручки несёт `pending_changes` — `{поле: новое значение}`, и
бот показывает эту пару рядом («сейчас X, ⏳ на проверке Y»), иначе экран
выглядел бы так, будто правка не сохранилась.

Модерируются пять полей текстового ввода — `full_name`, `nickname`, `age`,
`experience`, `bio` — и фотография, `photo_url`
(`profile_change_service.MODERATED_FIELDS`).

**Фото — особый случай той же очереди.** Приходит оно не через `PUT`, а
отдельной ручкой (`POST /api/bot/players/me/photo`, multipart), и в
`new_value` ложится не введённый текст, а адрес уже записанного файла
(`/media/players/<uuid>.jpg`): показать админу картинку иначе нечем. Файл
пишется до решения и до него не принадлежит никому — в профиле продолжает
действовать прежнее фото. Отсюда единственная обязанность, которой нет у
текстовых полей: за непринятым файлом надо убирать, иначе волюм растёт на
каждую отклонённую аватарку. Убирает `profile_change_service` — при отказе
(файл не пригодился), при вытеснении прежней правки новой (админу нужен
последний вариант) и при применении (не нужно уже прежнее фото игрока).
Содержимое не принимается на веру: `player_service.store_photo_file`
пересобирает изображение заново, срезая метаданные и полиглот-контент.

Показывает правку фото бот **картинкой**: и уведомление админам, и карточка в
разделе «🕓 На проверке» — это `sendPhoto` с подписью и теми же кнопками
решения (`ui.open_photo_screen`, `notifier.change_photo`). Решать по фото, не
видя фото, нельзя, а путь к файлу в тексте карточки бесполезен. Отсюда же
единственная развилка в `handlers/moderation.py`: у сообщения-картинки текст
лежит в `caption`, и правится он `editMessageCaption`, а не `editMessageText`.

У неподтверждённого и отклонённого игрока фото, как и текст, применяется
сразу: у них на проверке весь профиль целиком.

**Удаление фото проверки не требует** (`DELETE /api/bot/players/me/photo`):
модерация сторожит то, что появляется на сайте, а пустое место сторожить не
от чего. Заодно оно снимает с проверки ещё не рассмотренное фото
(`profile_change_service.withdraw` — строка удаляется, а не отклоняется:
решения по ней не было). Без этого «удалить» сразу после «отправлено на
проверку» ничего бы не значило: фото всё равно встало бы в профиль, как
только админ дойдёт до карточки.
Обращение, статус прохода, роли и любимая роль выбираются кнопками из
вариантов, заданных самим ботом — проверять там нечего, а роли к тому же
решают, на какие места пускает запись прямо сейчас.

Два важных исключения:

- **Непподтверждённого и отклонённого игрока правка не тормозит** — у них на
  проверке весь профиль целиком. Иначе отказ «поправьте ФИО и отправьте заявку
  заново» стал бы тупиком: исправление тоже ушло бы в очередь.
- **Админ на сайте правит профиль напрямую** (`PUT /api/admin/players/{id}`) —
  он и есть та проверка, которую ждёт очередь.

Одно поле — одна строка в очереди: повторная правка вытесняет прежнюю
(частичный уникальный индекс `uq_profile_changes_one_pending_per_field`), иначе
админ разбирал бы стопку промежуточных вариантов. Вытесняет **на месте**: `id`
строки при этом не меняется. Пересоздание ломало всё, что уже успело на этот
`id` сослаться — открытую вкладку «Обзор» и разосланные админам сообщения:
«Применить» у всех правок, кроме последней, утыкалось в «Правка не найдена», и
снаружи это выглядело как «подтвердить можно только последнюю». Значение
хранится строкой независимо от типа колонки и приводится к нему в момент
применения; `NULL` — осознанная очистка необязательного поля. Ник
перепроверяется на занятость **при применении**, а не только при подаче:
очередь ничего не резервирует, и за время ожидания ник мог занять другой
человек.

Решённая строка не удаляется: `applied`/`rejected` — это и история правок, и
очередь доставки решения игроку. Доставка устроена ровно как у модерации
регистраций (сайт ставит `decided_at`, бот забирает опросом и ставит
`notified_at`), но очередь **отдельная** — недоставленное решение по заявке не
должно задерживать ответ по правке профиля.

О самой новой правке админам пишет бот — той же очередью
`GET /api/bot/admin-notifications`, что и о новых заявках (раздел 3.7);
`pending`-строка с пустым `admin_notified_at` в неё и попадает.

**Решение принимается прямо в этом сообщении**, кнопками под ним
(`POST /api/bot/moderation/*`, бот — `handlers/moderation.py`): админ клуба
живёт в Telegram, и «проверить можно в админке сайта» откладывало проверку до
ближайшего компьютера. Отказ спрашивает причину тем же диалогом — её увидит
игрок, и без неё отказ выглядит поломкой. Уведомление уходит **каждому** админу
с привязанным Telegram (и сайта, и бота —
`admin_notification_service.admin_recipients`) своей копией; решает кто-то
один, у остальных нажатие получает 409 «уже рассмотрено» и их копия
дописывается этим текстом.

**Экрана модерации на сайте больше нет.** Вкладка «Обзор» держала вторую копию
тех же двух очередей, и «уже рассмотрено» в ней выяснялось только по нажатию.
Ручки `GET /api/admin/players/pending` и
`GET /api/admin/players/profile-changes` (и решения по ним) остались без
интерфейса — аварийным доступом к очереди.

Само же «а что там висит?» отвечает раздел **«🕓 На проверке»** в админ-меню
бота (`GET /api/bot/moderation/pending`): список → карточка → те же две кнопки,
после решения — обратно к списку. Он отличается от очереди оповещения
(`/admin-notifications`) ровно одним, но важным: это **полный** список
незакрытого, а не «о чём ещё не писали». Уведомление можно удалить из чата, а
`ack` уже проставлен — без такого списка заявка после этого не всплыла бы
больше нигде.

---

### 3.9 Списки на пропуск

Клуб играет на ВМК, и людям со статусом
`affiliation='outside_need_pass'` пропуск заказывают заранее списком ФИО.
Неделя тут не календарная: окно — полуинтервал `[последний рубеж; +7 суток)`,
где рубеж задаётся `club_settings` (по умолчанию воскресенье 18:00 МСК). В
момент рубежа показ переключается на наступающую неделю, чтобы заявку успели
подать; игра, начинающаяся ровно в момент рубежа, относится уже к новой
неделе. В список попадают все записи на фановые и обучающие игры окна — и
основной состав, и ведущие с судьями, и резерв: пропуск нужен человеку, а не
его роли, а запасной попадает в состав в последний момент, когда заказывать
пропуск уже поздно. Считает всё это `services/pass_list_service.py`.

---

## 4. Единый API

Один FastAPI-процесс (`app/main.py`), шесть роутеров с разными моделями
авторизации.

```
# ================= PUBLIC (app/routers/public.py) — читает кто угодно, только rate limit =================
GET  /api/games                    ?limit=&offset=&date_from=&date_to=&game_type=&player_slug=&tournament_slug=
GET  /api/games/{id}
GET  /api/rating                   ?q=&limit=&offset=&sort=rating|games_count|win_rate|avg_bonus
                                   — без q: только те, кто уже играл. С q -- поиск человека
                                     по нику, в том числе не сыгравшего ни одной игры.
                                     sort меняет ТОЛЬКО порядок строк: место в колонке «#»
                                     всегда клубное, по рейтингу (см. ниже)
GET  /api/rating/formula           — формула и текущие коэффициенты, вычисленные из тех же функций, что реплей
GET  /api/stats                    — счётчики для главной (игр/игроков/турниров)
GET  /api/tournaments
GET  /api/tournaments/{slug}       — общая таблица + таблицы этапов + is_final + пронумерованные игры этапа
                                   + номинации и призёры, но только если админ их опубликовал (раздел 7.8)
GET  /api/players
GET  /api/players/{slug}           — профиль + PlayerStats (см. раздел 8)

# ================= AUTH (app/routers/auth.py) =================
POST /api/auth/login               — 5/мин/IP; блокировка на N минут после 5 неверных попыток
POST /api/auth/refresh             — обменивает refresh-cookie на новую пару access+refresh+csrf
POST /api/auth/logout
POST /api/auth/password            — смена пароля себе (требует текущий пароль)
GET  /api/auth/me                  — {player_id, nickname, is_site_admin}; player_id нужен
#                                    админке, чтобы понять своё место в цепочке выдачи прав

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
GET  /api/admin/tournaments/{id}/awards                — предпросмотр номинаций: победители + кандидаты (7.8)
PUT  /api/admin/tournaments/{id}/awards                — {published?, winners?: {номинация: slug|null}}

GET/POST/PUT/DELETE /api/admin/players[/{id}]
GET  /api/admin/players/slug-suggestion
# Модерация решается в Telegram (раздел 3.8), экрана под неё на сайте нет.
# Ручки ниже остались аварийным доступом к очереди: уведомление можно удалить
# из чата, и другого способа увидеть незакрытую заявку тогда не остаётся.
GET  /api/admin/players/pending                        — заявки из бота, ждущие решения (раздел 3.7)
POST /api/admin/players/{id}/confirm
POST /api/admin/players/{id}/reject                    — {reason} обязателен
GET  /api/admin/players/profile-changes                — правки профилей из бота (раздел 3.8)
POST /api/admin/players/profile-changes/{id}/apply
POST /api/admin/players/profile-changes/{id}/reject    — {reason} обязателен
POST /api/admin/players/{id}/photo
POST/DELETE /api/admin/players/{id}/site-access        — выдать/отозвать сайт-логин
#                                                        отзыв только вниз по цепочке выдачи (раздел 3.1)
GET/POST/DELETE /api/admin/bot-admins[/{player_id}]     — {telegram_id | username}

GET  /api/admin/pass-list                              — ФИО на пропуск за текущую неделю (раздел 3.9)
GET/PUT /api/admin/settings/pass-week                  — день и время рубежа пропускной недели

# ===== SITE ADMIN, ПЛАНИРОВЩИК (app/routers/admin_schedule.py; та же авторизация) =====
# Переехавшая из бота админка расписания, вкладка «Игры → Расписание».
GET  /api/admin/schedule/days                          ?game_type= — игровые дни со счётчиками
GET  /api/admin/schedule/sessions                      ?day=ДД.ММ.ГГГГ — игры одного дня
POST /api/admin/schedule/plan/preview                  — во что развернётся план и что уже занято
POST /api/admin/schedule/plan                          — создать слоты (409, если время занято)
GET  /api/admin/schedule/sessions/{id}                 — слот + состав и резерв
PUT  /api/admin/schedule/sessions/{id}                 — время, место, формат, needs_rating
DELETE /api/admin/schedule/sessions/{id}               — в том числе ответ «не состоялась»
GET  /api/admin/schedule/awaiting-confirmation         — прошедшие игры без ответа «состоялась?»
POST /api/admin/schedule/sessions/{id}/played          — «Игра проведена»: scheduled -> played
GET  /api/admin/schedule/locations                     — места прошлых игр для подсказки в форме

# ================= TELEGRAM USER (app/routers/bot.py; Bearer BOT_SERVICE_TOKEN + telegram_id в теле/query) =================
POST /api/bot/players/register                        — заводит игрока со статусом 'pending'
GET/PUT /api/bot/players/me                           — PUT: текстовые поля уходят на проверку (раздел 3.8),
                                                        ответ несёт pending_changes
POST /api/bot/players/me/photo                        — аватарка из чата (multipart); у подтверждённого ждёт админа (3.8)
DELETE /api/bot/players/me/photo                      — убрать своё фото; заодно снимает с проверки неодобренное
GET  /api/bot/players/me/stats                        — короткая сводка для карточки профиля в боте
POST /api/bot/players/me/resubmit                     — отклонённый просит перепроверить заявку
GET  /api/bot/players/confirmation-notifications      — очередь решений админа (только сервисный токен)
POST /api/bot/players/confirmation-notifications/ack  — {player_ids} — бот подтверждает доставку
GET  /api/bot/players/profile-change-notifications    — очередь решений по правкам профиля
POST /api/bot/players/profile-change-notifications/ack — {change_ids}
GET  /api/bot/admin-notifications                     — что появилось на проверку + telegram_id админов
POST /api/bot/admin-notifications/ack                 — {registration_player_ids, profile_change_ids}
GET  /api/bot/moderation/pending                      — всё, что ждёт решения: раздел «На проверке»
                                                        (полный список, в отличие от очереди выше)
GET  /api/bot/day-reminders                           — дни, до первой игры которых меньше 3 часов (раздел 12)
POST /api/bot/day-reminders/ack                       — {game_ids} — id первой игры дня
# Решение админа кнопкой под уведомлением (раздел 3.8). Права шире остального
# /api/bot/admin: уведомление уходит и админу сайта без прав в боте.
POST /api/bot/moderation/registrations/{player_id}/confirm | reject   — reject: {reason}
POST /api/bot/moderation/profile-changes/{change_id}/apply | reject   — reject: {reason}
GET  /api/bot/game-days                ?game_type=&telegram_id=
GET  /api/bot/sessions/open            ?game_type=&day= — свои записи не вычитаются, а помечаются my_role
GET  /api/bot/sessions/{id}
POST /api/bot/sessions/{id}/register   — {telegram_id, role_kind: player|staff}
                                         роль player переполнением не отказывает: 11-й уходит
                                         в резерв тем же запросом (is_reserve, reserve_position)
POST /api/bot/sessions/{id}/reserve     — явная постановка в очередь (обычный путь — /register)
DELETE /api/bot/sessions/{id}/registration — авто-промоушен из резерва, ответ несёт promoted_telegram_id
GET  /api/bot/sessions/{id}/roster
GET  /api/bot/registrations/mine

# ================= TELEGRAM ADMIN (app/routers/bot_admin.py; тот же токен + is_bot_admin у переданного telegram_id) =================
# Расписания здесь больше нет: планировщик уехал в /api/admin/schedule/*.
# Осталось то, чего без Telegram не сделать.
GET  /api/bot/admin/broadcast/weekly                ?days= — игры недели + кому анонс ещё нужен
GET  /api/bot/admin/broadcast/audience              — кому уйдёт произвольное сообщение админа
GET  /api/bot/admin/players/by-username | by-phone   — шаг назначения админа
GET/POST/DELETE /api/bot/admin/admins[...]           — тот же admin_grant.grant_bot_admin, что и с сайта
```

`POST /api/admin/bot-admins` и `POST /api/bot/admin/admins` вызывают **один и
тот же** сервисный метод `admin_grant.grant_bot_admin(...)` — правами бот-админа
можно управлять и с сайта, и из чата бота, потому что под капотом это ровно
одна операция над одной таблицей.

Важно: **турнирные игры нельзя создать ни через `/api/admin/games`, ни через
планировщик** — единственный путь описан в разделе 7.

---

## 5. Жизненный цикл игры

```
scheduled ──► (registration_closed, не используется сейчас) ──► played ──► rated
```

- **scheduled** — слот создан (планировщиком как сессия для записи, либо как
  пустой турнирный слот), `starts_at` в будущем.
- **registration_closed** — значение определено в модели и проверяется в
  `CHECK`, но на практике сейчас ничем не выставляется — зарезервировано под
  будущую фичу «закрыть запись раньше начала игры».
- **played** — админ нажал «✅ Игра проведена» в карточке слота
  (`POST /api/admin/schedule/sessions/{id}/played` → `game_service.mark_session_played`).
  Раньше этот переход делала фоновая задача по одному лишь наступлению времени,
  и в «Ждут оценки» попадало всё подряд, включая игры, которые не собрались.
  Прошедшие неподтверждённые игры видны отдельным блоком во вкладке
  «Игры → Расписание» и на «Обзоре» (`schedule/awaiting-confirmation`); ответ
  «не состоялась» — это `DELETE` игры вместе с записями. Турнирные слоты в
  этой очереди не участвуют — они оцениваются внутри своего этапа.
- **rated** — результат внесён (`game_participants` заполнены, `result`
  проставлен), рейтинг пересчитан. Обратного пути из `rated` нет, кроме
  повторного `PUT` с новыми данными или `DELETE`.

### 5.1 `needs_rating` — будет ли у игры результат

Флаг ставится при планировании дня и применяется ко всем его слотам; у
отдельной игры его можно переключить, пока она не оценена.

- `needs_rating = true` (по умолчанию) — полный цикл выше: игра доступна для
  записи в боте, после неё просит подтверждения, оттуда идёт в «Ждут оценки»,
  её результат попадает в рейтинг.
- `needs_rating = false` — слот существует только ради записи в боте
  («просто поиграть»). Он не попадает ни в `awaiting-confirmation`, ни в
  `pending-review`; `mark_session_played` для него отвечает 409. Когда время
  игры прошло, слот молча уходит из расписания
  (`schedule_admin_service._active_schedule_filters`), потому что нажимать по
  нему больше нечего. Сама игра и её `registrations` остаются в базе — по ним
  считается список на пропуск и видна история записи.

Снятие флага с игры, уже отмеченной проведённой, возвращает её в `scheduled`:
иначе она осталась бы в «Ждут оценки» навсегда — оценивать её больше некому.

### 5.2 Номер игры = её место в хронологии

`games.id` — это то, чем игру называют («Игра №14» в карточке, в подтверждении
удаления в боте, в URL `/games/{id}`, номером `№14` в каждой карточке
списка — игры клуба, партии турнира, игры игрока). Поэтому нумерация ведётся не
`SERIAL`-порядком создания, а хронологией:

- игры пронумерованы подряд по `starts_at` — игра, внесённая задним числом,
  встаёт между уже сыгранными и сдвигает те, что позже;
- удалённая игра не оставляет дыры: всё, что стояло после неё, сдвигается на
  номер назад;
- при равных датах (пустые слоты этапа получают дату турнира-плейсхолдера)
  порядок держится по `created_at`, а затем по текущему `id`, так что взаимное
  расположение слотов не скачет.

Механика — `game_service.resequence_game_ids()`: два `UPDATE` (сдвиг всех
ключей за пределы занятого диапазона, затем присвоение `row_number()`) плюс
`setval` последовательности. Строки, ссылающиеся на игру — составы, записи,
резерв, история рейтинга — переезжают сами: их внешние ключи объявлены
`ON UPDATE CASCADE` (миграция `c9a2f4e17b58`).

Перенумерация вызывается из роутеров **после** их собственного `db.commit()`
через `game_service.resequence_and_reload()` — она же возвращает изменившиеся
игры под новыми номерами. Обычный `db.refresh()` на этом месте не годится: он
пошёл бы в базу за строкой по старому, уже несуществующему `id`.

**Следствие**: `id`, который клиент получил раньше, может устареть. Ответ на
`POST`/`PUT` всегда содержит актуальный номер, а формы админки после
сохранения уходят на список — но внешняя ссылка на `/games/{id}`,
сохранённая до правки расписания, может указать на соседнюю игру.

### 5.3 Три способа попасть в `rated`

1. **Игра с записью**: `POST /api/admin/schedule/plan` (funky/training) →
   игроки записываются в боте через `registrations`/`reserves` → админ
   подтверждает проведение и игра становится `played` → он же открывает
   `/admin/games/{id}/edit`, видит уже подставленный состав (roster) из
   записей бота и расставляет 10 реальных мест/ролей/баллов → `PUT`
   переводит `played → rated`.
2. **Турнирная игра**: слот создаётся сразу на сайте, без всякой записи (см.
   раздел 7) → тот же экран оценки (`GameOut.roster` для турнирного слота
   всегда пуст — расставлять некого) → `PUT` переводит `scheduled → rated`
   напрямую.
3. **Полностью историческая игра** (её не было ни в расписании, ни как
   турнирный слот): `POST /api/admin/games` создаёт funky/training игру сразу
   как `rated`, минуя запись.

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

Sa = points_win + points_judge + lh_points(lh) + ci − zk − sk
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

Штрафы разведены по двум механизмам, и это не случайность:

- **ЖК и СК** хранятся сразу в игровых баллах и потому вычитаются из `Sa` —
  ровно так, как считает клубная таблица («итого очков за игру»). Одна
  карточка стоит `K · ЖК / M` очков рейтинга: при K=40 и ЖК=0.5 это 2.86.
- **Удаления и ППК** — отдельный член `O` сразу в очках рейтинга, по ставкам
  из `_penalty_rates`. В `Sa` они не входят, хотя в колонке «Итог» на сайте
  (`stats_service._SCORE_SQL`) вычитаются как игровые баллы — там своя шкала
  (0.5 за удаление, 2.5 за ППК).

Формула сверена с реальной клубной таблицей (7 игр, 70 строк): `Sa`,
ожидание `E`, дельта и итоговый рейтинг всех участников сходятся до копейки.
До сверки `zk`/`sk` в `Sa` не входили, и карточка не влияла на рейтинг вообще.

`lh` хранит **попадания** легендарного хода, а не баллы: 0 / 0.5 / 1 / 1.5 в
БД означают 0/3, 1/3, 2/3, 3/3 названных чёрных. В очки они переводятся так:
0/3 и 1/3 → 0 баллов, 2/3 → 0.5, 3/3 → 1 (`rating_service.LH_POINTS`, зеркало —
`stats_service._LH_POINTS_SQL`, держать в синхроне вручную).

**Обучающие игры (`training`) не участвуют в реплее вообще** — не только не
двигают рейтинг, но и не увеличивают `games_count`, от которого зависит K.
Раньше нулевой вес без исключения из реплея всё равно косвенно «взрослил»
игрока. В личной статистике игрока (`/api/players/{slug}` и карточка профиля в
боте) их тоже нет ни в каком виде: `compute_player_stats` отсекает их одним
`_RATED_FORMAT_SQL` в WHERE, поэтому обучающая игра не идёт ни в счётчики игр,
побед и поражений, ни в разбивку по картам и ролям, ни в первоубиенного с его
ЛХ, ни в средние. Раньше фильтр висел только на двух средних, и на одной
карточке стояли числа по разным наборам игр. В СПИСКЕ игр под статистикой
обучающие остаются: это история игрока, а не статистика, и формат у карточки
подписан.

Формулу пересчитывает сама себя только при правке игр. Если изменились её
собственные константы (веса, коэффициенты, состав `Sa`), игры при этом никто
не трогал — и старые числа останутся в базе, пока кто-нибудь не отредактирует
случайную игру. Для таких случаев есть команда:

```
docker compose exec api python -m app.scripts.recompute_rating --dry-run
docker compose exec api python -m app.scripts.recompute_rating
```

`GET /api/rating/formula` отдаёт текст и таблицу коэффициентов, **вычисленные
теми же функциями**, что и сам реплей (`_k_coefficient`, `_penalty_rates`,
`GAME_TYPE_WEIGHT`) — правки порогов в одном месте не могут разойтись с
текстом на сайте.

**Поиск по нику — это «найди человека», а не «покажи таблицу».** С непустым
`q` в выдачу попадают и те, кто ещё не сыграл ни одной игры: иначе страницу
новичка на сайте не открыть ниоткуда. Без `q` таблица прежняя — только
игравшие, у остальных рейтинга просто нет: `rank` у такой строки приезжает
`null`, и в таблице ей рисуется прочерк вместо места и рейтинга. Само место
считает оконная `rank()` в БД, а не номер строки в выдаче, — поэтому найденный
поиском игрок показывает своё место в клубе, а не позицию в результатах. Модерация регистраций сильнее поиска: неподтверждённый
не находится и по нику (`visibility.public_player_criteria`) — ссылка вела бы
на 404.

---

## 7. Турниры и этапы

Полная модель — `backend/app/services/tournament_service.py` +
`app/routers/admin.py` (раздел «Турниры») + публичная страница
`/tournaments/[slug]`.

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
Оценивается он той же самой общей формой/ручкой, что и игра с записью —
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

### 7.6 Порядок мест в таблице

Строки сортируются по сумме баллов (`Итог`), а равные суммы разводит тай-брейк
регламента — в этом порядке:

1. больше баллов от судей;
2. больше побед;
3. больше побед на **активных ролях** (дон, шериф);
4. меньше поражений на активных ролях.

Считается это одним местом на весь проект —
`stats_service._standing_sort_key` (агрегаты для него собирает
`_standing_columns`, они же общие у таблицы одного этапа и у сводного запроса
по всем этапам сразу). Тем же порядком разрешаются равенства в номинациях
(7.8), поэтому расходиться этим двум местам нельзя по построению.

### 7.7 Удаление турнира/этапа

Турнир или этап с уже **оценёнными** играми удалить нельзя (сначала
переносят игры в другой турнир/этап — `ON DELETE RESTRICT` в БД плюс явная
проверка в сервисе с понятным текстом ошибки). Ещё не оценённые
(`scheduled`) слоты — просто пустые заготовки, они удаляются вместе с
турниром/этапом безо всякого переноса.

### 7.8 Номинации и победители

`backend/app/services/awards_service.py` + публичный блок
`frontend/src/components/tournaments/awards-section.tsx` + панель админки
`frontend/src/components/admin/tournament-awards-panel.tsx`.

Считаются **только по играм финального стола**: финального этапа, если у
турнира есть сетка, иначе по единственной таблице турнира. Отборочные этапы не
входят вообще — составы там разные, и средний балл за игру сравнивал бы людей,
игравших с разными соперниками. Если этапы есть, а финальный не отмечен,
номинаций нет вовсе, и админке возвращается объяснение (`problem`), а не пустой
блок.

| Номинация | Что делится | На что делится |
|---|---|---|
| MVP турнира | баллы от судей + ЛХ на всех ролях | игры финального стола |
| Лучший мирный | баллы от судей + ЛХ на мирном | игры на мирном |
| Лучший чёрный | баллы от судей на мафии | игры на мафии |
| Лучший дон | баллы от судей на доне | игры на доне |
| Лучший шериф | баллы от судей + ЛХ на шерифе | игры на шерифе |
| 1/2/3 место | сумма баллов финального стола (не среднее) | — |

У чёрных ролей ЛХ в зачёт не идёт (`Nomination.with_lh`). Делимое на игры —
это ровно «средний дополнительный балл» страницы игрока
(`stats_service._BONUS_SQL`), только в разрезе роли. Равные значения разводит
место в турнирной таблице, то есть тай-брейк из 7.6.

Статистика победителя считается **в зачёте номинации** (у MVP и мест — по
всему финальному столу). На карточках показывается не всё, что отдаёт API, и в
одном порядке у MVP и призовых мест: игры, % побед, баллы от судей, средний
доп. балл. MVP при этом главная номинация — идёт первой, во всю ширину и по
центру; у ролевых карточек остаются только игры в зачёте и средний доп. балл,
иначе четыре карточки в ряд читаются как таблица.

**В базе номинации не хранятся** — это производная от оценённых игр, и после
правки оценки они обязаны пересчитаться сами. Хранится только то, чего из игр
не вывести:

- `tournament_awards` — ручная замена победителя. Строка появляется, лишь если
  админ выбрал не того, кого посчитал сервис; кандидатом может быть только тот,
  кто эту роль на финальном столе действительно играл (иначе 422). Выбор
  «Автоматически» удаляет строку. Если после переоценки игры выбранный вручную
  игрок выпал из кандидатов, номинация молча возвращается к расчёту.
- `tournaments.awards_published` — показывать ли блок на сайте. Пока флаг снят,
  `GET /api/tournaments/{slug}` отдаёт пустой `awards`: промежуточный «лучший
  дон» посреди турнира не значит ничего.

Кандидаты выбираются по `slug`, а не по числовому id игрока: админка получает
их тем же `AwardCandidateOut`, что и публичная страница, а публичный контракт
числовых id игроков не отдаёт.

### 7.9 Бот турниры больше не видит

С момента введения этой модели турнирная сетка целиком живёт на сайте.
Бот (`app/schemas/bot.py`, `GAME_TYPES = {"funky", "training"}`) физически
не может создать сессию с `game_type='tournament'` — попытка получает 422 на
уровне Pydantic-валидатора. Регистрация на игру и bulk-создание слотов дня
(`registration_service.list_open_sessions`,
`schedule_admin_service.day_cards/games_by_day`) явно исключают турнирные
слоты фильтром `game_type != 'tournament'`, иначе плейсхолдер-слоты этапа
(со статусом `scheduled` и датой, которая может уже быть в прошлом) попали бы
в список открытых для записи игр или в расписание планировщика.

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
  main.py            — сборка FastAPI-приложения, CORS, подключение всех роутеров, /health
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

  routers/
    public.py         — /api/* (не требует авторизации)
    auth.py            — /api/auth/*
    admin.py           — /api/admin/* (сайт-админка: игры, турниры, игроки, пропуска)
    admin_schedule.py   — /api/admin/schedule/* (планировщик игровых дней, раздел 5)
    bot.py              — /api/bot/* (пользователь бота)
    bot_admin.py         — /api/bot/admin/* (права и рассылки — всё, что осталось от
                            админки бота)

  services/            — бизнес-логика без привязки к HTTP
    player_service.py    — CRUD игрока, фото, выдача/отзыв сайт-доступа
    player_confirmation_service.py — модерация регистраций из бота (раздел 3.7)
    profile_change_service.py       — модерация правок профиля из бота (раздел 3.8)
    slug_service.py       — транслитерация/валидация/резерв slug'ов
    game_service.py        — CRUD рейтинговой игры, resolve турнира/этапа, подтверждение
                              проведения сессии, проверка единого состава таблицы
    tournament_service.py  — CRUD турнира и этапов, bulk-создание слотов, is_final
    awards_service.py       — номинации турнира по финальному столу и ручные
                               правки победителей (раздел 7.8)
    registration_service.py— запись с авто-резервом, отмена с авто-промоушеном (для бота)
    schedule_admin_service.py — планирование слотов дня (шаг и количество), конфликты
                                 по времени, обзор по дням, места прошлых игр
    broadcast_service.py      — игры недели и получатели анонса (бот, раздел 11.4)
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

Next.js 16 App Router, `/` — префикс всего сайта (namespace, чтобы
уживаться с прочими проектами на том же домене).

```
frontend/src/
  proxy.ts                    — гейт по наличию refresh-cookie перед /admin/*
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

  app/(site)/               — публичные страницы (Server Components, всегда свежие)
    page.tsx                       — главная
    games/, games/[gameId]/         — список и карточка игры
    rating/                          — таблица рейтинга + описание формулы
    [slug]/                          — профиль игрока
    tournaments/, tournaments/[slug]/ — список турниров и страница турнира (аккордеон этапов)

  app/revalidate/                  — сброс кеша публичных страниц (revalidateTag).
                                      Дёргается из lib/api.ts после каждой удачной
                                      правки в админке. Путь НЕ под /api/: там nginx
                                      отдаёт всё бэкенду

  app/media/players/[...path]/     — прокси к фотографиям игроков на бэкенде. Нужен не
                                      посетителю (в проде /media/players/ отдаёт nginx
                                      прямо с волюма, до Next запрос не доходит), а
                                      ОПТИМИЗАТОРУ next/image: при пустом
                                      NEXT_PUBLIC_API_URL mediaUrl() отдаёт
                                      относительный путь, и оптимизатор идёт за файлом
                                      на сам сервер Next

  app/admin/                 — админка (Client Components, сессия через cookie)
    login/                          — форма входа (единственная страница вне гейта proxy.ts)
    (dashboard)/                    — всё остальное: обзор, игры, турниры, игроки, смена пароля
    (dashboard)/games/               — три вкладки одного раздела: «Расписание» (планировщик),
                                        «Ждут оценки», «Оценённые». Вкладка, открытый день и
                                        карточка слота лежат в query (?tab=&day=&session=),
                                        чтобы возврат из формы оценки не выбрасывал в начало

  components/
    admin/                          — game-form, tournament-form, tournament-stages-manager,
                                       tournament-awards-panel (предпросмотр номинаций,
                                       раздел 7.8), player-form, player-combobox,
                                       admin-shell, confirm-dialog…
                                       Экранов модерации здесь нет: заявки и правки профиля
                                       разбираются в Telegram (раздел 3.8)
    admin/schedule/                  — планировщик: schedule-panel (дни, день, очередь
                                        подтверждения), plan-form (пачка слотов с
                                        предпросмотром времён), session-card (правка слота,
                                        «проведена / не состоялась», состав и резерв)
    games/, home/, player/, rating/, tournaments/, ui/ — публичные виджеты
                                       (tournaments/awards-section — призёры и номинации
                                       на странице турнира, раздел 7.8)
```

Ключевые тонкости, которые легко сломать заново:

- `next.config.ts`'ы `NEXT_PUBLIC_API_URL`-фоллбэк обязан совпадать с
  `lib/api.ts`'ым — иначе `next/image`-оптимизатор отказывается грузить
  фотографии игроков (не в allow-list удалённых хостов). Второй, независимый
  способ сломать те же фотографии — убрать роут `app/media/players/[...path]`:
  на проде путь к фото относительный, оптимизатор считает картинку локальной и
  ищет её у себя, а не у бэкенда. Симптом одинаковый и обманчивый: вместо
  аватара в углу виден его `alt`, то есть ник игрока. Rewrite вместо роута тут
  не работает — `rewrites()` вычисляются на сборке и запекаются в
  `routes-manifest.json`, а `API_INTERNAL_URL` появляется только в рантайме.
- Всё, что начинается с `/api/`, в проде уходит на FastAPI — nginx не смотрит,
  есть ли такой роут в Next (`location /api/` в `nginx/nginx.conf`). Роут Next
  под этим префиксом молча недостижим: именно так сброс кеша из админки не
  работал в проде вовсе, отвечая бэкендовым 404 в проглоченный `.catch()`,
  тогда как в dev без nginx всё выглядело исправным. Новые
  server-роуты фронтенда заводить вне `/api/`.
- Фото игроков рисует `next/image`, и он пережимает уже пережатый нами JPEG
  ВТОРОЙ раз. Дефолтное `quality` у него 75 — этого мало везде, где лицо
  видно: на странице игрока, в превью админки и особенно в аватарке 32px,
  куда портретное фото ужимается в двадцать раз. Поэтому у всех трёх
  `quality={90}` (значение обязано быть в `images.qualities`, иначе Next 16
  молча округлит его обратно к 75), а у аватарки ещё и `sizes` вдвое больше
  её реальных 32px: браузер берёт кандидат 64w на обычном экране и 128w на
  ретине, и кружок перестаёт быть пятном ценой ~2 КБ на строку.
- Мелкий текст админки поднят на ступень через `.admin-ui` в `globals.css`
  (класс висит на `(dashboard)/layout.tsx` и на странице логина), а не
  правкой `text-xs`/`text-sm` по файлам — иначе следующая страница снова
  приедет с размерами публичного сайта.
- Светлая тема — это переопределение самих токенов `ink-*`/`brand-*` в
  `globals.css` под `html[data-theme="light"]`, а не второй набор классов по
  компонентам: утилиты Tailwind v4 ссылаются на `var(--color-*)` в точке
  применения, включая варианты с прозрачностью. Отсюда правило: цвет в
  разметке задаётся токеном. Исключения ровно два, и оба намеренные —
  `text-white` на красных заливках (в светлой теме `ink-50` почти чёрный, и
  контраст на `brand-600` падал до 3:1) и `bg-black/60` под модалкой (`ink-950`
  в светлой теме сам почти белый). Контраст обеих палитр проверяет
  `node scripts/check-contrast.mjs`.
- Тема хранится кукой `theme`, а не в `localStorage`: `layout.tsx` читает её
  на сервере и сразу отдаёт `data-theme` на `<html>`. Inline-скрипт в `<head>`
  сделал бы то же, но упёрся бы в CSP с nonce (см. `proxy.ts`) и всё равно
  успевал бы мигнуть тёмной темой. Цена — `cookies()` в корневом layout: `/`
  и `/_not-found` стали динамическими, остальные страницы и так `force-dynamic`.
  Дефолт — тёмная тема: бренд клуба чёрно-красный, светлая включается кнопкой.
- У эмблемы есть светлый вариант файла (`logo-*-light.png`): в исходнике белая
  линейная графика на прозрачном фоне, и на бумаге от знака остаётся одно
  красное «МАФИЯ». Подменяет его CSS (`content: url(...)` под `data-theme`),
  поэтому разметка, `alt` и `drop-shadow` в геро-блоке не меняются. Фильтром
  (`invert` + `hue-rotate`) обойтись нельзя — вместе с белым он уводит в розовый
  и фирменный красный.
- Даты турнира — `<input type="date">` (не `datetime-local`): это плейсхолдер
  периода, а не точное время; `lib/format.ts` конвертирует в/из ISO через
  фиксированное смещение Москвы (+03:00, без перехода на летнее время с 2014).
- Форма игры (`GameForm`) на вкладке «Игры» создаёт и редактирует только
  funky/training; для существующей турнирной игры турнир/этап показываются
  read-only — переставить их оттуда нельзя (см. раздел 7.3).
- Планировщик и форма оценки — разные экраны одной вкладки: первый заводит
  пустые слоты для записи в боте, вторая вносит в них результат. Кнопка
  «Добавить» рядом с заголовком — третий, независимый путь: игра сразу с
  результатом, минуя запись (раздел 5.3, пункт 3).

---

## 11. Telegram-бот — структура кода

`aiogram 3`, long polling (`Dispatcher.start_polling`, без вебхука). Бот —
тонкий клиент: вся работа с данными идёт через `ApiClient` (`httpx`), сам он
Postgres не видит.

### 11.1 Один живой экран на раздел

Главное правило интерфейса, вокруг которого построен весь бот:

* нажатие инлайн-кнопки **редактирует то же самое сообщение** — в чате не
  появляется ничего нового, и клавиатуры предыдущего шага не остаётся;
* обычное сообщение (ввод текста или команда) **удаляет прошлый экран и
  присылает новый** — разговор идёт снизу вверх, наверху не копится
  кликабельный мусор.

Обе операции — `app/ui.py` (`edit_screen` / `open_screen`), id текущего экрана
лежит в данных FSM. До этого каждый шаг присылал новое сообщение со своей
клавиатурой: четыре шага записи на игру — четыре живых клавиатуры, и нажатие
на вчерашнюю кнопку «выберите день» уводило в устаревший список.

**Нижнего меню нет.** Reply-клавиатура шлёт в чат обычное текстовое сообщение
на каждое нажатие, и история диалога состояла в основном из «👤 Профиль» и
«📋 Мои регистрации», написанных самим человеком. Разделы открываются
инлайн-кнопками главного экрана (`inline.main_menu_keyboard`, callback
`mn:menu`) и командами из синей кнопки «Меню» — `/menu`, `/games`, `/my`,
`/profile`, `/help`, а у бот-админов ещё `/admin` (`app/commands.py`
выставляет его скоупом на конкретный чат). Единственная оставшаяся
reply-клавиатура — разовый запрос телефона при регистрации: `request_contact`
бывает только у reply-кнопки. Она снимается сразу после получения номера
(`ui.hide_reply_keyboard`), там же снимается и меню, оставшееся у тех, кто
застал прошлую версию бота.

**Руками почти ничего не вводится.** Текстом остались ФИО, ник, анкетные поля
профиля, поиск человека при выдаче прав и текст рассылки. Календарь и сетка
часов уехали вместе с планировщиком в админку сайта. Всё, что человек
всё-таки набрал, бот удаляет из чата сразу после разбора
(`ui.consume_input`): значение он и так показывает в экране раздела, а второй
его копией история только засоряется.

У каждого экрана, кроме корневых, есть «Назад» на родительский экран, у
корневых — «🏠 Меню», а у каждого ожидания текста — «Отмена».

### 11.2 Файлы

```
bot/
  bot.py                    — точка входа: конфиг, storage, Bot/Dispatcher, роутеры,
                               фоновая рассылка решений, подавление безобидных ошибок Telegram
  app/config.py               — BOT_TOKEN / API_BASE_URL / BOT_SERVICE_TOKEN / REDIS_URL из .env
  app/commands.py              — список команд в кнопке «Меню» (общий и админский скоуп)
  app/api_client.py            — HTTP-клиент ко всем /api/bot/* и /api/bot/admin/* эндпоинтам
  app/ui.py                     — open_screen/edit_screen/consume_input: правило «один живой экран» (11.1)
  app/texts.py                   — подписи и словари значений, общие для клавиатур и текстов
  app/states.py                   — FSM только там, где вводится текст (ФИО, ник, анкета, админка)
  app/notifier.py                  — опрос четырёх очередей: решения игрокам (заявки 3.7, правки 3.8),
                                     новые заявки/правки админам (3.7) и «сегодня игры» (раздел 12)
  app/keyboards/inline.py, reply.py — экраны и единственное нижнее меню
  app/handlers/
    common.py                       — /start, /menu, /help, главный экран, catch-all (последним)
    registration.py                   — регистрация: 6 шагов в одном сообщении
    moderation.py                      — решение админа кнопкой: и под уведомлением, и в
                                          разделе «🕓 На проверке» админ-меню (3.8).
                                          Хвост ":q" в callback_data отличает второе от первого:
                                          решение одно, а возвращаться надо в разные места
    profile.py                         — карточка профиля, правка всех полей, включая фото
                                          (у подтверждённого всё это уходит на проверку, 3.8),
                                          повторная заявка после отказа, краткая статистика
    schedule.py                          — запись на игру (с авто-резервом), свои регистрации, состав
    admin.py                              — назначение админов и две рассылки (11.4);
                                             расписание уехало на сайт (раздел 5)
```

`bot/tests/` — два уровня, оба без Telegram и без сети: `test_bot_logic.py` —
чистая логика (сборка текста анонса, граница «прошедшая игра» в клубной зоне,
разбор полей профиля, семантика `ack`), `test_bot_flow.py` — прогон диалогов
через настоящий `Dispatcher` с заглушками `Bot` и `ApiClient`: регистрация,
запись с попаданием в резерв, обе рассылки и подсказка на кнопках уехавшего
планировщика.

### 11.3 Состояние диалогов

FSM по умолчанию в **Redis** (`REDIS_URL`, тот же инстанс, что у rate limit'а
API). На `MemoryStorage` каждый рестарт бота молча терял незавершённые
регистрации, а вместе с ними и ссылку на текущий экран — в чате оставалось
висеть сообщение с рабочими кнопками, которое бот больше не мог ни
отредактировать, ни удалить. Пустой `REDIS_URL` оставляет `MemoryStorage` с
предупреждением в лог — это осознанный вариант для локального запуска.

### 11.4 Запись, резерв и рассылки

**Сначала день, а формат и роль — только если есть из чего выбирать.** Экраны
идут `день -> формат -> роль -> игры`; формат спрашивается, лишь когда в этот
день назначены и фанки, и обучающие, роль — лишь когда у игрока отмечены обе.
Раньше формат был первым экраном и спрашивался всегда, в том числе у человека,
которому нужно просто знать, когда ближайшая игра. «Назад» ведёт на предыдущий
**показанный** экран, а не на предыдущий по схеме: иначе кнопка возвращала бы
на экран, который тут же снова пропускается.

**Своя запись остаётся в списке с галочкой, и та же строка её снимает.**
`GET /api/bot/sessions/open` больше не вычитает игры, на которые человек
записан, — вместо этого отдаёт `my_role`, и строка показывается как
«✅ 18:00 · Фанки · вы записаны (игрок)». Раньше игра из списка исчезала, и
нажатие читалось как «слот куда-то делся», а не «место занято мной». Повторное
нажатие отменяет запись и снимает галочку: запись и отмена — одно действие с
двумя исходами, и отдельный путь через «📋 Мои регистрации» нужен только тем,
кто пришёл туда за составом. Резерв снимается тем же нажатием — на бэкенде это
одна ручка (`unregister` смотрит и в записи, и в очередь), и освободившееся
место так же поднимает первого из очереди.

**Резерв не отдельное действие.** Первые `max_players` занимают места за
столом, все следующие тем же нажатием уходят в очередь и получают свой номер
в ней; при отмене первый из очереди поднимается автоматически и получает
сообщение. Раньше на переполнение показывался экран «мест нет» с кнопкой
«Встать в резерв» — до второго нажатия доходили не все. Штаб (ведущий + двое
судей) очереди не имеет: заменить ведущего из неё некем.

**Анонс игр на неделю** — кнопка «📢 Анонс игр на неделю» в админ-меню.
`GET /api/bot/admin/broadcast/weekly` отдаёт игры ближайших семи дней и список
получателей: все, кроме отклонённых и кроме тех, у кого на эти же игры уже
есть запись или резерв. Бот показывает предпросмотр с числом получателей,
после подтверждения рассылает по одному сообщению с паузой 50 мс (лимит
Telegram — около 30 сообщений в секунду) и отчитывается, сколько доставлено и
сколько человек заблокировали бота. Под сообщением — кнопка «Записаться»,
которая открывает обычный экран записи прямо в нём.

**Произвольное сообщение от админа** — кнопка «✉️ Написать всем». Админ
присылает текст одним сообщением, бот показывает его целиком вместе с числом
получателей (`GET /api/bot/admin/broadcast/audience`: все игроки с
`telegram_id`, кроме отклонённых) и ждёт подтверждения — опечатку в
сообщении, ушедшем всему клубу, уже не отозвать. От анонса аудитория
отличается ровно одним: записавшиеся из неё не вычитаются. Анонс им не нужен,
они уже идут; объявление «сегодня играем в другой аудитории» нужно в первую
очередь как раз им. Отправка — та же машинка, что у анонса, и текст забывается
сразу после старта рассылки, чтобы повторное нажатие из старого экрана не
ушло клубу второй раз.

### 11.5 Чего бот не делает

**Бот не ведёт расписание.** Игровые дни, карточки игр, подтверждение
проведения и «не состоялась» переехали в админку сайта, во вкладку
«Игры → Расписание» (раздел 5). В боте осталось то, чего без Telegram не
сделать: назначить админа человеку, которого знают по @username (его
`telegram_id` появится лишь при первом `/start`), две рассылки — их шлёт тот,
у кого есть токен бота, — и модерация заявок и правок профиля, которая, наоборот,
уехала сюда с сайта (раздел 3.8). Нажатие на кнопку планировщика в экране,
оставшемся у админа со времён до переезда, отвечает подсказкой, куда идти
(`handlers/admin.moved_to_site`).

Бот **не создаёт и не показывает турнирные игры** — ни в меню записи, ни
где-либо ещё: вся сетка турниров ведётся на сайте (раздел 7).

Полная статистика и рейтинг тоже живут только на сайте; в профиле бота
показывается одна строка-сводка (`GET /api/bot/players/me/stats`).

---

## 12. Фоновые задачи

**В процессе API** — ни одной. Здесь был свип, переводивший прошедшие игры в
`played` каждые 5 минут; он снят вместе с `app/tasks.py`, потому что решал не
ту задачу: наступление времени игры ничего не говорит о том, состоялась ли
она, а в «Ждут оценки» из-за этого попадало всё подряд. Теперь переход делает
человек кнопкой в админке сайта (раздел 5).

Уведомлений о переносе игры тоже нет. Пока планировщик жил в боте, он сам
писал записавшимся при смене времени или места; после переезда на сайт это
означало бы либо очередь-мост API → бот, либо второй экземпляр токена
Telegram. Ни того, ни другого ради одного сообщения делать не стали: карточка
слота прямо говорит админу, что о переносе он предупреждает сам.

**В процессе бота**: `app/notifier.py:notifier_loop()` раз в
`CONFIRMATION_POLL_SECONDS` (по умолчанию 60) забирает у API четыре независимые
очереди и рассылает их в Telegram:

- решения админа по заявкам на вступление (раздел 3.7) — игроку;
- решения админа по правкам профиля (раздел 3.8) — игроку;
- новые заявки и правки, ждущие проверки (`GET /api/bot/admin-notifications`) —
  админам, сразу с кнопками решения (раздел 3.8);
- «сегодня игры» (`GET /api/bot/day-reminders`) — всем, кто записан на этот
  день, включая резерв.

Очереди разделены, чтобы недоставленное одного вида не задерживало другие.
Причина, по которой всё это делает бот, а не бэкенд, во всех случаях одна:
сообщение в Telegram — уже не состояние данных, и слать его обязан тот, у кого
есть токен бота. Оповещение админов при этом «мягкое»: адресат может
отсутствовать (ни у одного админа нет Telegram) — тогда очередь просто ждёт,
пока такой админ появится.

**Напоминание о дне игр** (`services/day_reminder_service.py`) уходит за
`REMINDER_LEAD_HOURS` = 3 часа до начала **первой** игры клубного дня — одно
сообщение на человека на день, со списком всех игр этого дня и их мест, а не
по штуке на каждый слот. Метка «уже разослано» (`games.day_reminder_sent_at`)
стоит на той же первой игре: она задаёт и момент отправки, так что второго
места для неё не нужно. День подтверждается ack'ом, только когда у каждого
получателя исход окончательный, — иначе половина записавшихся осталась бы без
напоминания. Просроченные дни (первая игра уже началась) уходят из очереди
сами: напоминать о том, что уже идёт, поздно.

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
  `/admin/games/{id}/edit` требовал бы повторного логина, хотя сессия
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
  Перекодирование обязательно, поэтому его параметры видны на каждом аватаре
  и подобраны под то, как фото показывается (`player_service.store_photo_file`):
  коробка 1024 (на странице игрока фото занимает до 480 физических пикселей,
  и оптимизатор Next жмёт наш файл ещё раз — запас нужен), качество 92,
  `subsampling=0`, LANCZOS, плюс `ImageOps.exif_transpose` — тег поворота мы
  срезаем вместе с остальными метаданными, и без него снятое боком фото
  таким и осталось бы. Бот к тому же принимает картинку, отправленную
  файлом: обычное фото Telegram сжимает сам, ещё до того как его увидит бот.

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

Базовый `docker-compose.yml` поднят по HTTP (`COOKIE_SECURE=false`) — браузер
выбрасывает `Secure`-куки на http-origin, поэтому `COOKIE_SECURE=true` имеет
смысл только вместе с TLS. Это локальный режим.

В продакшне сверху ложится **`docker-compose.prod.yml`**: он подменяет конфиг
nginx на `nginx/nginx-tls.conf` (`:80` — только ACME-проверка и редирект,
`:443` — TLS + HSTS), открывает `443`, добавляет сервис `certbot` и
подставляет домен из корневого `.env` в `NEXT_PUBLIC_SITE_URL` и
`CORS_ORIGINS`. Флаги `-f` не нужны: в корневом `.env` на сервере стоит
`COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml`, поэтому поднять
прод без TLS случайно нельзя. Сертификат выписывается с `--cert-name site`, то
есть путь к нему в конфиге nginx не зависит от домена — домен задан ровно в
одном месте, в `.env`. Пошагово — в [TIMEWEB.md](TIMEWEB.md).

Первый сайт-админ заводится
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
  игру через слот, публичное API отдаёт рейтинг и статистику, пользователь
  бота регистрируется, записывается/резервируется/отменяет с авто-промоушеном.
  Отдельно — планировщик (`test_schedule_planner_flow`: пачка слотов с шагом,
  обзор по дням, предпросмотр конфликтов, правка и удаление слота) и то, что
  осталось от админки бота (`test_bot_admin_management_flow`).
- `test_review_flow.py` — цикл «слот в расписании → подтверждение проведения →
  форма оценки → rated», включая отказ подтвердить ещё не начавшуюся игру,
  удаление несостоявшейся и обе стороны флага `needs_rating` (раздел 5.1).
- `test_bot_reserve_and_broadcast.py` — авто-резерв (первые `max_players` за
  столом, остальные в очередь по порядку, у штаба очереди нет) и обе
  аудитории рассылок: анонс (окно недели, вычет уже записанных и отклонённых)
  и произвольное сообщение (записавшиеся остаются, отклонённые нет).
- `test_tournament_stages.py` / `test_tournament_standings.py` — вся модель
  раздела 7: bulk-создание слотов, единый состав таблицы, финальный этап,
  immutable-привязка слота, отказ бота от турнирных игр.
- `test_tournament_awards.py` — номинации (раздел 7.8): формулы всех пяти
  номинаций и топ-3, счёт только по финальному столу, тай-брейк мест, ручная замена победителя с
  проверкой кандидата, публикация блока и запрет отрицательного Ci.
- `test_scoring.py` — формула среднего балла/бонуса, конвертация попаданий ЛХ
  в очки, обучающие игры вне реплея.
- `test_admin_validation.py`, `test_photo_upload.py`, `test_password_change.py` —
  валидация slug/полей, загрузка фото, смена пароля.
- `test_profile_change_moderation.py` — модерация правок профиля (раздел 3.8):
  текстовое поле не применяется до решения админа, кнопочные применяются
  сразу, у неподтверждённого игрока правка проходит без очереди, повторная
  правка вытесняет прежнюю, занятый за время ожидания ник даёт отказ при
  применении, решение доходит до очереди бота ровно один раз.
- `test_player_confirmation.py` — модерация регистраций из бота (раздел 3.7):
  скрытие неподтверждённого игрока из рейтинга и со страниц сайта, отказ с
  причиной, повторная заявка, очередь решений для бота и её `ack`.
- `test_pass_list.py` — рубеж пропускной недели (включая игру ровно в его
  момент) и отбор людей: только `outside_need_pass`, зато вместе с ведущими,
  судьями и резервом.
- `test_bot_session_lists.py` — главный экран бота: `/sessions/open`,
  `/game-days` и своя карточка `/players/me/stats`. Отбор в
  `registration_service.list_open_sessions` устроен неочевидно (турнирные
  слоты вон, свои записи и резерв вон, дни считаются по московской полуночи),
  а раньше проверялся только косвенно, через запись на игру.
- `test_tournament_crud.py` — жизненный цикл карточки турнира: чтение, правка,
  подсказка slug'а и удаление. Удаление тут главное: оно каскадом уносит
  неоценённые слоты этапов и перенумеровывает все игры клуба, а оценённые не
  отдаёт удалить вовсе.
- `test_site_access.py` — раздача доступа: выданный логин действительно
  пускает на сайт, отозванный перестаёт, права бот-админа снимаются с сайта,
  а приглашение по `@username` можно отозвать до того, как человек нажмёт
  `/start`.
- `test_regressions.py` — дороги, на которых правила обходились: смена одного
  лишь `result` мимо проверки ППК, уход игрока из-за стола в штаб без
  промоушена из резерва, выход с истёкшим access-токеном, `%`/`_` в нике как
  шаблон LIKE и вход мягко удалённого админа.

Бот — `pytest` (`bot/tests/`), без Telegram и без сети. `test_bot_logic.py` —
чистая логика: сборка текста анонса, граница «прошедшая игра» в клубной зоне,
валидация полей профиля, семантика `ack` у рассылки решений (недоставленное
решение остаётся в очереди, заблокировавший бота — нет). `test_bot_flow.py` —
диалоги целиком через настоящий `Dispatcher` с заглушками `Bot` и `ApiClient`:
регистрация, запись с попаданием в резерв одним нажатием, удаление набранного
текста из чата, обе рассылки (включая предпросмотр перед отправкой и то, что
повторное «Разослать» ничего не шлёт), подсказка на кнопках уехавшего
планировщика и уведомление тому, кого подняли из резерва освободившимся
местом — освободить его можно двумя способами (отмена записи и уход за столом
в штаб), сообщение у них одно.

Frontend — `npx tsc --noEmit`, `npx eslint`, `npm run build` (Next.js
типизирует и собирает страницы статически/динамически по разметке в
`app/**/page.tsx`); отдельного unit-рантайма для компонентов сейчас нет,
проверка — сборка + ручная/браузерная верификация ключевых потоков.
