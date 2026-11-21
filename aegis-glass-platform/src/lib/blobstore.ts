import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { dirname, join, resolve, sep } from "node:path";

// Private object storage. Only sealed (encrypted) bytes are ever written.
// FsBlobStore is for development and CI. Production should implement BlobStore
// over a private bucket with server-side access logging and no public ACLs;
// the application never hands out bucket URLs, so no signed-URL can leak.

export interface BlobStore {
  put(key: string, bytes: Buffer): Promise<void>;
  get(key: string): Promise<Buffer>;
}

const UUID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
const KEY_PATTERN = new RegExp(`^tenants/${UUID}/assets/${UUID}/original\\.aeg$`);

export const blobKeyFor = (tenantId: string, assetId: string): string => `tenants/${tenantId}/assets/${assetId}/original.aeg`;

export class FsBlobStore implements BlobStore {
  private readonly root: string;

  constructor(root: string) {
    this.root = resolve(root);
  }

  private pathFor(key: string): string {
    // Keys are built from validated UUIDs only; anything else is refused, so
    // path traversal is impossible rather than merely filtered.
    if (!KEY_PATTERN.test(key)) throw new Error("invalid blob key");
    const full = resolve(join(this.root, key));
    if (!full.startsWith(this.root + sep)) throw new Error("invalid blob key");
    return full;
  }

  async put(key: string, bytes: Buffer): Promise<void> {
    const full = this.pathFor(key);
    await mkdir(dirname(full), { recursive: true, mode: 0o700 });
    const tmp = `${full}.${process.pid}.${Date.now()}.tmp`;
    await writeFile(tmp, bytes, { mode: 0o600, flag: "wx" });
    await rename(tmp, full);
  }

  async get(key: string): Promise<Buffer> {
    return readFile(this.pathFor(key));
  }
}
