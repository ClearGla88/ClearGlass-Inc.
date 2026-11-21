// Tamper-evident, append-only audit trail.
//
// Each record carries the SHA-256 hash of its own canonical content plus the
// previous record's hash, so editing or deleting any record breaks every link
// after it. Each hash is also MAC'd with a key the application cannot use to
// rewrite history once records are shipped to immutable storage (production:
// Postgres with an append-only trigger, replicated to object-lock storage).
// Signed checkpoints let an outside party verify a prefix of the log.

import { createHash, createHmac, sign, timingSafeEqual, verify, type KeyObject } from "node:crypto";
import { canonicalJson } from "./canonical.ts";

export const EVENT_TYPES = [
  "authz.decision",
  "capability.issued",
  "capability.denied",
  "media.served",
  "media.denied",
  "rate.limited",
  "risk.state_changed",
  "session.revoked",
  "grant.revoked",
  "honey.accessed",
  "case.opened",
  "trace.resolved",
  "audit.verified",
] as const;
export type EventType = (typeof EVENT_TYPES)[number];

export type AuditValue = string | number | boolean | null;

export interface AuditEvent {
  type: EventType;
  tenantId: string;
  /** Opaque user ID, or "system". Never an email address. */
  actor: string;
  /** The asset, session or case the event is about. */
  subject?: string;
  data: Record<string, AuditValue>;
}

export interface AuditRecord extends AuditEvent {
  seq: number;
  ts: string;
  prevHash: string;
  hash: string;
  mac: string;
}

export interface AuditSink {
  append(record: AuditRecord): Promise<void>;
  last(): Promise<AuditRecord | undefined>;
  all(): Promise<AuditRecord[]>;
}

export class MemoryAuditSink implements AuditSink {
  private readonly records: AuditRecord[] = [];

  async append(record: AuditRecord): Promise<void> {
    this.records.push(Object.freeze({ ...record, data: Object.freeze({ ...record.data }) }) as AuditRecord);
  }

  async last(): Promise<AuditRecord | undefined> {
    return this.records[this.records.length - 1];
  }

  async all(): Promise<AuditRecord[]> {
    return [...this.records];
  }
}

export const GENESIS_HASH = "0".repeat(64);

function recordHash(r: Omit<AuditRecord, "hash" | "mac">): string {
  const body = {
    seq: r.seq,
    ts: r.ts,
    type: r.type,
    tenantId: r.tenantId,
    actor: r.actor,
    subject: r.subject,
    data: r.data,
    prevHash: r.prevHash,
  };
  return createHash("sha256").update(canonicalJson(body)).digest("hex");
}

function recordMac(key: Buffer, hash: string): string {
  return createHmac("sha256", key).update("aegis.audit.v1.").update(hash).digest("hex");
}

export class AuditLog {
  private readonly sink: AuditSink;
  private readonly macKey: Buffer;
  private readonly now: () => Date;
  private tail: Promise<unknown> = Promise.resolve();

  constructor(sink: AuditSink, macKey: Buffer, now: () => Date = () => new Date()) {
    this.sink = sink;
    this.macKey = macKey;
    this.now = now;
  }

  /** Appends are serialized so concurrent requests cannot fork the chain. */
  append(event: AuditEvent): Promise<AuditRecord> {
    const run = this.tail.then(async () => {
      const prev = await this.sink.last();
      const base = {
        ...event,
        data: { ...event.data },
        seq: prev ? prev.seq + 1 : 1,
        ts: this.now().toISOString(),
        prevHash: prev ? prev.hash : GENESIS_HASH,
      };
      const hash = recordHash(base);
      const record: AuditRecord = { ...base, hash, mac: recordMac(this.macKey, hash) };
      await this.sink.append(record);
      return record;
    });
    this.tail = run.catch(() => undefined);
    return run;
  }

  all(): Promise<AuditRecord[]> {
    return this.sink.all();
  }
}

export interface ChainVerification {
  ok: boolean;
  checked: number;
  /** Sequence number of the first bad record, if any. */
  brokenAt?: number;
  problem?: "sequence_gap" | "prev_hash_mismatch" | "hash_mismatch" | "mac_mismatch";
}

export function verifyChain(records: AuditRecord[], macKey: Buffer): ChainVerification {
  let prevHash = GENESIS_HASH;
  let expectedSeq = records.length > 0 ? records[0].seq : 1;
  if (records.length > 0 && records[0].seq === 1 && records[0].prevHash !== GENESIS_HASH) {
    return { ok: false, checked: 0, brokenAt: 1, problem: "prev_hash_mismatch" };
  }
  for (let i = 0; i < records.length; i += 1) {
    const r = records[i];
    if (r.seq !== expectedSeq) return { ok: false, checked: i, brokenAt: r.seq, problem: "sequence_gap" };
    if (i > 0 && r.prevHash !== prevHash) return { ok: false, checked: i, brokenAt: r.seq, problem: "prev_hash_mismatch" };
    const { hash: _hash, mac: _mac, ...rest } = r;
    const computed = recordHash(rest);
    if (computed !== r.hash) return { ok: false, checked: i, brokenAt: r.seq, problem: "hash_mismatch" };
    const expectedMac = Buffer.from(recordMac(macKey, computed), "hex");
    const givenMac = Buffer.from(r.mac, "hex");
    if (givenMac.length !== expectedMac.length || !timingSafeEqual(givenMac, expectedMac)) {
      return { ok: false, checked: i, brokenAt: r.seq, problem: "mac_mismatch" };
    }
    prevHash = r.hash;
    expectedSeq += 1;
  }
  return { ok: true, checked: records.length };
}

export interface Checkpoint {
  seq: number;
  hash: string;
  ts: string;
  signature: string;
}

/** Signed statement "the log up to seq N had head hash H". Publish or escrow it externally. */
export function signCheckpoint(head: AuditRecord, privateKey: KeyObject, at: Date = new Date()): Checkpoint {
  const body = { seq: head.seq, hash: head.hash, ts: at.toISOString() };
  const signature = sign(null, Buffer.from(canonicalJson(body)), privateKey).toString("base64url");
  return { ...body, signature };
}

export function verifyCheckpoint(cp: Checkpoint, publicKey: KeyObject): boolean {
  const body = { seq: cp.seq, hash: cp.hash, ts: cp.ts };
  return verify(null, Buffer.from(canonicalJson(body)), publicKey, Buffer.from(cp.signature, "base64url"));
}
