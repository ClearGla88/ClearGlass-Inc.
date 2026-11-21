// Server-side watermark payload. The visible text identifies a view without
// exposing personal data: no email, no IP address, no real name. Pseudonyms are
// keyed HMACs, so only someone holding the pseudonym key and the user list can
// map one back to a person, and the trace token resolves through the
// view-receipt table, which only investigators can read.

import { createHmac, randomBytes } from "node:crypto";
import type { Classification } from "./types.ts";
import { classificationLabel } from "./types.ts";

const CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";

export function crockford(bytes: Buffer, length: number): string {
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
  return out;
}

/** Stable, non-reversible display identifier, e.g. "V-7K2Q9M4X". */
export function pseudonym(key: Buffer, prefix: string, value: string): string {
  const digest = createHmac("sha256", key).update(`${prefix}:${value}`).digest();
  return `${prefix}-${crockford(digest, 8)}`;
}

/** Random, single-view trace token, e.g. "T-3F9KQ2M7XA". */
export function newTraceToken(): string {
  return `T-${crockford(randomBytes(8), 10)}`;
}

export interface WatermarkIdentity {
  classification: Classification;
  tenantPseudonym: string;
  viewerPseudonym: string;
  sessionFragment: string;
  traceToken: string;
}

function minuteStamp(date: Date): string {
  return `${date.toISOString().slice(0, 16).replace("T", " ")}Z`;
}

export function watermarkLines(id: WatermarkIdentity, at: Date): string[] {
  return [
    `${classificationLabel(id.classification)} · ${id.traceToken}`,
    `${id.viewerPseudonym} · ${id.sessionFragment} · ${id.tenantPseudonym} · ${minuteStamp(at)}`,
  ];
}
