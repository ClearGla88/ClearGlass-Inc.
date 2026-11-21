// Configuration with a fail-closed production gate.
//
// Mode "demo": in-memory stores, a local KMS and ephemeral random keys, all
// recreated at every start. Fine for evaluation, useless for real data.
// Mode "production": refuses to start until real adapters (Postgres, Redis, a
// cloud KMS, an OIDC provider) and managed keys are configured. This release
// does not ship those adapters, so production mode stops at startup on purpose.

import { createPrivateKey, createPublicKey, generateKeyPairSync, randomBytes, type KeyObject } from "node:crypto";

export type Mode = "demo" | "production";

export function resolveMode(env: Record<string, string | undefined>): Mode {
  const explicit = env.AEGIS_MODE;
  if (explicit === "demo" || explicit === "production") return explicit;
  if (explicit !== undefined) throw new Error(`AEGIS_MODE must be "demo" or "production", got "${explicit}"`);
  // No silent demo in a production build.
  return env.NODE_ENV === "production" ? "production" : "demo";
}

export interface AegisConfig {
  mode: Mode;
  sessionKey: Buffer;
  capabilityKeys: Record<string, Buffer>;
  capabilityActiveKid: string;
  auditMacKey: Buffer;
  pseudonymKey: Buffer;
  receiptPrivate: KeyObject;
  receiptPublic: KeyObject;
  receiptKeyId: string;
  kek: Buffer;
  kekId: string;
}

const PRODUCTION_REQUIREMENTS = [
  "AEGIS_SESSION_KEY or an OIDC provider adapter",
  "AEGIS_CAPABILITY_KEYS and AEGIS_CAPABILITY_ACTIVE_KID from a secret manager",
  "AEGIS_AUDIT_MAC_KEY and AEGIS_PSEUDONYM_KEY from a secret manager",
  "AEGIS_RECEIPT_PRIVATE_KEY (Ed25519, PKCS#8 PEM) and AEGIS_RECEIPT_KEY_ID",
  "a Postgres Repository adapter (db/schema.sql) and an append-only audit sink",
  "a Redis KeyValueStore adapter",
  "a cloud KMS adapter for envelope encryption",
];

export class ProductionNotReadyError extends Error {
  constructor() {
    super(
      "Aegis Glass production mode is not available in this release. It needs:\n - " +
        PRODUCTION_REQUIREMENTS.join("\n - ") +
        "\nSet AEGIS_MODE=demo to evaluate with in-memory stores and ephemeral keys.",
    );
    this.name = "ProductionNotReadyError";
  }
}

function key(bytes = 32): Buffer {
  return randomBytes(bytes);
}

export function loadConfig(env: Record<string, string | undefined> = process.env): AegisConfig {
  const mode = resolveMode(env);
  if (mode === "production") throw new ProductionNotReadyError();

  const receipt = generateKeyPairSync("ed25519");
  return {
    mode,
    sessionKey: key(),
    capabilityKeys: { "demo-1": key() },
    capabilityActiveKid: "demo-1",
    auditMacKey: key(),
    pseudonymKey: key(),
    receiptPrivate: receipt.privateKey,
    receiptPublic: receipt.publicKey,
    receiptKeyId: "demo-receipt-1",
    kek: key(),
    kekId: "demo-kek-1",
  };
}

/** Helper for operators preparing production secrets: parses "kid:base64,kid:base64". */
export function parseKeyring(value: string): Record<string, Buffer> {
  const ring: Record<string, Buffer> = {};
  for (const part of value.split(",")) {
    const [kid, b64] = part.split(":");
    if (!kid || !b64) throw new Error("keyring entries must be kid:base64");
    const k = Buffer.from(b64, "base64");
    if (k.length < 32) throw new Error(`key ${kid} is shorter than 32 bytes`);
    ring[kid] = k;
  }
  return ring;
}

export function receiptKeysFromPem(pem: string): { privateKey: KeyObject; publicKey: KeyObject } {
  const privateKey = createPrivateKey(pem);
  if (privateKey.asymmetricKeyType !== "ed25519") throw new Error("receipt key must be Ed25519");
  return { privateKey, publicKey: createPublicKey(privateKey) };
}
