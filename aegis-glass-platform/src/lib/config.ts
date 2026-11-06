import { fromB64url, generateSigningKeyPair, randomKey, signingKeyFromJwk, type SigningKeyPair } from "./crypto";

// Configuration fails closed. In production every key must be supplied,
// distinct, and full-length; anything missing stops startup with the exact
// variable name. Development and test generate ephemeral keys instead.

export class ConfigError extends Error {}

export type AegisEnv = "development" | "test" | "production";

export interface AegisKeys {
  /** HMAC key for media capabilities and session binding. */
  capability: Buffer;
  /** HMAC key for trace-token check symbols. */
  trace: Buffer;
  /** HMAC key for tenant / viewer / session pseudonyms. */
  pseudonym: Buffer;
  /** HMAC key for the session cookie. */
  session: Buffer;
  /** Key-encryption keys by id, and which one wraps new data keys. */
  keks: Map<string, Buffer>;
  activeKekId: string;
  /** Ed25519 key for view receipts and audit checkpoints. */
  signing: SigningKeyPair;
}

export interface AegisConfig {
  env: AegisEnv;
  appOrigin: string;
  databaseUrl: string | null;
  dataDir: string | null;
  migrationsDir: string;
  devLogin: boolean;
  sessionTtlSeconds: number;
  keys: AegisKeys;
  ephemeralKeys: boolean;
}

type Env = Record<string, string | undefined>;

const SYMMETRIC = {
  capability: "AEGIS_CAPABILITY_KEY",
  trace: "AEGIS_TRACE_KEY",
  pseudonym: "AEGIS_PSEUDONYM_KEY",
  session: "AEGIS_SESSION_KEY",
} as const;

function key32(env: Env, name: string): Buffer {
  const raw = env[name];
  if (!raw) throw new ConfigError(`${name} is required in production (32 random bytes, base64url)`);
  let buf: Buffer;
  try {
    buf = fromB64url(raw);
  } catch {
    throw new ConfigError(`${name} must be base64url`);
  }
  if (buf.length !== 32) throw new ConfigError(`${name} must decode to exactly 32 bytes`);
  return buf;
}

export function loadConfig(env: Env = process.env): AegisConfig {
  // A production build with no AEGIS_ENV is treated as production, so a missed
  // variable fails closed instead of silently enabling development sign-in.
  const mode = (env.AEGIS_ENV ?? (env.NODE_ENV === "test" ? "test" : env.NODE_ENV === "production" ? "production" : "development")) as AegisEnv;
  if (!["development", "test", "production"].includes(mode)) throw new ConfigError(`AEGIS_ENV must be development, test, or production`);
  const appOrigin = env.AEGIS_APP_ORIGIN ?? "http://localhost:3000";
  const migrationsDir = env.AEGIS_MIGRATIONS_DIR ?? `${process.cwd()}/db/migrations`;
  const sessionTtlSeconds = Number(env.AEGIS_SESSION_TTL_SECONDS ?? 8 * 3600);

  if (mode === "production") {
    if (!/^https:\/\/[^/]+$/.test(appOrigin)) throw new ConfigError("AEGIS_APP_ORIGIN must be an https origin with no path in production");
    if (!env.AEGIS_DATABASE_URL) throw new ConfigError("AEGIS_DATABASE_URL is required in production");
    if (env.AEGIS_DEV_LOGIN && env.AEGIS_DEV_LOGIN !== "0") throw new ConfigError("AEGIS_DEV_LOGIN must not be enabled in production");
    const sym = Object.fromEntries(Object.entries(SYMMETRIC).map(([k, name]) => [k, key32(env, name)])) as Record<keyof typeof SYMMETRIC, Buffer>;
    const kekId = env.AEGIS_KEK_ID ?? "";
    if (!/^[a-z0-9-]{1,40}$/.test(kekId)) throw new ConfigError("AEGIS_KEK_ID is required in production (lowercase id, e.g. kek-2026-11)");
    const kek = key32(env, "AEGIS_KEK");
    const all = [...Object.values(sym), kek].map((b) => b.toString("hex"));
    if (new Set(all).size !== all.length) throw new ConfigError("every Aegis key must be distinct; reuse across purposes is refused");
    if (!env.AEGIS_SIGNING_JWK) throw new ConfigError("AEGIS_SIGNING_JWK is required in production (Ed25519 private JWK, base64url)");
    const signing = signingKeyFromJwk(env.AEGIS_SIGNING_KEY_ID ?? "sig-1", env.AEGIS_SIGNING_JWK);
    // Identity: production sessions must come from the organisation's OIDC
    // provider with MFA / passkeys. That adapter is not part of this release,
    // so production refuses to start rather than run without real sign-in.
    throw new ConfigError(
      "BLOCKED: production sign-in needs an OIDC identity-provider adapter, which this release does not include. " +
        `Keys and database settings validated (${signing.keyId}); see docs/ARCHITECTURE.md, "Activation checklist".`,
    );
  }

  const keks = new Map([["kek-dev", randomKey()]]);
  return {
    env: mode,
    appOrigin,
    databaseUrl: env.AEGIS_DATABASE_URL ?? null,
    dataDir: mode === "test" ? null : (env.AEGIS_DATA_DIR ?? `${process.cwd()}/.aegis-data`),
    migrationsDir,
    devLogin: env.AEGIS_DEV_LOGIN !== "0",
    sessionTtlSeconds,
    ephemeralKeys: true,
    keys: {
      capability: randomKey(),
      trace: randomKey(),
      pseudonym: randomKey(),
      session: randomKey(),
      keks,
      activeKekId: "kek-dev",
      signing: generateSigningKeyPair("sig-dev"),
    },
  };
}
