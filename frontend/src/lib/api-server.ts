import { headers } from "next/headers";
import { INTERNAL_API_URL, parseResponse } from "@/lib/api";

// Server-only half of the API client. Kept apart from lib/api.ts because
// next/headers may never be pulled into the client bundle, and lib/api.ts is
// imported by "use client" components (admin forms, nav, photo uploader).

/** Public pages render on the server, so their API calls leave the frontend
 * container instead of the visitor's browser -- and the backend rate-limits by
 * client IP. Without forwarding the visitor's address every SSR request would
 * share a single bucket (60/min for the whole site, see
 * backend/app/rate_limit.py). nginx puts the real address in X-Forwarded-For,
 * and uvicorn is configured to trust it from inside the compose network
 * (FORWARDED_ALLOW_IPS in docker-compose.yml). */
async function forwardedClientHeaders(): Promise<HeadersInit> {
  try {
    const incoming = await headers();
    const forwardedFor = incoming.get("x-forwarded-for");
    return forwardedFor ? { "x-forwarded-for": forwardedFor } : {};
  } catch {
    // Outside a request scope (e.g. a static generation pass) there is no
    // visitor to attribute the call to.
    return {};
  }
}

/** Как долго держится закешированный ответ бэкенда, в секундах.
 *
 * Раньше здесь стоял cache: "no-store", а все публичные страницы были
 * force-dynamic: каждый заход любого посетителя означал полный SSR и поход в
 * API. Данные при этом меняются только когда админ правит игру -- возможно,
 * раз в неделю. Пять минут -- компромисс: свежесть на глаз незаметна, а
 * нагрузка от повторных заходов исчезает. */
export const PUBLIC_REVALIDATE_SECONDS = 300;

/** Тег, которым помечены ВСЕ публичные чтения. Правка в админке сбрасывает его
 * целиком через /revalidate -- иначе изменение (переименование турнира,
 * оценка игры) не появлялось на сайте до истечения пяти минут, хотя в админке
 * уже отображалось. Разделять теги по сущностям смысла мало: почти любая
 * правка задевает и рейтинг, и списки, и страницы игроков. */
export const PUBLIC_CACHE_TAG = "public-data";

/** Server Components: public, unauthenticated reads. */
export async function serverGet<T>(
  path: string,
  searchParams?: Record<string, string | number | undefined>
): Promise<T> {
  const url = new URL(path, INTERNAL_API_URL);
  if (searchParams) {
    for (const [key, value] of Object.entries(searchParams)) {
      if (value !== undefined && value !== "") url.searchParams.set(key, String(value));
    }
  }
  const res = await fetch(url, {
    next: { revalidate: PUBLIC_REVALIDATE_SECONDS, tags: [PUBLIC_CACHE_TAG] },
    headers: await forwardedClientHeaders(),
  });
  return parseResponse<T>(res);
}
