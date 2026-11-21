// Signed view receipts. One per served preview. A receipt binds the trace token
// printed in the watermark to the asset, the pseudonymous viewer, the policy
// version, and the exact bytes served (SHA-256 plus a perceptual hash), and is
// signed with Ed25519 so an investigator can verify it with the public key alone.

import { randomUUID, sign, verify, type KeyObject } from "node:crypto";
import { canonicalJson } from "./canonical.ts";
import type { Classification } from "./types.ts";

export interface ViewReceiptBody {
  receiptId: string;
  traceToken: string;
  tenantId: string;
  assetId: string;
  classification: Classification;
  /** Opaque user ID (resolvable by investigators) and display pseudonym. */
  userId: string;
  viewerPseudonym: string;
  sessionFragment: string;
  capabilityId: string;
  policyVersion: string;
  issuedAt: string;
  servedAt: string;
  previewWidth: number;
  previewHeight: number;
  watermarkDensity: number;
  watermarkEpoch: number;
  servedSha256: string;
  servedDhash: string;
}

export interface ViewReceipt {
  body: ViewReceiptBody;
  signature: string;
  keyId: string;
}

export function newReceiptId(): string {
  return randomUUID();
}

export function signReceipt(body: ViewReceiptBody, privateKey: KeyObject, keyId: string): ViewReceipt {
  const signature = sign(null, Buffer.from(canonicalJson(body)), privateKey).toString("base64url");
  return { body, signature, keyId };
}

export function verifyReceipt(receipt: ViewReceipt, publicKey: KeyObject): boolean {
  return verify(null, Buffer.from(canonicalJson(receipt.body)), publicKey, Buffer.from(receipt.signature, "base64url"));
}
