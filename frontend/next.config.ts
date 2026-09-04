import type { NextConfig } from "next";

// Empty NEXT_PUBLIC_API_URL means same-origin (photos served via nginx at
// /media on the site's own domain) -- next/image needs no remotePattern for
// that. Only register one when photos come from a different origin (local
// dev without nginx, or a separate media host).
const publicApiUrl = process.env.NEXT_PUBLIC_API_URL;
const publicApiHostname = publicApiUrl ? new URL(publicApiUrl).hostname : "";
const isLocalApiHost = publicApiHostname === "localhost" || publicApiHostname === "127.0.0.1";

const nextConfig: NextConfig = {
  output: "standalone",
  images: {
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
