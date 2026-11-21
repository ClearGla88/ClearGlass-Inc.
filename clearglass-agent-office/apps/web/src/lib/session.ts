// Console sign-in. Server-side only (node:crypto, cookies).
//
// Modes:
// - "required":  OFFICE_CONSOLE_PASSPHRASE and OFFICE_SESSION_SECRET are set. Every page and action needs a
//                signed, HttpOnly, SameSite=Strict session cookie.
// - "locked":    OFFICE_ENV=production without both values. Pages render read-only; actions are refused.
// - "open-dev":  local development with no passphrase. Pages and actions work, and the UI says so.
import { createHash, createHmac, timingSafeEqual } from "node:crypto";
import { cookies } from "next/headers";

export const SESSION_COOKIE = "cg_office_session";
const SESSION_HOURS = 8;

export type AuthMode = "required" | "locked" | "open-dev";

export function authMode(): AuthMode {
  if (process.env.OFFICE_CONSOLE_PASSPHRASE && process.env.OFFICE_SESSION_SECRET) return "required";
  if (process.env.OFFICE_ENV === "production") return "locked";
  return "open-dev";
}

function sign(payload: string): string {
  return createHmac("sha256", process.env.OFFICE_SESSION_SECRET ?? "").update(payload).digest("base64url");
}

function safeEqual(a: string, b: string): boolean {
  const ha = createHash("sha256").update(a).digest();
  const hb = createHash("sha256").update(b).digest();
  return timingSafeEqual(ha, hb);
}

export function checkPassphrase(candidate: string): boolean {
  const expected = process.env.OFFICE_CONSOLE_PASSPHRASE;
  return Boolean(expected) && safeEqual(candidate, expected as string);
}

export function issueToken(now = Date.now()): string {
  const exp = String(now + SESSION_HOURS * 3600 * 1000);
  return `${exp}.${sign(exp)}`;
}

export function validToken(token: string | undefined, now = Date.now()): boolean {
  if (!token) return false;
  const [exp, sig] = token.split(".");
  if (!exp || !sig || !/^\d+$/.test(exp) || Number(exp) < now) return false;
  return safeEqual(sig, sign(exp));
}

export async function isAuthed(): Promise<boolean> {
  const mode = authMode();
  if (mode === "open-dev") return true;
  if (mode === "locked") return false;
  const jar = await cookies();
  return validToken(jar.get(SESSION_COOKIE)?.value);
}

export const sessionCookieOptions = {
  httpOnly: true,
  sameSite: "strict" as const,
  secure: process.env.NODE_ENV === "production",
  path: "/",
  maxAge: SESSION_HOURS * 3600,
};
