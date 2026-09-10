# Деплой на Railway

Стек «Мафия ВМК» разворачивается на Railway как **один проект с пятью
сервисами**: три собираются из этого репозитория по своим `Dockerfile`, два
подключаются плагинами Railway.

| Сервис на Railway | Что это | Root Directory | Источник |
|---|---|---|---|
| `postgres` | PostgreSQL 18 | — | плагин Railway (Add → Database → PostgreSQL) |
| `redis` | Redis 7 | — | плагин Railway (Add → Database → Redis) |
| `api` | FastAPI-бэкенд | `backend` | Dockerfile (`backend/railway.json`) |
| `bot` | Telegram-бот (long polling, без порта) | `bot` | Dockerfile (`bot/railway.json`) |
| `web` | Next.js фронтенд | `frontend` | Dockerfile (`frontend/railway.json`) |

nginx из `docker-compose.yml` на Railway **не нужен** — TLS и маршрутизацию по
доменам делает edge самого Railway. `docker-compose.yml` остаётся для локального
запуска и не читается Railway.

---

## 1. Создание сервисов

1. New Project → Deploy from GitHub repo → выбрать этот репозиторий.
2. Railway создаст один сервис. В его **Settings → Root Directory** поставить
   `backend`, переименовать сервис в `api`. Railway подхватит
   `backend/railway.json` (builder = Dockerfile, healthcheck `/health`).
3. **New → GitHub Repo** (тот же репозиторий) ещё дважды: Root Directory `bot`
   и `frontend`, имена `bot` и `web`.
4. **New → Database → PostgreSQL** и **New → Database → Redis**.

Все пять сервисов должны лежать в одном **environment** одного проекта —
тогда работает приватная сеть (`*.railway.internal`) и ссылки на переменные
`${{ api.RAILWAY_PUBLIC_DOMAIN }}` и т.п.

---

## 2. Переменные окружения

Сгенерировать два секрета (одинаковые значения указать там, где сказано):

```bash
openssl rand -hex 32   # -> JWT_SECRET
openssl rand -hex 32   # -> BOT_SERVICE_TOKEN
```

### Сервис `api`

| Переменная | Значение |
|---|---|
| `DATABASE_URL` | `${{ Postgres.DATABASE_URL }}` (схему `postgresql://` бэкенд сам чинит на `postgresql+psycopg://`) |
| `REDIS_URL` | `${{ Redis.REDIS_URL }}` |
| `JWT_SECRET` | сгенерированный секрет |
| `BOT_SERVICE_TOKEN` | сгенерированный секрет (тот же в сервисе `bot`) |
| `CORS_ORIGINS` | `["https://${{ web.RAILWAY_PUBLIC_DOMAIN }}"]` — JSON-массив (браузер к `api` напрямую не ходит, но пусть будет корректным) |
| `COOKIE_SECURE` | `true` |
| `COOKIE_SAMESITE` | `lax` — браузер обращается к API через тот же домен, что и сайт (прокси в `web`, см. ниже), поэтому кука first-party |
| `COOKIE_DOMAIN` | пусто |
| `MEDIA_ROOT` | `/app/media/players` |
| `SUPERADMIN_TELEGRAM_IDS_RAW` | telegram id суперадминов через запятую (то же в `bot`) |
| `BOOTSTRAP_ADMIN_PHONE_RAW` | телефон бут-админа (то же, что `ADMIN_PHONE`/аналог в `bot`) |
| `PORT` | **не задавать** — Railway выставит сам, uvicorn слушает `$PORT` |

**Volume для фото игроков.** Файловая система контейнера на Railway эфемерна.
В сервисе `api`: **Settings → Volumes → Add**, mount path `/app/media`.
Без этого загруженные аватары исчезают при каждом редеплое.

### Сервис `bot`

| Переменная | Значение |
|---|---|
| `BOT_TOKEN` | токен от @BotFather |
| `API_BASE_URL` | `http://${{ api.RAILWAY_PRIVATE_DOMAIN }}:8080` (приватная сеть, без TLS; порт — тот, что слушает контейнер `api`, обычно 8080) |
| `BOT_SERVICE_TOKEN` | тот же секрет, что в `api` |
| `REDIS_URL` | `${{ Redis.REDIS_URL }}` |
| `CONFIRMATION_POLL_SECONDS` | `60` (по желанию) |

