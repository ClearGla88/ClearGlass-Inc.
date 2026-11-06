import { b64url, canonicalJson, fromB64url, hmacSha256, safeEqual } from "./crypto";

// A media capability authorises exactly one fetch of one derived view.
//
//   v1.<base64url(canonical JSON claims)>.<base64url(HMAC-SHA256)>
//
// It travels in a request header, never in a URL, so it does not land in
// browser history, proxy logs, or Referer headers. It is bound to the session
// (a keyed hash of the session id, not the id itself), to one path, and to a
// short lifetime. Single use is enforced in the database, not here.

export interface CapabilityClaims {
  v: 1;
  /** Capability id; consumed atomically on first use. */
  cid: string;
  vid: string;
  aid: string;
  tid: string;
  /** Keyed session binding. */
  sb: string;
  path: string;
  iat: number;
  exp: number;
}

export const CAPABILITY_HEADER = "x-aegis-capability";
const CLOCK_SKEW_SECONDS = 5;

export const sessionBinding = (key: Buffer, sessionId: string): string =>
  b64url(hmacSha256(key, `aegis-session-binding:v1:${sessionId}`)).slice(0, 22);

export function issueCapability(key: Buffer, claims: CapabilityClaims): string {
  const body = b64url(Buffer.from(canonicalJson(claims)));
  return `v1.${body}.${b64url(hmacSha256(key, `v1.${body}`))}`;
}

export type CapabilityCheck =
  | { ok: true; claims: CapabilityClaims }
  | { ok: false; reason: "malformed" | "bad_signature" | "expired" | "not_yet_valid" | "wrong_path" | "wrong_session" };

export function verifyCapability(
  key: Buffer,
  token: string | null | undefined,
  expect: { now: number; path: string; sessionId: string },
): CapabilityCheck {
  if (!token || token.length > 2048) return { ok: false, reason: "malformed" };
  const parts = token.split(".");
  if (parts.length !== 3 || parts[0] !== "v1") return { ok: false, reason: "malformed" };
  const [, body, sig] = parts as [string, string, string];
  let given: Buffer;
  try {
    given = fromB64url(sig);
  } catch {
    return { ok: false, reason: "malformed" };
  }
  // Signature first: nothing in an unsigned payload is trusted, not even for error messages.
  if (!safeEqual(hmacSha256(key, `v1.${body}`), given)) return { ok: false, reason: "bad_signature" };

  let claims: CapabilityClaims;
  try {
    claims = JSON.parse(fromB64url(body).toString("utf8")) as CapabilityClaims;
  } catch {
    return { ok: false, reason: "malformed" };
  }
  if (claims.v !== 1 || typeof claims.exp !== "number" || typeof claims.iat !== "number") return { ok: false, reason: "malformed" };
  if (expect.now > claims.exp + CLOCK_SKEW_SECONDS) return { ok: false, reason: "expired" };
  if (expect.now + CLOCK_SKEW_SECONDS < claims.iat) return { ok: false, reason: "not_yet_valid" };
  if (claims.path !== expect.path) return { ok: false, reason: "wrong_path" };
  if (!safeEqual(Buffer.from(claims.sb), Buffer.from(sessionBinding(key, expect.sessionId)))) {
    return { ok: false, reason: "wrong_session" };
  }
  return { ok: true, claims };
}
