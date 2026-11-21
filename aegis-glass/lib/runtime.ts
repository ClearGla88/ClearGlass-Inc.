// Process-wide service instance for the Next.js route handlers. Server only.

import "server-only";
import { AuditLog, MemoryAuditSink } from "./audit.ts";
import { loadConfig, type AegisConfig } from "./config.ts";
import { LocalKms } from "./envelope.ts";
import { MemoryObjectStore, MemoryRepository } from "./repository.ts";
import { seedDemo } from "./seed.ts";
import { AegisService } from "./service.ts";
import { MemoryStore } from "./store.ts";

export interface AegisRuntime {
  config: AegisConfig;
  service: AegisService;
}

const globalRef = globalThis as typeof globalThis & { __aegisRuntime?: Promise<AegisRuntime> };

async function build(): Promise<AegisRuntime> {
  const config = loadConfig(); // throws in production mode: fail closed
  const service = new AegisService({
    repo: new MemoryRepository(),
    objects: new MemoryObjectStore(),
    kv: new MemoryStore(),
    kms: new LocalKms({ [config.kekId]: config.kek }, config.kekId),
    audit: new AuditLog(new MemoryAuditSink(), config.auditMacKey),
    keys: {
      capability: { activeKid: config.capabilityActiveKid, keys: config.capabilityKeys },
      auditMac: config.auditMacKey,
      pseudonym: config.pseudonymKey,
      receiptPrivate: config.receiptPrivate,
      receiptPublic: config.receiptPublic,
      receiptKeyId: config.receiptKeyId,
    },
    now: Date.now,
  });
  if (config.mode === "demo") await seedDemo(service, Math.floor(Date.now() / 1000));
  return { config, service };
}

export function getRuntime(): Promise<AegisRuntime> {
  if (!globalRef.__aegisRuntime) {
    globalRef.__aegisRuntime = build().catch((err) => {
      globalRef.__aegisRuntime = undefined;
      throw err;
    });
  }
  return globalRef.__aegisRuntime;
}
