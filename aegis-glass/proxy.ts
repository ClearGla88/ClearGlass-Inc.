// Runs before every page and API request (Node runtime in Next.js 16).
// Sets a per-request CSP nonce and the baseline security headers, and rejects
// cross-site state-changing API calls early. Route handlers repeat the CSRF
// check, so a future matcher change cannot silently remove it.

import { NextResponse, type NextRequest } from "next/server";
import { BASE_SECURITY_HEADERS, contentSecurityPolicy, CSRF_HEADER, CSRF_HEADER_VALUE } from "./lib/headers.ts";

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

function crossSiteMutation(request: NextRequest): boolean {
  if (!request.nextUrl.pathname.startsWith("/api/") || SAFE_METHODS.has(request.method)) return false;
  if (request.headers.get(CSRF_HEADER) !== CSRF_HEADER_VALUE) return true;
  const origin = request.headers.get("origin");
  const host = request.headers.get("host");
  if (!origin || !host) return true;
  try {
    return new URL(origin).host !== host;
  } catch {
    return true;
  }
}

export function proxy(request: NextRequest) {
  if (crossSiteMutation(request)) {
    return NextResponse.json({ error: "csrf" }, { status: 403, headers: BASE_SECURITY_HEADERS });
  }

  const nonce = Buffer.from(crypto.randomUUID()).toString("base64");
  const csp = contentSecurityPolicy(nonce, { dev: process.env.NODE_ENV === "development" });

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", csp);

  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set("Content-Security-Policy", csp);
  for (const [name, value] of Object.entries(BASE_SECURITY_HEADERS)) response.headers.set(name, value);
  return response;
}

// No header-based exclusions (such as prefetch headers): a caller controls its
// own headers, so any such rule would be a bypass.
export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
