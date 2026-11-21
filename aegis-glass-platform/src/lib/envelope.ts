import { createCipheriv, createDecipheriv, randomBytes } from "node:crypto";

// Envelope encryption for stored originals.
//
// Every asset gets its own random 256-bit data key. The data key encrypts the
// original (AES-256-GCM); a key-encryption key (KEK) wraps the data key. Only
// wrapped keys are stored. Both layers bind associated data (tenant + asset),
// so a ciphertext copied onto another asset's record fails to decrypt.
//
// LocalKeyWrapper keeps KEKs in process memory (development, CI). Production
// should implement KeyWrapper over a KMS/HSM so KEKs never leave it.

export interface WrappedKey {
  keyId: string;
  iv: string;
  tag: string;
  ciphertext: string;
}

export interface KeyWrapper {
  readonly activeKeyId: string;
  wrap(dataKey: Buffer, aad: Buffer): Promise<WrappedKey>;
  unwrap(wrapped: WrappedKey, aad: Buffer): Promise<Buffer>;
}

function gcmEncrypt(key: Buffer, plaintext: Buffer, aad: Buffer) {
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", key, iv);
  cipher.setAAD(aad);
  const ciphertext = Buffer.concat([cipher.update(plaintext), cipher.final()]);
  return { iv, tag: cipher.getAuthTag(), ciphertext };
}

function gcmDecrypt(key: Buffer, iv: Buffer, tag: Buffer, ciphertext: Buffer, aad: Buffer): Buffer {
  const decipher = createDecipheriv("aes-256-gcm", key, iv);
  decipher.setAAD(aad);
  decipher.setAuthTag(tag);
  return Buffer.concat([decipher.update(ciphertext), decipher.final()]);
}

export class LocalKeyWrapper implements KeyWrapper {
  constructor(
    private readonly keks: ReadonlyMap<string, Buffer>,
    readonly activeKeyId: string,
  ) {
    for (const [id, k] of keks) if (k.length !== 32) throw new Error(`KEK ${id} must be 32 bytes`);
    if (!keks.has(activeKeyId)) throw new Error("active KEK id not present");
  }

  async wrap(dataKey: Buffer, aad: Buffer): Promise<WrappedKey> {
    const kek = this.keks.get(this.activeKeyId) as Buffer;
    const { iv, tag, ciphertext } = gcmEncrypt(kek, dataKey, Buffer.concat([Buffer.from("aegis-kek:v1:"), aad]));
    return { keyId: this.activeKeyId, iv: iv.toString("base64"), tag: tag.toString("base64"), ciphertext: ciphertext.toString("base64") };
  }

  async unwrap(w: WrappedKey, aad: Buffer): Promise<Buffer> {
    const kek = this.keks.get(w.keyId);
    if (!kek) throw new Error(`unknown KEK ${w.keyId}`);
    return gcmDecrypt(
      kek,
      Buffer.from(w.iv, "base64"),
      Buffer.from(w.tag, "base64"),
      Buffer.from(w.ciphertext, "base64"),
      Buffer.concat([Buffer.from("aegis-kek:v1:"), aad]),
    );
  }
}

const MAGIC = Buffer.from("AEG1");

export const assetAad = (tenantId: string, assetId: string): Buffer => Buffer.from(`aegis:asset:v1:${tenantId}:${assetId}`);

/** Container: "AEG1" | uint32 header length | header JSON | ciphertext. */
export async function sealObject(wrapper: KeyWrapper, plaintext: Buffer, aad: Buffer): Promise<{ sealed: Buffer; keyId: string }> {
  const dataKey = randomBytes(32);
  try {
    const { iv, tag, ciphertext } = gcmEncrypt(dataKey, plaintext, aad);
    const wrapped = await wrapper.wrap(dataKey, aad);
    const header = Buffer.from(JSON.stringify({ v: 1, alg: "AES-256-GCM", iv: iv.toString("base64"), tag: tag.toString("base64"), wrapped }));
    const len = Buffer.alloc(4);
    len.writeUInt32BE(header.length);
    return { sealed: Buffer.concat([MAGIC, len, header, ciphertext]), keyId: wrapped.keyId };
  } finally {
    dataKey.fill(0);
  }
}

export async function openObject(wrapper: KeyWrapper, sealed: Buffer, aad: Buffer): Promise<Buffer> {
  if (sealed.length < 8 || !sealed.subarray(0, 4).equals(MAGIC)) throw new Error("not an Aegis sealed object");
  const len = sealed.readUInt32BE(4);
  if (len > 4096 || 8 + len > sealed.length) throw new Error("corrupt sealed object header");
  const header = JSON.parse(sealed.subarray(8, 8 + len).toString("utf8")) as { v: number; iv: string; tag: string; wrapped: WrappedKey };
  if (header.v !== 1) throw new Error("unsupported sealed object version");
  const dataKey = await wrapper.unwrap(header.wrapped, aad);
  try {
    return gcmDecrypt(dataKey, Buffer.from(header.iv, "base64"), Buffer.from(header.tag, "base64"), sealed.subarray(8 + len), aad);
  } finally {
    dataKey.fill(0);
  }
}
