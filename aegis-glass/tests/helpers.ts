import { generateKeyPairSync, randomBytes } from "node:crypto";
import { AuditLog, MemoryAuditSink } from "../lib/audit.ts";
import { LocalKms } from "../lib/envelope.ts";
import { MemoryObjectStore, MemoryRepository } from "../lib/repository.ts";
import { PERSONAS, personaPrincipal, seedDemo } from "../lib/seed.ts";
import { AegisService } from "../lib/service.ts";
import { MemoryStore } from "../lib/store.ts";
import type { Principal } from "../lib/types.ts";

export interface Harness {
  service: AegisService;
  clock: { ms: number };
  auditMacKey: Buffer;
  login(key: string, overrides?: Partial<Principal>): Principal;
}

export async function harness(): Promise<Harness> {
  const clock = { ms: Date.UTC(2026, 10, 21, 15, 0, 0) };
  const now = () => clock.ms;
  const auditMacKey = randomBytes(32);
  const receipt = generateKeyPairSync("ed25519");
  const kek = randomBytes(32);
  const service = new AegisService({
    repo: new MemoryRepository(),
    objects: new MemoryObjectStore(),
    kv: new MemoryStore(now),
    kms: new LocalKms({ k1: kek }, "k1"),
    audit: new AuditLog(new MemoryAuditSink(), auditMacKey, () => new Date(clock.ms)),
    keys: {
      capability: { activeKid: "c1", keys: { c1: randomBytes(32) } },
      auditMac: auditMacKey,
      pseudonym: randomBytes(32),
      receiptPrivate: receipt.privateKey,
      receiptPublic: receipt.publicKey,
      receiptKeyId: "r1",
    },
    now,
  });
  await seedDemo(service, Math.floor(clock.ms / 1000));

  let n = 0;
  const login = (key: string, overrides: Partial<Principal> = {}): Principal => {
    const persona = PERSONAS.find((p) => p.key === key);
    if (!persona) throw new Error(`no persona ${key}`);
    n += 1;
    const p = { ...personaPrincipal(persona, `sess-${key}-${n}`, Math.floor(clock.ms / 1000)), ...overrides };
    void service.registerSession(p, 8 * 3600);
    return p;
  };
  return { service, clock, auditMacKey, login };
}

export function tokenFromUrl(url: string): string {
  const prefix = "/api/media/";
  if (!url.startsWith(prefix)) throw new Error(`unexpected media url ${url}`);
  return url.slice(prefix.length);
}
