import { NextRequest, NextResponse } from "next/server";
import { INTERNAL_API_URL } from "@/lib/api";

/**
 * Прокси браузерных запросов к бэкенду через сервер Next.
 *
 * Нужен, когда перед стеком нет общего reverse-proxy и фронтенд с API живут
 * на РАЗНЫХ доменах (так на Railway: каждый сервис получает свой
 * *.up.railway.app). Без него httpOnly-кука сессии выставляется на домене
 * API, а гейт админки (src/proxy.ts) читает куки со своего домена -- вход
 * «проходит» на бэкенде, но Next тут же редиректит обратно на форму логина.
 *
 * С этим роутом браузер ходит на /api того же домена, что и сайт; Next
 * переправляет запрос на INTERNAL_API_URL и возвращает ответ вместе с
 * Set-Cookie, так что кука садится на домен сайта -- first-party.
 *
 * В docker-compose роут не мешает: там /api до Next не доходит, его раньше
 * перехватывает nginx (см. nginx/nginx.conf). Параллельный роут для картинок
 * -- src/app/media/players/[...path]/route.ts.
 *
 * INTERNAL_API_URL читается в рантайме (не запекается на сборке, в отличие
 * от next.config rewrites) -- поэтому это route handler, а не rewrites().
 */

// Заголовки, которые нельзя тащить один-в-один: они относятся к соединению
// «браузер <-> Next», а не «Next <-> бэкенд», и ломают upstream-запрос.
const STRIP_REQUEST_HEADERS = new Set([
  "host",
  "connection",
  "content-length",
  "transfer-encoding",
  "accept-encoding",
]);

// Заголовки ответа бэкенда, которые Next выставит сам при отдаче body.
const STRIP_RESPONSE_HEADERS = new Set([
  "content-length",
  "content-encoding",
  "transfer-encoding",
  "connection",
  "keep-alive",
]);

async function proxy(request: NextRequest, path: string[]): Promise<Response> {
  if (path.some((segment) => segment.includes("..") || segment.includes("/"))) {
    return new Response("Not found", { status: 404 });
  }

  const target =
    `${INTERNAL_API_URL}/api/${path.map(encodeURIComponent).join("/")}` +
    request.nextUrl.search;

  const headers = new Headers();
  request.headers.forEach((value, key) => {
    if (!STRIP_REQUEST_HEADERS.has(key.toLowerCase())) headers.set(key, value);
  });

  const method = request.method.toUpperCase();
  const hasBody = method !== "GET" && method !== "HEAD";

  const upstream = await fetch(target, {
    method,
    headers,
    body: hasBody ? await request.arrayBuffer() : undefined,
    redirect: "manual",
    cache: "no-store",
  }).catch(() => null);

  if (!upstream) {
    return new Response("Bad gateway", { status: 502 });
  }

  const responseHeaders = new Headers();
  upstream.headers.forEach((value, key) => {
    if (key.toLowerCase() === "set-cookie") return; // переносим отдельно ниже
    if (!STRIP_RESPONSE_HEADERS.has(key.toLowerCase())) responseHeaders.set(key, value);
  });

  const response = new NextResponse(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: responseHeaders,
  });

  // Куки сессии/CSRF: бэкенд ставит их без атрибута Domain, поэтому в ответе
  // с домена сайта они и осядут на домен сайта.
  for (const cookie of upstream.headers.getSetCookie()) {
    response.headers.append("set-cookie", cookie);
  }

  return response;
}

export async function GET(request: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return proxy(request, (await ctx.params).path);
}
export async function POST(request: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return proxy(request, (await ctx.params).path);
}
export async function PUT(request: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return proxy(request, (await ctx.params).path);
}
export async function PATCH(request: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return proxy(request, (await ctx.params).path);
}
export async function DELETE(request: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return proxy(request, (await ctx.params).path);
}
