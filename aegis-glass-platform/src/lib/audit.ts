import { canonicalJson, sha256Hex, signBytes, verifyBytes, type SigningKeyPair } from "./crypto";
import type { KeyObject } from "node:crypto";

// Tamper-evident audit trail.
//
// Each event's hash covers its content and the previous event's hash, so
// changing, inserting, or removing any past event breaks every link after it.
// Periodic checkpoints sign the chain head with Ed25519, which stops someone
// with database write access from silently rebuilding the whole chain.
// The database also refuses UPDATE, DELETE, and TRUNCATE on the event table.

export const GENESIS_HASH = "0".repeat(64);
export const CHECKPOINT_EVERY = 50;

export const AUDIT_EVENT_TYPES = [
  "auth.session_created",
  "auth.session_revoked",
  "auth.session_paused",
  "auth.step_up_required",
  "authz.deny",
  "asset.registered",
  "asset.revoked",
  "grant.created",
  "view.capability_issued",
  "view.capability_rejected",
  "view.started",
  "risk.signal_recorded",
  "risk.state_changed",
  "honey.accessed",
  "incident.opened",
  "leak.intake_submitted",
  "leak.trace_resolved",
  "audit.verified",
] as const;
export type AuditEventType = (typeof AUDIT_EVENT_TYPES)[number];

export type Severity = "info" | "notice" | "warning" | "critical";

export interface AuditSubject {
  assetId?: string;
  viewId?: string;
  sessionId?: string;
  grantId?: string;
  incidentId?: string;
  receiptId?: string;
}

export interface AuditEventInput {
  type: AuditEventType;
  tenantId: string | null;
  /** User id, or "system" for automated actions. */
  actor: string;
  severity: Severity;
  subject?: AuditSubject;
  data?: Record<string, unknown>;
}

export interface AuditEvent {
  seq: number;
  eventId: string;
  ts: string;
  type: AuditEventType;
  tenantId: string | null;
  actor: string;
  severity: Severity;
  subject: AuditSubject;
  data: Record<string, unknown>;
  prevHash: string;
  hash: string;
}

export interface Checkpoint {
  seq: number;
  hash: string;
  ts: string;
  keyId: string;
  signature: string;
}

// Keys that must never reach the audit store. Values are replaced, not hashed:
// the audit log is for decisions, not for re-identifying people.
const REDACT = new Set(["email", "ip", "ipaddress", "password", "secret", "cookie", "authorization", "capability", "capabilitytoken", "sessiontoken"]);

export function redact(data: Record<string, unknown> | undefined): Record<string, unknown> {
  if (!data) return {};
  const walk = (v: unknown): unknown => {
    if (Array.isArray(v)) return v.map(walk);
    if (v && typeof v === "object") {
      const out: Record<string, unknown> = {};
      for (const [k, val] of Object.entries(v as Record<string, unknown>)) {
        out[k] = REDACT.has(k.toLowerCase()) ? "[redacted]" : walk(val);
      }
      return out;
    }
    return v;
  };
  return walk(data) as Record<string, unknown>;
}

export function computeEventHash(e: Omit<AuditEvent, "hash">): string {
  return sha256Hex(
    canonicalJson({
      seq: e.seq,
      eventId: e.eventId,
      ts: e.ts,
      type: e.type,
      tenantId: e.tenantId,
      actor: e.actor,
      severity: e.severity,
      subject: e.subject,
      data: e.data,
      prevHash: e.prevHash,
    }),
  );
}

const checkpointBytes = (seq: number, hash: string, ts: string) =>
  Buffer.from(canonicalJson({ domain: "aegis-audit-checkpoint:v1", seq, hash, ts }));

export function signCheckpoint(key: SigningKeyPair, seq: number, hash: string, ts: string): Checkpoint {
  return { seq, hash, ts, keyId: key.keyId, signature: signBytes(key.privateKey, checkpointBytes(seq, hash, ts)) };
}

export type ChainVerification =
  | { ok: true; events: number; checkpoints: number; headSeq: number; headHash: string }
  | { ok: false; failedAtSeq: number; reason: string };

/** Replays the whole chain. Events must be in seq order starting at 1. */
export function verifyChain(events: readonly AuditEvent[], checkpoints: readonly Checkpoint[], publicKey: KeyObject): ChainVerification {
  let prev = GENESIS_HASH;
  const bySeq = new Map<number, string>();
  for (let i = 0; i < events.length; i++) {
    const e = events[i] as AuditEvent;
    if (e.seq !== i + 1) return { ok: false, failedAtSeq: e.seq, reason: "sequence_gap" };
    if (e.prevHash !== prev) return { ok: false, failedAtSeq: e.seq, reason: "broken_link" };
    const { hash, ...rest } = e;
    if (computeEventHash(rest) !== hash) return { ok: false, failedAtSeq: e.seq, reason: "content_altered" };
    bySeq.set(e.seq, hash);
    prev = hash;
  }
  for (const cp of checkpoints) {
    if (bySeq.get(cp.seq) !== cp.hash) return { ok: false, failedAtSeq: cp.seq, reason: "checkpoint_mismatch" };
    if (!verifyBytes(publicKey, checkpointBytes(cp.seq, cp.hash, cp.ts), cp.signature)) {
      return { ok: false, failedAtSeq: cp.seq, reason: "checkpoint_signature_invalid" };
    }
  }
  const last = events[events.length - 1];
  return { ok: true, events: events.length, checkpoints: checkpoints.length, headSeq: last?.seq ?? 0, headHash: last?.hash ?? GENESIS_HASH };
}
