import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { loadConfig } from "@/lib/config";
import { createRuntime, type Runtime } from "@/lib/runtime";
import { PERSONAS, type Persona } from "@/lib/demo";

export interface TestRig {
  rt: Runtime;
  clock: { now: number };
  persona: (key: Persona["key"]) => Persona;
  login: (key: Persona["key"], overrides?: { authLevel?: Persona["authLevel"]; authTime?: number }) => Promise<string>;
  cleanup: () => Promise<void>;
}

/** In-process Postgres (PGlite), a temp blob directory, fresh keys, seeded demo data, and a controllable clock. */
export async function makeRig(opts: { databaseUrl?: string } = {}): Promise<TestRig> {
  const dir = await mkdtemp(join(tmpdir(), "aegis-test-"));
  const config = loadConfig({ AEGIS_ENV: "test", ...(opts.databaseUrl ? { AEGIS_DATABASE_URL: opts.databaseUrl } : {}) });
  const clock = { now: Date.now() };
  const rt = await createRuntime(config, { blobRoot: dir, seed: true });
  // Re-point the service clock at the controllable one.
  (rt.service as unknown as { now: () => number }).now = () => clock.now;
  const persona = (key: Persona["key"]) => PERSONAS.find((p) => p.key === key) as Persona;
  return {
    rt,
    clock,
    persona,
    login: (key, overrides = {}) => {
      const p = persona(key);
      return rt.service.createSession({ tenantId: p.tenantId, userId: p.userId, authLevel: overrides.authLevel ?? p.authLevel, authTime: overrides.authTime ?? clock.now });
    },
    cleanup: async () => {
      await rt.db.close();
      await rm(dir, { recursive: true, force: true });
    },
  };
}

export async function assetIdByTitle(rt: Runtime, tenantId: string, prefix: string): Promise<string> {
  const rows = await rt.store.listAssets(tenantId);
  const hit = rows.find((r) => r.title.startsWith(prefix));
  if (!hit) throw new Error(`no asset titled ${prefix}`);
  return hit.assetId;
}
