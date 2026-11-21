import { b64url, fromB64url, hmacSha256, safeEqual } from "./crypto";

// The session cookie carries only a signed session id. Everything else
// (user, roles, auth strength, revocation, pause) is read from the database on
// every request, so revoking a session takes effect immediately.

export const SESSION_COOKIE_SECURE = "__Host-aegis_session";
export const SESSION_COOKIE_DEV = "aegis_session";

export const cookieNameFor = (appOrigin: string): string => (appOrigin.startsWith("https://") ? SESSION_COOKIE_SECURE : SESSION_COOKIE_DEV);

export function sealSessionId(key: Buffer, sessionId: string): string {
  const body = b64url(Buffer.from(sessionId));
  return `v1.${body}.${b64url(hmacSha256(key, `aegis-session:v1:${body}`))}`;
}

export function unsealSessionId(key: Buffer, value: string | undefined | null): string | null {
  if (!value || value.length > 256) return null;
  const parts = value.split(".");
  if (parts.length !== 3 || parts[0] !== "v1") return null;
  const [, body, sig] = parts as [string, string, string];
  try {
    if (!safeEqual(hmacSha256(key, `aegis-session:v1:${body}`), fromB64url(sig))) return null;
    const id = fromB64url(body).toString("utf8");
    return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(id) ? id : null;
  } catch {
    return null;
  }
}

/** HttpOnly, SameSite=Strict, host-only; Secure whenever the app is served over https. */
export function sessionCookie(appOrigin: string, value: string, maxAgeSeconds: number): string {
  const secure = appOrigin.startsWith("https://");
  return [
    `${cookieNameFor(appOrigin)}=${value}`,
    "Path=/",
    "HttpOnly",
    "SameSite=Strict",
    `Max-Age=${Math.max(0, Math.floor(maxAgeSeconds))}`,
    ...(secure ? ["Secure"] : []),
  ].join("; ");
}

export const clearSessionCookie = (appOrigin: string): string => sessionCookie(appOrigin, "", 0);

export function parseCookies(header: string | null): Record<string, string> {
  const out: Record<string, string> = {};
  if (!header) return out;
  for (const part of header.split(";")) {
    const i = part.indexOf("=");
    if (i <= 0) continue;
    const name = part.slice(0, i).trim();
    if (!(name in out)) out[name] = part.slice(i + 1).trim();
  }
  return out;
}
