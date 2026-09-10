import type { NextConfig } from "next";

// Explicitly EMPTY NEXT_PUBLIC_API_URL means same-origin (photos served via
// nginx at /media on the site's own domain, see docker-compose.yml) --
// next/image needs no remotePattern for that.
//
// Genuinely UNSET (as when running `next build`/`next start` locally without
// any env file, e.g. for a quick manual check) falls back to
// "http://localhost:8000" -- the SAME fallback lib/api.ts's PUBLIC_API_URL
// uses (`?? "http://localhost:8000"`, which only fires on undefined, not on
// an explicit ""). Before this matched the client's fallback, that mismatch
// meant: the browser dutifully requested player photos from
// http://localhost:8000/media/..., but this config saw an falsy/undefined
// publicApiUrl and registered ZERO remote patterns -- so next/image's
// optimizer rejected every single one of those requests with "url parameter
// is not allowed", and every uploaded avatar rendered as a broken image.
const publicApiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const publicApiHostname = publicApiUrl ? new URL(publicApiUrl).hostname : "";
const isLocalApiHost = publicApiHostname === "localhost" || publicApiHostname === "127.0.0.1";

const nextConfig: NextConfig = {
  output: "standalone",
  // Статичные заголовки безопасности ставим на все ответы. Content-Security-
  // Policy сюда НЕ входит: ему нужен свежий nonce на каждый запрос, поэтому он
  // живёт в proxy.ts (middleware). См. src/proxy.ts.
  poweredByHeader: false,
  // Раздел жил по адресу /mafia/*, пока сайт делил домен с чем-то ещё. На
  // своём домене этот префикс стал лишним, но ссылки на него могли разойтись
  // по чатам -- отдаём постоянный редирект вместо 404.
  async redirects() {
    return [
      { source: "/mafia", destination: "/", permanent: true },
      { source: "/mafia/:path*", destination: "/:path*", permanent: true },
    ];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          // Content-Security-Policy теперь ставит proxy.ts (middleware): ему
          // нужен свежий nonce на каждый запрос для script-src, а здесь
          // значение статичное. См. src/proxy.ts.
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
          { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
          { key: "X-Permitted-Cross-Domain-Policies", value: "none" },
          // COEP и CORP намеренно НЕ ставим: COEP требует CORS/CORP на КАЖДОМ
          // сабресурсе (включая og:image из соцсетей и next/image) и вслепую
          // роняет страницу в белый экран -- отдельная задача с прогоном.
        ],
      },
    ];
  },
  images: {
    // 90 -- для фото игрока в его карточке (см. app/mafia/(site)/[slug]).
    // С Next 16 список обязателен, и значения вне его округляются к
    // ближайшему разрешённому.
    qualities: [75, 90],
    remotePatterns: publicApiUrl
      ? [
          {
            protocol: new URL(publicApiUrl).protocol.replace(":", "") as "http" | "https",
            hostname: publicApiHostname,
            port: new URL(publicApiUrl).port || undefined,
            pathname: "/media/**",
          },
        ]
      : [],
    // Next 16's SSRF guard blocks loopback hosts by default; only needed
    // for local dev without nginx, where NEXT_PUBLIC_API_URL points at
    // localhost directly instead of same-origin.
    ...(isLocalApiHost ? { dangerouslyAllowLocalIP: true } : {}),
  },
};

export default nextConfig;
