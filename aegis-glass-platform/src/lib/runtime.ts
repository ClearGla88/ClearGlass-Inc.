import { mkdir } from "node:fs/promises";
import { join } from "node:path";
import { loadConfig, type AegisConfig } from "./config";
import { openPglite, openPostgres, type Database } from "./db";
import { AegisStore } from "./store";
import { FsBlobStore, type BlobStore } from "./blobstore";
import { LocalKeyWrapper } from "./envelope";
import { AegisService } from "./service";
import { seedDemo } from "./demo";

// Process-wide composition root. Route handlers call getRuntime(); tests build
// their own runtime with createRuntime() and install it with setRuntime().

export interface Runtime {
  config: AegisConfig;
  db: Database;
  store: AegisStore;
  blobs: BlobStore;
  service: AegisService;
}

export async function createRuntime(config: AegisConfig, opts: { blobRoot?: string; seed?: boolean } = {}): Promise<Runtime> {
  let db: Database;
  if (config.databaseUrl) {
    db = openPostgres(config.databaseUrl);
  } else {
    if (config.dataDir) await mkdir(config.dataDir, { recursive: true, mode: 0o700 });
    db = await openPglite(config.dataDir ? join(config.dataDir, "pg") : undefined);
  }
  const store = new AegisStore(db);
  await store.migrate(config.migrationsDir);
  const blobRoot = opts.blobRoot ?? join(config.dataDir ?? "/tmp/aegis-glass", "blobs");
  const blobs = new FsBlobStore(blobRoot);
  const wrapper = new LocalKeyWrapper(config.keys.keks, config.keys.activeKekId);
  const service = new AegisService({ config, store, blobs, wrapper });
  if (opts.seed ?? (config.env !== "production" && config.devLogin)) await seedDemo(service, config);
  return { config, db, store, blobs, service };
}

const GLOBAL_KEY = Symbol.for("aegis-glass.runtime");
type Holder = { [GLOBAL_KEY]?: Promise<Runtime> };

export function getRuntime(): Promise<Runtime> {
  const holder = globalThis as Holder;
  if (!holder[GLOBAL_KEY]) {
    const config = loadConfig();
    if (config.ephemeralKeys && config.env === "development" && config.dataDir) {
      // Ephemeral keys cannot decrypt blobs from an earlier process, so a
      // development data directory is per process.
      config.dataDir = join(config.dataDir, `run-${process.pid}`);
    }
    holder[GLOBAL_KEY] = createRuntime(config);
  }
  return holder[GLOBAL_KEY] as Promise<Runtime>;
}

export function setRuntime(runtime: Runtime | null) {
  const holder = globalThis as Holder;
  if (runtime) holder[GLOBAL_KEY] = Promise.resolve(runtime);
  else delete holder[GLOBAL_KEY];
}
