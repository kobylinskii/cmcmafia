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
