// Media capabilities: short-lived, single-use, session-bound, asset-bound
// tokens that authorize exactly one preview fetch.
//
// Format: base64url(JSON payload) "." base64url(HMAC-SHA256(key[kid], domain || payload))
// The payload is integrity-protected, not encrypted. It carries no personal
// data: user and session identifiers are opaque IDs, never emails.

import { createHmac, randomBytes, timingSafeEqual } from "node:crypto";

const DOMAIN = "aegis.capability.v1.";
const CLOCK_SKEW_SECONDS = 5;

export interface CapabilityPayload {
  v: 1;
  kid: string;
  /** Unique token ID; consumed once. */
  jti: string;
  aid: string;
  tid: string;
  uid: string;
  sid: string;
  act: "view";
  /** Epoch seconds. */
  nbf: number;
  exp: number;
  /** Obligations fixed at issuance. */
  w: number;
  d: number;
  /** Trace token printed in the watermark and stored with the view receipt. */
  tr: string;
  /** Seed for the deterministic watermark layout. */
  seed: number;
}

export type Keyring = Record<string, Buffer>;

export interface CapabilitySigner {
  activeKid: string;
  keys: Keyring;
}

function b64url(buf: Buffer): string {
  return buf.toString("base64url");
}

function mac(key: Buffer, payloadB64: string): Buffer {
  return createHmac("sha256", key).update(DOMAIN).update(payloadB64).digest();
}

export function newTokenId(): string {
  return b64url(randomBytes(16));
}

export function signCapability(signer: CapabilitySigner, payload: Omit<CapabilityPayload, "v" | "kid">): string {
  const key = signer.keys[signer.activeKid];
  if (!key) throw new Error(`active capability key ${signer.activeKid} is missing`);
  const full: CapabilityPayload = { v: 1, kid: signer.activeKid, ...payload };
  const payloadB64 = b64url(Buffer.from(JSON.stringify(full), "utf8"));
  return `${payloadB64}.${b64url(mac(key, payloadB64))}`;
}

export type VerifyResult =
  | { ok: true; payload: CapabilityPayload }
  | { ok: false; reason: "malformed" | "unknown_key" | "bad_signature" | "not_yet_valid" | "expired" };

const TOKEN_SHAPE = /^[A-Za-z0-9_-]{16,4096}\.[A-Za-z0-9_-]{43}$/;

export function verifyCapability(keys: Keyring, token: string, nowSeconds: number): VerifyResult {
  if (typeof token !== "string" || !TOKEN_SHAPE.test(token)) return { ok: false, reason: "malformed" };
  const [payloadB64, sigB64] = token.split(".");

  let payload: CapabilityPayload;
  try {
    payload = JSON.parse(Buffer.from(payloadB64, "base64url").toString("utf8")) as CapabilityPayload;
  } catch {
    return { ok: false, reason: "malformed" };
  }
  if (payload === null || typeof payload !== "object" || payload.v !== 1 || typeof payload.kid !== "string") {
    return { ok: false, reason: "malformed" };
  }

  // Own-property lookup only, so "__proto__" or "constructor" can never select a key.
  const key = Object.prototype.hasOwnProperty.call(keys, payload.kid) ? keys[payload.kid] : undefined;
  if (!key) return { ok: false, reason: "unknown_key" };

  const expected = mac(key, payloadB64);
  const given = Buffer.from(sigB64, "base64url");
  if (given.length !== expected.length || !timingSafeEqual(given, expected)) {
    return { ok: false, reason: "bad_signature" };
  }

  const fields: Array<[unknown, string]> = [
    [payload.jti, "string"], [payload.aid, "string"], [payload.tid, "string"], [payload.uid, "string"],
    [payload.sid, "string"], [payload.tr, "string"], [payload.nbf, "number"], [payload.exp, "number"],
    [payload.w, "number"], [payload.d, "number"], [payload.seed, "number"],
  ];
  if (payload.act !== "view" || fields.some(([value, type]) => typeof value !== type)) {
    return { ok: false, reason: "malformed" };
  }

  if (nowSeconds + CLOCK_SKEW_SECONDS < payload.nbf) return { ok: false, reason: "not_yet_valid" };
  if (nowSeconds - CLOCK_SKEW_SECONDS >= payload.exp) return { ok: false, reason: "expired" };
  return { ok: true, payload };
}
