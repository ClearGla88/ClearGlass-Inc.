// Envelope encryption for stored originals. Each object gets a fresh 256-bit
// data key; the data key is wrapped by a key-encryption key (KEK) held in a KMS.
// The asset and tenant IDs are bound in as additional authenticated data, so a
// ciphertext moved to another asset or tenant fails to decrypt.
//
// LocalKms keeps the KEK in process memory and exists for development and
// tests. Production must use a cloud KMS adapter (AWS KMS GenerateDataKey and
// Decrypt, or equivalent); config.ts refuses to start production without one.

import { createCipheriv, createDecipheriv, randomBytes } from "node:crypto";

export interface DataKey {
  plaintext: Buffer;
  wrapped: Buffer;
  kekId: string;
}

export interface Kms {
  generateDataKey(context: string): Promise<DataKey>;
  unwrap(wrapped: Buffer, kekId: string, context: string): Promise<Buffer>;
}

function gcmSeal(key: Buffer, plaintext: Buffer, aad: Buffer): Buffer {
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", key, iv);
  cipher.setAAD(aad);
  const ct = Buffer.concat([cipher.update(plaintext), cipher.final()]);
  return Buffer.concat([iv, cipher.getAuthTag(), ct]);
}

function gcmOpen(key: Buffer, sealed: Buffer, aad: Buffer): Buffer {
  if (sealed.length < 28) throw new Error("ciphertext too short");
  const iv = sealed.subarray(0, 12);
  const tag = sealed.subarray(12, 28);
  const ct = sealed.subarray(28);
  const decipher = createDecipheriv("aes-256-gcm", key, iv);
  decipher.setAAD(aad);
  decipher.setAuthTag(tag);
  return Buffer.concat([decipher.update(ct), decipher.final()]);
}

export class LocalKms implements Kms {
  private readonly keks: Map<string, Buffer>;
  private readonly activeKekId: string;

  constructor(keks: Record<string, Buffer>, activeKekId: string) {
    for (const [id, key] of Object.entries(keks)) {
      if (key.length !== 32) throw new Error(`KEK ${id} must be 32 bytes`);
    }
    if (!keks[activeKekId]) throw new Error(`active KEK ${activeKekId} missing`);
    this.keks = new Map(Object.entries(keks));
    this.activeKekId = activeKekId;
  }

  async generateDataKey(context: string): Promise<DataKey> {
    const plaintext = randomBytes(32);
    const kek = this.keks.get(this.activeKekId) as Buffer;
    return { plaintext, wrapped: gcmSeal(kek, plaintext, Buffer.from(`kek:${context}`)), kekId: this.activeKekId };
  }

  async unwrap(wrapped: Buffer, kekId: string, context: string): Promise<Buffer> {
    const kek = this.keks.get(kekId);
    if (!kek) throw new Error(`unknown KEK ${kekId}`);
    return gcmOpen(kek, wrapped, Buffer.from(`kek:${context}`));
  }
}

export interface SealedObject {
  alg: "AES-256-GCM";
  kekId: string;
  wrappedKey: string;
  ciphertext: string;
}

function contextFor(tenantId: string, assetId: string): string {
  return `aegis.object.v1|${tenantId}|${assetId}`;
}

export async function sealObject(kms: Kms, tenantId: string, assetId: string, plaintext: Buffer): Promise<SealedObject> {
  const context = contextFor(tenantId, assetId);
  const dk = await kms.generateDataKey(context);
  try {
    const ciphertext = gcmSeal(dk.plaintext, plaintext, Buffer.from(context));
    return { alg: "AES-256-GCM", kekId: dk.kekId, wrappedKey: dk.wrapped.toString("base64"), ciphertext: ciphertext.toString("base64") };
  } finally {
    dk.plaintext.fill(0);
  }
}

export async function openObject(kms: Kms, tenantId: string, assetId: string, sealed: SealedObject): Promise<Buffer> {
  const context = contextFor(tenantId, assetId);
  const key = await kms.unwrap(Buffer.from(sealed.wrappedKey, "base64"), sealed.kekId, context);
  try {
    return gcmOpen(key, Buffer.from(sealed.ciphertext, "base64"), Buffer.from(context));
  } finally {
    key.fill(0);
  }
}
