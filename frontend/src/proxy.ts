import { NextRequest, NextResponse } from "next/server";

// Единый proxy (middleware) на все страницы. Делает две вещи:
//  1. Content-Security-Policy с одноразовым nonce для script-src -- строгая
//     защита от XSS. nonce обязан быть свежим на каждый запрос, поэтому CSP
//     живёт здесь, а не в next.config headers() (там значение статичное).
//     Next сам вычитывает nonce из CSP запроса и проставляет его своим
//     скриптам -- при условии ДИНАМИЧЕСКОГО рендера страницы (см. force-dynamic
//     в page.tsx публичных страниц и app/admin/layout.tsx).
//  2. Presence-check сессии для /admin/* (кроме логина) -- чтобы не
//     мигать админкой анониму. Авторитет всё равно бэкенд (require_site_admin).
//
// style-src остаётся 'unsafe-inline': в вёрстке есть inline style-атрибуты
// (динамические ширины в player/lh-distribution, reveal) и <style> в
// <noscript> layout -- строгий style-src их ломает, а инъекция стилей несёт
// несравнимо меньший риск, чем скриптов. upgrade-insecure-requests не ставим:
// HSTS (next.config) уже переводит домен на https, а все сабресурсы
// same-origin.
//
// Прочие заголовки безопасности (HSTS, X-Frame-Options и т.п.) статичны и
// живут в next.config headers().

function buildCsp(nonce: string): string {
  // 'unsafe-eval' нужен только локальному `next dev` (React использует eval для
  // реконструкции стеков ошибок). Завязываемся на ЯВНЫЙ опт-ин, а не на
  // NODE_ENV: в edge-рантайме `next start` NODE_ENV ненадёжно резолвится в
  // "production", и unsafe-eval протекал в прод-CSP. Опт-ин ставит только
  // dev-скрипт (package.json), прод его не выставляет -- секьюр-бай-дефолт.
  const allowUnsafeEval = process.env.CSP_UNSAFE_EVAL === "1";
  return [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${allowUnsafeEval ? " 'unsafe-eval'" : ""}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' blob: data:",
    "font-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ].join("; ");
}

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;

  const nonce = Buffer.from(crypto.randomUUID()).toString("base64");
  const csp = buildCsp(nonce);

  // Гейт админки: редирект аноним -> логин. Ответы из proxy НЕ проходят через
  // next.config headers(), поэтому критичные заголовки ставим тут же.
  if (pathname.startsWith("/admin") && pathname !== "/admin/login") {
    if (!request.cookies.has("refresh_token")) {
      const loginUrl = new URL("/admin/login", request.url);
      loginUrl.searchParams.set("next", pathname);
      const res = NextResponse.redirect(loginUrl);
      res.headers.set("Strict-Transport-Security", "max-age=63072000; includeSubDomains");
      res.headers.set("X-Content-Type-Options", "nosniff");
      res.headers.set("X-Frame-Options", "DENY");
      res.headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
      return res;
    }
  }

  // nonce уходит в рендер двумя путями: в CSP запроса (Next достаёт его оттуда
  // и проставляет своим <script>) и в x-nonce (на случай, если понадобится
  // прочитать его вручную в компоненте через headers()).
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", csp);

  const res = NextResponse.next({ request: { headers: requestHeaders } });
  res.headers.set("Content-Security-Policy", csp);
  return res;
}

export const config = {
  // Все страницы, КРОМЕ api, статики Next и оптимизатора картинок -- им CSP не
  // нужен, а nonce на пререндеренной статике всё равно не сработает. Префетчи
  // next/link тоже пропускаем: у них нет HTML, куда встраивать nonce.
  matcher: [
    {
      source: "/((?!api|_next/static|_next/image|favicon.ico).*)",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
