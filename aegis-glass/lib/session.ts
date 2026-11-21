// Session cookie for demo mode. Production replaces the issuer with an OIDC
// provider (passkeys for high-sensitivity spaces) but keeps the same Principal
// shape, so nothing downstream changes.
//
// Cookie value: base64url(JSON claims) "." base64url(HMAC-SHA256). HttpOnly,
// Secure, SameSite=Strict, Path=/.

import { createHmac, randomBytes, timingSafeEqual } from "node:crypto";
import type { AuthLevel, Principal, Role } from "./types.ts";
import { AUTH_LEVELS, ROLES } from "./types.ts";

export const SESSION_COOKIE = "aegis_session";
export const DEVICE_COOKIE = "aegis_device";
export const SESSION_TTL_SECONDS = 8 * 3600;

interface Claims {
  v: 1;
  uid: string;
  tid: string;
  name: string;
  roles: Role[];
  al: AuthLevel;
  at: number;
  sid: string;
  iat: number;
  exp: number;
}

function mac(key: Buffer, body: string): Buffer {
  return createHmac("sha256", key).update("aegis.session.v1.").update(body).digest();
}

export function newSessionId(): string {
  return randomBytes(18).toString("base64url");
}

export function newDeviceId(): string {
  return randomBytes(16).toString("base64url");
}

export function issueSessionCookie(key: Buffer, p: Principal, nowSeconds: number, ttlSeconds = SESSION_TTL_SECONDS): string {
  const claims: Claims = {
    v: 1,
    uid: p.userId,
    tid: p.tenantId,
    name: p.displayName,
    roles: p.roles,
    al: p.authLevel,
    at: p.authTime,
    sid: p.sessionId,
    iat: nowSeconds,
    exp: nowSeconds + ttlSeconds,
  };
  const body = Buffer.from(JSON.stringify(claims), "utf8").toString("base64url");
  return `${body}.${mac(key, body).toString("base64url")}`;
}

const COOKIE_SHAPE = /^[A-Za-z0-9_-]{16,4096}\.[A-Za-z0-9_-]{43}$/;

export function readSessionCookie(key: Buffer, value: string | undefined, nowSeconds: number): Principal | undefined {
  if (!value || !COOKIE_SHAPE.test(value)) return undefined;
  const [body, sig] = value.split(".");
  const expected = mac(key, body);
  const given = Buffer.from(sig, "base64url");
  if (given.length !== expected.length || !timingSafeEqual(given, expected)) return undefined;

  let c: Claims;
  try {
    c = JSON.parse(Buffer.from(body, "base64url").toString("utf8")) as Claims;
  } catch {
    return undefined;
  }
  if (
    c?.v !== 1 ||
    typeof c.uid !== "string" ||
    typeof c.tid !== "string" ||
    typeof c.sid !== "string" ||
    typeof c.name !== "string" ||
    !Array.isArray(c.roles) ||
    !c.roles.every((r) => (ROLES as readonly string[]).includes(r)) ||
    !(AUTH_LEVELS as readonly string[]).includes(c.al) ||
    typeof c.exp !== "number" ||
    typeof c.at !== "number" ||
    c.exp <= nowSeconds
  ) {
    return undefined;
  }
  return { userId: c.uid, tenantId: c.tid, displayName: c.name, roles: c.roles, authLevel: c.al, authTime: c.at, sessionId: c.sid };
}

/** Minimal cookie header parser; returns the first value for a name. */
export function cookieValue(header: string | null, name: string): string | undefined {
  if (!header) return undefined;
  for (const part of header.split(";")) {
    const i = part.indexOf("=");
    if (i === -1) continue;
    if (part.slice(0, i).trim() === name) return part.slice(i + 1).trim();
  }
  return undefined;
}

export function sessionCookieHeader(value: string, maxAgeSeconds = SESSION_TTL_SECONDS): string {
  return `${SESSION_COOKIE}=${value}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=${maxAgeSeconds}`;
}

export function deviceCookieHeader(value: string): string {
  return `${DEVICE_COOKIE}=${value}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=${180 * 24 * 3600}`;
}
