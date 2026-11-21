import { cookieNameFor, parseCookies, unsealSessionId } from "./session";
import type { Runtime } from "./runtime";
import type { Refusal } from "./service";

// Shared route-handler plumbing: session lookup, CSRF origin checks, rate
// limits, and JSON responses that are never cached.

export const NO_STORE = { "Cache-Control": "no-store, private, max-age=0", Pragma: "no-cache" } as const;

export function json(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json; charset=utf-8", ...NO_STORE, ...headers } });
}

export const refusal = (r: Refusal): Response => json({ error: r.reasons[0] ?? "refused", reasons: r.reasons }, r.httpStatus);

export function sessionIdFrom(request: Request, rt: Runtime): string | null {
  const cookies = parseCookies(request.headers.get("cookie"));
  return unsealSessionId(rt.config.keys.session, cookies[cookieNameFor(rt.config.appOrigin)]);
}

/**
 * CSRF defence for state-changing requests: the Origin header must be ours.
 * Browsers always send Origin on cross-site POSTs, so a missing Origin is only
 * accepted when Fetch Metadata says the request is same-origin.
 */
export function sameOrigin(request: Request, rt: Runtime): boolean {
  const origin = request.headers.get("origin");
  if (origin) return origin === rt.config.appOrigin;
  return request.headers.get("sec-fetch-site") === "same-origin";
}

export const forbiddenOrigin = () => json({ error: "cross_origin_request_refused" }, 403);

// Per-process fixed-window limiter. A multi-instance deployment needs a shared
// store (Redis or Postgres) for limits to hold across instances.
const windows = new Map<string, { start: number; count: number }>();

export function rateLimited(key: string, limit: number, windowMs = 60_000, now = Date.now()): boolean {
  const w = windows.get(key);
  if (!w || now - w.start >= windowMs) {
    windows.set(key, { start: now, count: 1 });
    if (windows.size > 50_000) windows.clear();
    return false;
  }
  w.count += 1;
  return w.count > limit;
}

export const tooMany = () => json({ error: "rate_limited" }, 429, { "Retry-After": "60" });

export function resetRateLimits() {
  windows.clear();
}

export const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
