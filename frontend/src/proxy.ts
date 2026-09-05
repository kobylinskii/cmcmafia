import { NextRequest, NextResponse } from "next/server";

// Lightweight gate: presence-check the session cookie before rendering any
// /mafia/admin page (the login page itself is excluded). This is not the
// authority -- the backend verifies and signs every request via
// require_site_admin (see backend/app/deps.py) -- it just avoids flashing
// admin UI to an anonymous visitor and redirects them straight to login.
//
// Checks the refresh cookie, not the access one: access lives 15 minutes, so
// gating on it bounced a working session to the login screen every quarter of
// an hour. While the week-long refresh cookie is present the session is still
// recoverable, and lib/api.ts spends it on the first 401.
export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  if (pathname === "/mafia/admin/login") return NextResponse.next();

  const hasSession = request.cookies.has("refresh_token");
  if (!hasSession) {
    const loginUrl = new URL("/mafia/admin/login", request.url);
    loginUrl.searchParams.set("next", pathname);
    return NextResponse.redirect(loginUrl);
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/mafia/admin/:path*"],
};
