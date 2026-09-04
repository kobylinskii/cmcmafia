import { NextRequest, NextResponse } from "next/server";

// Lightweight gate: presence-check the access_token cookie before rendering
// any /mafia/admin page (the login page itself is excluded). This is not the
// authority -- the backend verifies and signs every request via
// require_site_admin (see backend/app/deps.py) -- it just avoids flashing
// admin UI to an anonymous visitor and redirects them straight to login.
export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  if (pathname === "/mafia/admin/login") return NextResponse.next();

  const hasSession = request.cookies.has("access_token");
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
