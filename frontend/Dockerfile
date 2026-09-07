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

# Публичные страницы кешируются через ISR (`export const revalidate = 300`), а
# не рендерятся строго по запросу, поэтому Next дёргает бэкенд ещё на сборке.
# Без этого адреса `npm run build` падает на пререндере /mafia с ECONNREFUSED,
# и образ фронтенда невозможно собрать на чистой машине вообще. Значение по
# умолчанию верно для сборки внутри compose-сети; buildkit пользовательские
# сети не поддерживает, поэтому на практике сборка идёт через host-сеть и
# адрес поднятого контейнера api:
#   API=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' cmcmafia-api-1)
#   docker build --network host --build-arg API_INTERNAL_URL=http://$API:8000 \
#     -t cmcmafia-frontend ./frontend
ARG API_INTERNAL_URL="http://api:8000"
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
