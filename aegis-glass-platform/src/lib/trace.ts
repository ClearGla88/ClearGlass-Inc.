import { crockfordEncode, crockfordNormalize, hmacSha256, isCrockford, randomKey, safeEqual } from "./crypto";

// Trace tokens are printed into every protected view. They must survive being
// photographed and retyped, so they use Crockford base32 (no I, L, O, U) and
// carry a keyed check value: a typo or a forged token fails verification
// instead of resolving to the wrong person.
//
//   XXXX-XXXX-CCCC   8 random symbols (40 bits) + 4 HMAC check symbols (20 bits)

const BODY_LEN = 8;
const TAG_LEN = 4;

const tagFor = (traceKey: Buffer, body: string): string =>
  crockfordEncode(hmacSha256(traceKey, `aegis-trace:v1:${body}`), TAG_LEN);

const format = (raw: string): string => `${raw.slice(0, 4)}-${raw.slice(4, 8)}-${raw.slice(8, 12)}`;

export function issueTraceToken(traceKey: Buffer): string {
  const body = crockfordEncode(randomKey(5), BODY_LEN);
  return format(body + tagFor(traceKey, body));
}

export type TraceTokenCheck = { valid: true; token: string } | { valid: false; reason: "malformed" | "bad_check" };

export function verifyTraceToken(traceKey: Buffer, input: string): TraceTokenCheck {
  const raw = crockfordNormalize(input);
  if (raw.length !== BODY_LEN + TAG_LEN || !isCrockford(raw)) return { valid: false, reason: "malformed" };
  const body = raw.slice(0, BODY_LEN);
  const expected = Buffer.from(tagFor(traceKey, body));
  const given = Buffer.from(raw.slice(BODY_LEN));
  if (!safeEqual(expected, given)) return { valid: false, reason: "bad_check" };
  return { valid: true, token: format(raw) };
}

/**
 * Stable, privacy-safe display identifier. It reveals nothing about the person
 * (no name, email, or IP) and can only be resolved to a user by someone who can
 * read the database, which the leak-intake workflow restricts to investigators.
 */
export function pseudonym(key: Buffer, prefix: "T" | "V" | "S", ...parts: string[]): string {
  const symbols = crockfordEncode(hmacSha256(key, `aegis-pseudonym:v1:${prefix}:${parts.join("\u0000")}`), 8);
  return prefix === "S" ? `S-${symbols.slice(0, 4)}` : `${prefix}-${symbols.slice(0, 4)}-${symbols.slice(4, 8)}`;
}
