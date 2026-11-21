// Server-only by construction: node:crypto cannot be bundled into a client component.
import {
  createHash,
  createHmac,
  createPrivateKey,
  createPublicKey,
  generateKeyPairSync,
  randomBytes,
  sign,
  timingSafeEqual,
  verify,
  type KeyObject,
} from "node:crypto";

export const b64url = (buf: Buffer | Uint8Array): string => Buffer.from(buf).toString("base64url");

export function fromB64url(value: string): Buffer {
  if (!/^[A-Za-z0-9_-]*$/.test(value)) throw new Error("invalid base64url");
  return Buffer.from(value, "base64url");
}

export const hmacSha256 = (key: Buffer, data: string | Buffer): Buffer => createHmac("sha256", key).update(data).digest();

export const sha256Hex = (data: string | Buffer): string => createHash("sha256").update(data).digest("hex");

export const randomId = (): string => crypto.randomUUID();

export const randomKey = (bytes = 32): Buffer => randomBytes(bytes);

/** Constant-time comparison that also tolerates length mismatch without leaking timing on content. */
export function safeEqual(a: Buffer, b: Buffer): boolean {
  if (a.length !== b.length) {
    timingSafeEqual(a, a);
    return false;
  }
  return timingSafeEqual(a, b);
}

/**
 * Deterministic JSON: object keys sorted recursively, undefined members dropped.
 * Used for every hash and signature input so that a record re-read from storage
 * reproduces the exact bytes it was sealed with.
 */
export function canonicalJson(value: unknown): string {
  return JSON.stringify(normalize(value));
}

function normalize(value: unknown): unknown {
  if (value === null) return null;
  if (Array.isArray(value)) return value.map((v) => (v === undefined ? null : normalize(v)));
  switch (typeof value) {
    case "string":
    case "boolean":
      return value;
    case "number":
      if (!Number.isFinite(value)) throw new Error("canonicalJson: non-finite number");
      return value;
    case "object": {
      const out: Record<string, unknown> = {};
      for (const key of Object.keys(value as Record<string, unknown>).sort()) {
        const v = (value as Record<string, unknown>)[key];
        if (v !== undefined) out[key] = normalize(v);
      }
      return out;
    }
    default:
      throw new Error(`canonicalJson: unsupported type ${typeof value}`);
  }
}

// ---- Ed25519 (view receipts, audit checkpoints) ----

export interface SigningKeyPair {
  keyId: string;
  privateKey: KeyObject;
  publicKey: KeyObject;
}

export function generateSigningKeyPair(keyId: string): SigningKeyPair {
  const { privateKey, publicKey } = generateKeyPairSync("ed25519");
  return { keyId, privateKey, publicKey };
}

/** Load an Ed25519 private key from a base64url-encoded JWK ({"kty":"OKP","crv":"Ed25519","d":..,"x":..}). */
export function signingKeyFromJwk(keyId: string, encodedJwk: string): SigningKeyPair {
  const jwk = JSON.parse(fromB64url(encodedJwk).toString("utf8")) as Record<string, unknown>;
  if (jwk.kty !== "OKP" || jwk.crv !== "Ed25519" || typeof jwk.d !== "string") {
    throw new Error("receipt signing key must be an Ed25519 private JWK");
  }
  const privateKey = createPrivateKey({ key: jwk as never, format: "jwk" });
  return { keyId, privateKey, publicKey: createPublicKey(privateKey) };
}

export const signBytes = (privateKey: KeyObject, data: Buffer): string => b64url(sign(null, data, privateKey));

export function verifyBytes(publicKey: KeyObject, data: Buffer, signature: string): boolean {
  try {
    return verify(null, data, publicKey, fromB64url(signature));
  } catch {
    return false;
  }
}

// ---- Crockford base32 (human-transcribable trace tokens and pseudonyms) ----

const CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";

export function crockfordEncode(bytes: Buffer, length: number): string {
  let bits = 0;
  let value = 0;
  let out = "";
  for (const byte of bytes) {
    value = (value << 8) | byte;
    bits += 8;
    while (bits >= 5 && out.length < length) {
      out += CROCKFORD[(value >>> (bits - 5)) & 31];
      bits -= 5;
    }
    value &= (1 << bits) - 1;
    if (out.length >= length) break;
  }
  if (out.length < length) throw new Error("crockfordEncode: not enough input bytes");
  return out;
}

/** Normalise a token read from a photo or typed by a person: case, separators, and confusable letters. */
export function crockfordNormalize(input: string): string {
  return input
    .toUpperCase()
    .replace(/[\s-]/g, "")
    .replace(/O/g, "0")
    .replace(/[IL]/g, "1");
}

export const isCrockford = (value: string): boolean => /^[0-9A-HJKMNP-TV-Z]+$/.test(value);
