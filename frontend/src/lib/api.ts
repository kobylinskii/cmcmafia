// Two different base URLs on purpose:
//
// - PUBLIC_API_URL (NEXT_PUBLIC_*, inlined into the client bundle at build
//   time) is whatever the *browser* can reach: the public site origin behind
//   nginx in production (often left empty -> same-origin relative "/api"),
//   or http://localhost:8000 for local dev without nginx in front. Used by
//   clientFetch (admin panel) and mediaUrl (photo <img> src, even when built
//   server-side -- the URL still has to resolve from the visitor's browser).
// - INTERNAL_API_URL (server-only env var, read at request time, never sent
//   to the client) is how the Next.js *server process* reaches the backend
//   -- inside docker-compose that's the service name (http://api:8000), not
//   the public URL. Used only by serverGet, whose results are plain data,
//   never a URL the browser would need to resolve itself.
//
// Public pages are Server Components: fetch straight from the backend, no
// cookies involved, always fresh (rating/results change whenever an admin
// edits a game). Admin pages are client-rendered and carry the session via
// httpOnly cookies (see proxy.ts for the route gate, CSRF_COOKIE below for
// the double-submit token FastAPI's CSRF check expects).

const PUBLIC_API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
// Falls back to a dummy absolute URL (never actually fetched) rather than "",
// which would throw at URL-construction time -- e.g. during `next build`'s
// page-data-collection pass, before API_INTERNAL_URL is set as a real env var
// at container run time. Every page that calls serverGet is `force-dynamic`
// (see each page.tsx), so this fallback is never hit for a real request.
const INTERNAL_API_URL = process.env.API_INTERNAL_URL || PUBLIC_API_URL || "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function extractMessage(body: unknown): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((d) => {
          const loc = Array.isArray(d?.loc) ? d.loc.filter((p: string) => p !== "body").join(".") : "";
          return loc ? `${loc}: ${d?.msg}` : String(d?.msg ?? "");
        })
        .filter(Boolean)
        .join("; ");
    }
  }
  return "Что-то пошло не так";
}

async function parseResponse<T>(res: Response): Promise<T> {
  const isJson = res.headers.get("content-type")?.includes("application/json");
  const body = isJson ? await res.json().catch(() => null) : null;
  if (!res.ok) {
    throw new ApiError(res.status, extractMessage(body));
  }
  return body as T;
}

/** Server Components: public, unauthenticated reads. Always no-store since
 * results/rating can change any time an admin edits a game. */
export async function serverGet<T>(path: string, searchParams?: Record<string, string | number | undefined>): Promise<T> {
  const url = new URL(path, INTERNAL_API_URL);
  if (searchParams) {
    for (const [key, value] of Object.entries(searchParams)) {
      if (value !== undefined && value !== "") url.searchParams.set(key, String(value));
    }
  }
  const res = await fetch(url, { cache: "no-store" });
  return parseResponse<T>(res);
}

function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

function resolvePublicUrl(path: string): string {
  if (!PUBLIC_API_URL) return path; // same-origin relative, e.g. "/api/..." behind nginx
  return new URL(path, PUBLIC_API_URL).toString();
}

/** Client Components: admin session lives in httpOnly cookies, sent
 * automatically via credentials:"include"; mutating requests also carry the
 * CSRF double-submit header the backend's require_site_admin dependency
 * checks (see backend/app/deps.py). */
export async function clientFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  const isFormData = init.body instanceof FormData;
  if (!isFormData && init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (method !== "GET" && method !== "HEAD") {
    const csrf = readCookie("csrf_token");
    if (csrf) headers.set("X-CSRF-Token", csrf);
  }
  const res = await fetch(resolvePublicUrl(path), {
    ...init,
    method,
    headers,
    credentials: "include",
  });
  return parseResponse<T>(res);
}

export function mediaUrl(path: string | null | undefined): string | null {
  if (!path) return null;
  if (path.startsWith("http")) return path;
  return resolvePublicUrl(path);
}