`bot` не слушает порт — в **Settings** у него не должно быть Public Networking
(это «private service», Railway с этим работает штатно).

### Сервис `web`

На Railway нет общего nginx, поэтому `web` сам проксирует `/api/*` и
`/media/*` на бэкенд (route handlers `src/app/api/[...path]` и
`src/app/media/players/[...path]`). Для браузера всё на одном домене — куки
сессии становятся first-party, вход в админку работает.

| Переменная | Значение | Когда читается |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | **пусто** (пустая строка) → браузер ходит на `/api` того же домена | сборка (вшивается в бандл) |
| `NEXT_PUBLIC_SITE_URL` | `https://${{ web.RAILWAY_PUBLIC_DOMAIN }}` (или свой домен) | сборка |
| `NEXT_PUBLIC_BOT_USERNAME` | username бота без `@` | сборка |
| `API_INTERNAL_URL` | `https://${{ api.RAILWAY_PUBLIC_DOMAIN }}` — куда сервер `web` шлёт проксируемые и SSR-запросы | сборка **и** рантайм |

> Пустое `NEXT_PUBLIC_API_URL`: в Railway создай переменную со значением `""`
> (пустое поле). Если её вовсе не задать — фронт соберётся с фолбэком
> `http://localhost:8000` и в проде работать не будет.
>
> `API_INTERNAL_URL` указывает на **публичный** адрес `api` (приватная сеть
> при сборке недоступна). Смена любой `NEXT_PUBLIC_*` требует **редеплоя
> `web`** — значения вшиты на этапе сборки.

---

## 3. Порядок первого деплоя

1. Поднять `Postgres` и `Redis`.
2. Задать переменные `api`, добавить volume, задеплоить. Контейнер на старте
   сам прогоняет `alembic upgrade head`. Дождаться, пока healthcheck `/health`
   станет зелёным.
3. Открыть у `api` Public Networking (Settings → Networking → Generate Domain).
4. Задать переменные `web` (в т.ч. `API_INTERNAL_URL` = публичный адрес `api`
   из шага 3, `NEXT_PUBLIC_API_URL` = пусто), задеплоить.
5. Задать переменные `bot`, задеплоить. В логах — `Start polling`.
6. Создать первого администратора сайта (см. раздел 6).
7. Проверить: `https://<web>/` открывается, `https://<api>/health` отвечает
   `{"status":"ok"}`, вход в админку сохраняет сессию, бот отвечает на `/start`.

---

## 4. Свои домены

- `web` → `site.ru`, `api` → `api.site.ru`.
- `NEXT_PUBLIC_SITE_URL` и `API_INTERNAL_URL` в `web` обновить на новые адреса,
  `CORS_ORIGINS` в `api` — тоже, затем редеплой `web`. `NEXT_PUBLIC_API_URL`
  оставить пустым (браузер по-прежнему ходит на `/api` того же домена).

---

## 5. Первый администратор сайта

Регистрации на сайте нет — первый админ создаётся разовой командой
[backend/app/scripts/create_admin.py](backend/app/scripts/create_admin.py)
внутри контейнера `api`.

**Через Railway CLI:**

```bash
npm i -g @railway/cli
railway login
railway link                      # выбрать проект и environment
railway ssh --service api
# внутри контейнера:
python -m app.scripts.create_admin --nickname "Админ" --username root --password "ЗАДАЙ_ПАРОЛЬ"
```

**Без CLI:** `api` → Settings → Deploy → **Custom Start Command** временно
поставить ту же команду `python -m app.scripts.create_admin ...`, задеплоить,
прочитать в Deploy Logs `Site admin ready`, затем **очистить** Custom Start
Command и задеплоить снова.

Вход: `https://<web>/admin/login`. Дальше администраторов и игроков
заводят через саму админку.

---

## 6. Что осталось от Compose

`docker-compose.yml`, `nginx/` — только для локального запуска (см. `README.md`).
На Railway они не используются: `railway.json` в каждой папке сервиса говорит
платформе собирать из `Dockerfile` и как запускать/проверять контейнер.
