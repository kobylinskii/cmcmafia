# Деплой на Railway

Стек «Мафия ВМК» разворачивается на Railway как **один проект с пятью
сервисами**: три собираются из этого репозитория по своим `Dockerfile`, два
подключаются плагинами Railway.

| Сервис на Railway | Что это | Root Directory | Источник |
|---|---|---|---|
| `postgres` | PostgreSQL 16 | — | плагин Railway (Add → Database → PostgreSQL) |
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
| `CORS_ORIGINS` | `["https://${{ web.RAILWAY_PUBLIC_DOMAIN }}"]` — JSON-массив; после привязки своего домена заменить на него |
| `COOKIE_SECURE` | `true` |
| `COOKIE_SAMESITE` | `none`, если `api` и `web` на разных доменах (`*.up.railway.app`); `lax`, если оба на одном registrable-домене (`site.ru` + `api.site.ru`) |
| `COOKIE_DOMAIN` | пусто для разных доменов; `.site.ru` — если сайт и API на поддоменах одного домена |
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
| `API_BASE_URL` | `http://${{ api.RAILWAY_PRIVATE_DOMAIN }}:${{ api.PORT }}` (приватная сеть, без TLS) |
| `BOT_SERVICE_TOKEN` | тот же секрет, что в `api` |
| `REDIS_URL` | `${{ Redis.REDIS_URL }}` |
| `CONFIRMATION_POLL_SECONDS` | `60` (по желанию) |

`bot` не слушает порт — в **Settings** у него не должно быть Public Networking
(это «private service», Railway с этим работает штатно).

### Сервис `web`

Эти переменные Railway автоматически передаёт в `docker build` как `--build-arg`
(они объявлены `ARG` в `frontend/Dockerfile`), поэтому попадают в бандл на сборке:

| Переменная | Значение |
|---|---|
| `NEXT_PUBLIC_API_URL` | `https://${{ api.RAILWAY_PUBLIC_DOMAIN }}` |
| `NEXT_PUBLIC_SITE_URL` | `https://${{ web.RAILWAY_PUBLIC_DOMAIN }}` (или свой домен) |
| `NEXT_PUBLIC_BOT_USERNAME` | username бота без `@` |
| `API_INTERNAL_URL` | `https://${{ api.RAILWAY_PUBLIC_DOMAIN }}` — при сборке приватная сеть недоступна, нужен публичный URL |

> Смена любой из этих переменных требует **редеплоя `web`** (значения вшиты на
> этапе сборки, рантайм их не перечитывает).

---

## 3. Порядок первого деплоя

1. Поднять `Postgres` и `Redis`.
2. Задать переменные `api`, добавить volume, задеплоить. Контейнер на старте
   сам прогоняет `alembic upgrade head`. Дождаться, пока healthcheck `/health`
   станет зелёным.
3. Открыть у `api` Public Networking (Settings → Networking → Generate Domain).
4. Задать переменные `web`, задеплоить.
5. Задать переменные `bot`, задеплоить. В логах — `Start polling`.
6. Проверить: `https://<web>/` открывается, `https://<api>/health` отвечает
   `{"status":"ok"}`, вход в админку сохраняет сессию, бот отвечает на `/start`.

---

## 4. Свои домены

- `web` → `site.ru`, `api` → `api.site.ru` (один registrable-домен →
  `COOKIE_SAMESITE=lax`, `COOKIE_DOMAIN=.site.ru`).
- После привязки обновить `CORS_ORIGINS` в `api`, `NEXT_PUBLIC_API_URL` /
  `NEXT_PUBLIC_SITE_URL` / `API_INTERNAL_URL` в `web` и редеплойнуть `web`.

---

## 5. Что осталось от Compose

`docker-compose.yml`, `nginx/` — только для локального запуска (см. `README.md`).
На Railway они не используются: `railway.json` в каждой папке сервиса говорит
платформе собирать из `Dockerfile` и как запускать/проверять контейнер.
