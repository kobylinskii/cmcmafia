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

RUN npm run build

FROM node:20-slim AS run
WORKDIR /app
ENV NODE_ENV=production

COPY --from=build /app/public ./public
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static

EXPOSE 3000
CMD ["node", "server.js"]
