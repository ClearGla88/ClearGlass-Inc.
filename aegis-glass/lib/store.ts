// Short-lived state: single-use token IDs, session revocations, rate-limit
// counters and per-session activity counters.
//
// Production uses Redis (SET NX EX, INCR + EXPIRE) behind this interface. The
// in-memory implementation is for development and tests only: it does not
// survive restarts and does not share state across instances.

export interface KeyValueStore {
  /** Set only if absent. Returns true if this call created the key. */
  setIfAbsent(key: string, value: string, ttlSeconds: number): Promise<boolean>;
  get(key: string): Promise<string | undefined>;
  set(key: string, value: string, ttlSeconds?: number): Promise<void>;
  /** Increment a counter, creating it with the TTL if absent. Returns the new value. */
  increment(key: string, ttlSeconds: number): Promise<number>;
}

interface Entry {
  value: string;
  expiresAtMs?: number;
}

export class MemoryStore implements KeyValueStore {
  private readonly entries = new Map<string, Entry>();
  private readonly nowMs: () => number;

  constructor(nowMs: () => number = Date.now) {
    this.nowMs = nowMs;
  }

  private live(key: string): Entry | undefined {
    const entry = this.entries.get(key);
    if (!entry) return undefined;
    if (entry.expiresAtMs !== undefined && entry.expiresAtMs <= this.nowMs()) {
      this.entries.delete(key);
      return undefined;
    }
    return entry;
  }

  async setIfAbsent(key: string, value: string, ttlSeconds: number): Promise<boolean> {
    if (this.live(key)) return false;
    this.entries.set(key, { value, expiresAtMs: this.nowMs() + ttlSeconds * 1000 });
    return true;
  }

  async get(key: string): Promise<string | undefined> {
    return this.live(key)?.value;
  }

  async set(key: string, value: string, ttlSeconds?: number): Promise<void> {
    this.entries.set(key, {
      value,
      expiresAtMs: ttlSeconds === undefined ? undefined : this.nowMs() + ttlSeconds * 1000,
    });
  }

  async increment(key: string, ttlSeconds: number): Promise<number> {
    const entry = this.live(key);
    if (!entry) {
      this.entries.set(key, { value: "1", expiresAtMs: this.nowMs() + ttlSeconds * 1000 });
      return 1;
    }
    const next = Number(entry.value) + 1;
    entry.value = String(next);
    return next;
  }
}

export interface RateLimitResult {
  allowed: boolean;
  count: number;
  limit: number;
}

/** Fixed-window limiter keyed by bucket name and window index. */
export async function rateLimit(
  store: KeyValueStore,
  bucket: string,
  limit: number,
  windowSeconds: number,
  nowSeconds: number,
): Promise<RateLimitResult> {
  const window = Math.floor(nowSeconds / windowSeconds);
  const count = await store.increment(`rl:${bucket}:${window}`, windowSeconds);
  return { allowed: count <= limit, count, limit };
}
