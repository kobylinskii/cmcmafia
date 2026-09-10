FROM node:20-slim AS build
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# NEXT_PUBLIC_* values get inlined into the client bundle at build time, so
# this has to be a build ARG, not just a runtime env var on the container.
# Leave it empty for same-origin behind nginx (see .env.example).
ARG NEXT_PUBLIC_API_URL=""
ARG NEXT_PUBLIC_BOT_USERNAME=""
ARG NEXT_PUBLIC_SITE_URL=""
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_BOT_USERNAME=$NEXT_PUBLIC_BOT_USERNAME
ENV NEXT_PUBLIC_SITE_URL=$NEXT_PUBLIC_SITE_URL

# Живой бэкенд на сборке НЕ нужен: все страницы, читающие API, помечены
# `export const dynamic = "force-dynamic"` (см. src/app/**/page.tsx), поэтому
# на этапе сборки Next в него не ходит, а lib/api.ts на незаданный
# API_INTERNAL_URL подставляет заглушку, которую никто не запрашивает.
# Значит `docker compose build` работает на чистой машине без поднятой базы.
# Реальное значение приходит в рантайме из docker-compose.yml (http://api:8000).
# ARG оставлен на случай, если какая-то страница снова станет статической:
# тогда её пререндер упрётся в этот адрес, и его можно будет задать на сборке.
ARG API_INTERNAL_URL=""
ENV API_INTERNAL_URL=$API_INTERNAL_URL

RUN npm run build

FROM node:20-slim AS run
WORKDIR /app
ENV NODE_ENV=production
# Next standalone по умолчанию слушает localhost -> за пределами контейнера
# (edge Railway, docker-хост) в него не достучаться, отдаёт 502 connection
# refused. Слушаем на всех интерфейсах. PORT на Railway приходит из окружения
# ($PORT), локально/в compose падаем на 3000.
ENV HOSTNAME="0.0.0.0"
ENV PORT=3000

COPY --from=build /app/public ./public
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static

EXPOSE 3000
CMD ["node", "server.js"]
