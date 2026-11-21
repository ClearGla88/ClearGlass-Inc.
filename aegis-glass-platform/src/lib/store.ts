import { readFile, readdir } from "node:fs/promises";
import { join } from "node:path";
import type { AuthLevel, Classification, RiskState, WatermarkDensity } from "./classification";
import type { Action, Grant, Resource, Role } from "./policy";
import type { Database, QueryRunner } from "./db";
import { GENESIS_HASH, computeEventHash, redact, type AuditEvent, type AuditEventInput, type Checkpoint } from "./audit";
import { randomId } from "./crypto";

// All persistence. Every query is parameterised; no SQL is ever built from input.

export interface SessionRecord {
  sessionId: string;
  tenantId: string;
  userId: string;
  authLevel: AuthLevel;
  authTime: number;
  createdAt: number;
  expiresAt: number;
  revokedAt: number | null;
  pausedAt: number | null;
  lastRiskState: RiskState;
}

export interface UserRecord {
  userId: string;
  tenantId: string;
  displayName: string;
  roles: Role[];
}

export interface AssetRecord extends Resource {
  title: string;
  altText: string;
  blobKey: string;
  contentType: string;
  width: number;
  height: number;
  originalDhash: string;
}

export interface ViewRecord {
  viewId: string;
  tenantId: string;
  assetId: string;
  sessionId: string;
  userId: string;
  viewerPseudonym: string;
  traceToken: string;
  capabilityId: string;
  capabilityExpiresAt: number;
  consumedAt: number | null;
  revokedAt: number | null;
  watermarkDensity: WatermarkDensity;
  rotationSeconds: number;
  maxWidth: number;
  riskState: Exclude<RiskState, "CRITICAL">;
  policyVersion: string;
  decisionReasons: string[];
  purpose: string | null;
  derivativeDhash: string | null;
  createdAt: number;
}

export interface ReceiptRecord {
  receiptId: string;
  viewId: string;
  payload: Record<string, unknown>;
  signature: string;
  keyId: string;
}

export interface IncidentRecord {
  incidentId: string;
  tenantId: string | null;
  kind: "honey_access" | "critical_risk" | "leak_report";
  status: string;
  sessionId: string | null;
  viewId: string | null;
  assetId: string | null;
  summary: string;
}

type Row = Record<string, unknown>;
const ms = (v: unknown): number => new Date(v as string).getTime();
const msOrNull = (v: unknown): number | null => (v === null || v === undefined ? null : ms(v));
const iso = (epochMs: number): string => new Date(epochMs).toISOString();

const toSession = (r: Row): SessionRecord => ({
  sessionId: r.session_id as string,
  tenantId: r.tenant_id as string,
  userId: r.user_id as string,
  authLevel: r.auth_level as AuthLevel,
  authTime: ms(r.auth_time),
  createdAt: ms(r.created_at),
  expiresAt: ms(r.expires_at),
  revokedAt: msOrNull(r.revoked_at),
  pausedAt: msOrNull(r.paused_at),
  lastRiskState: r.last_risk_state as RiskState,
});

const toAsset = (r: Row): AssetRecord => ({
  assetId: r.asset_id as string,
  tenantId: r.tenant_id as string,
  ownerId: r.owner_id as string,
  title: r.title as string,
  altText: r.alt_text as string,
  classification: r.classification as Classification,
  compartment: (r.compartment as string | null) ?? null,
  honey: r.honey as boolean,
  revoked: r.revoked_at !== null && r.revoked_at !== undefined,
  blobKey: r.blob_key as string,
  contentType: r.content_type as string,
  width: Number(r.width),
  height: Number(r.height),
  originalDhash: r.original_dhash as string,
});

const toView = (r: Row): ViewRecord => ({
  viewId: r.view_id as string,
  tenantId: r.tenant_id as string,
  assetId: r.asset_id as string,
  sessionId: r.session_id as string,
  userId: r.user_id as string,
  viewerPseudonym: r.viewer_pseudonym as string,
  traceToken: r.trace_token as string,
  capabilityId: r.capability_id as string,
  capabilityExpiresAt: ms(r.capability_expires_at),
  consumedAt: msOrNull(r.consumed_at),
  revokedAt: msOrNull(r.revoked_at),
  watermarkDensity: r.watermark_density as WatermarkDensity,
  rotationSeconds: Number(r.rotation_seconds),
  maxWidth: Number(r.max_width),
  riskState: r.risk_state as ViewRecord["riskState"],
  policyVersion: r.policy_version as string,
  decisionReasons: r.decision_reasons as string[],
  purpose: (r.purpose as string | null) ?? null,
  derivativeDhash: (r.derivative_dhash as string | null) ?? null,
  createdAt: ms(r.created_at),
});

const toGrant = (r: Row): Grant => ({
  grantId: r.grant_id as string,
  tenantId: r.tenant_id as string,
  subjectUserId: (r.subject_user_id as string | null) ?? null,
  subjectRole: (r.subject_role as Role | null) ?? null,
  assetId: (r.asset_id as string | null) ?? null,
  compartment: (r.compartment as string | null) ?? null,
  actions: r.actions as Action[],
  purpose: (r.purpose as string | null) ?? null,
  notBefore: Math.floor(ms(r.not_before) / 1000),
  expiresAt: Math.floor(ms(r.expires_at) / 1000),
  revoked: r.revoked_at !== null && r.revoked_at !== undefined,
});

const toEvent = (r: Row): AuditEvent => ({
  seq: Number(r.seq),
  eventId: r.event_id as string,
  ts: r.ts as string,
  type: r.type as AuditEvent["type"],
  tenantId: (r.tenant_id as string | null) ?? null,
  actor: r.actor as string,
  severity: r.severity as AuditEvent["severity"],
  subject: r.subject as AuditEvent["subject"],
  data: r.data as Record<string, unknown>,
  prevHash: r.prev_hash as string,
  hash: r.hash as string,
});

export class AegisStore {
  constructor(readonly db: Database) {}

  async migrate(migrationsDir: string): Promise<string[]> {
    await this.db.exec("CREATE TABLE IF NOT EXISTS aegis_schema_migrations (id text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())");
    const applied = new Set((await this.db.query<{ id: string }>("SELECT id FROM aegis_schema_migrations")).rows.map((r) => r.id));
    const files = (await readdir(migrationsDir)).filter((f) => /^\d{3}_[a-z0-9_]+\.sql$/.test(f)).sort();
    const ran: string[] = [];
    for (const file of files) {
      if (applied.has(file)) continue;
      const sql = await readFile(join(migrationsDir, file), "utf8");
      await this.db.transaction(async (tx) => {
        await this.execIn(tx, sql);
        await tx.query("INSERT INTO aegis_schema_migrations (id) VALUES ($1)", [file]);
      });
      ran.push(file);
    }
    return ran;
  }

  // Multi-statement migration text inside a transaction. Split on statement
  // boundaries outside dollar-quoted function bodies.
  private async execIn(tx: QueryRunner, sql: string) {
    const statements: string[] = [];
    let current = "";
    let inDollar = false;
    for (const line of sql.split("\n")) {
      if (/^\s*--/.test(line) && !inDollar) continue;
      if ((line.match(/\$\$/g) ?? []).length % 2 === 1) inDollar = !inDollar;
      current += line + "\n";
      if (!inDollar && /;\s*$/.test(line)) {
        statements.push(current.trim());
        current = "";
      }
    }
    if (current.trim()) statements.push(current.trim());
    for (const statement of statements) await tx.query(statement);
  }

  // ---- tenants, users, sessions ----

  async insertTenant(t: { tenantId: string; name: string; pseudonym: string }) {
    await this.db.query("INSERT INTO tenants (tenant_id, name, pseudonym) VALUES ($1, $2, $3) ON CONFLICT (tenant_id) DO NOTHING", [
      t.tenantId,
      t.name,
      t.pseudonym,
    ]);
  }

  async tenantPseudonym(tenantId: string): Promise<string | null> {
    const r = await this.db.query<{ pseudonym: string }>("SELECT pseudonym FROM tenants WHERE tenant_id = $1", [tenantId]);
    return r.rows[0]?.pseudonym ?? null;
  }

  async insertUser(u: UserRecord) {
    await this.db.query(
      "INSERT INTO users (user_id, tenant_id, display_name, roles) VALUES ($1, $2, $3, $4) ON CONFLICT (user_id) DO NOTHING",
      [u.userId, u.tenantId, u.displayName, u.roles],
    );
  }

  async getUser(userId: string): Promise<UserRecord | null> {
    const r = await this.db.query<Row>("SELECT * FROM users WHERE user_id = $1", [userId]);
    const row = r.rows[0];
    return row
      ? { userId: row.user_id as string, tenantId: row.tenant_id as string, displayName: row.display_name as string, roles: row.roles as Role[] }
      : null;
  }

  async insertSession(s: { sessionId: string; tenantId: string; userId: string; authLevel: AuthLevel; authTime: number; createdAt: number; expiresAt: number }) {
    await this.db.query(
      "INSERT INTO sessions (session_id, tenant_id, user_id, auth_level, auth_time, created_at, expires_at) VALUES ($1, $2, $3, $4, $5, $6, $7)",
      [s.sessionId, s.tenantId, s.userId, s.authLevel, iso(s.authTime), iso(s.createdAt), iso(s.expiresAt)],
    );
  }

  async getSession(sessionId: string): Promise<SessionRecord | null> {
    const r = await this.db.query<Row>("SELECT * FROM sessions WHERE session_id = $1", [sessionId]);
    return r.rows[0] ? toSession(r.rows[0]) : null;
  }

  /** Revokes the session and every outstanding view issued to it, in one transaction. */
  async revokeSession(sessionId: string, now: number): Promise<boolean> {
    return this.db.transaction(async (tx) => {
      const r = await tx.query("UPDATE sessions SET revoked_at = $2 WHERE session_id = $1 AND revoked_at IS NULL RETURNING session_id", [sessionId, iso(now)]);
      await tx.query("UPDATE views SET revoked_at = $2 WHERE session_id = $1 AND revoked_at IS NULL", [sessionId, iso(now)]);
      return r.rows.length > 0;
    });
  }

  async pauseSession(sessionId: string, now: number): Promise<boolean> {
    return this.db.transaction(async (tx) => {
      const r = await tx.query("UPDATE sessions SET paused_at = $2 WHERE session_id = $1 AND paused_at IS NULL RETURNING session_id", [sessionId, iso(now)]);
      await tx.query("UPDATE views SET revoked_at = $2 WHERE session_id = $1 AND revoked_at IS NULL", [sessionId, iso(now)]);
      return r.rows.length > 0;
    });
  }

  async setSessionRisk(sessionId: string, state: RiskState) {
    await this.db.query("UPDATE sessions SET last_risk_state = $2 WHERE session_id = $1", [sessionId, state]);
  }

  // ---- assets and grants ----

  async insertAsset(a: AssetRecord & { kekId: string }) {
    await this.db.query(
      `INSERT INTO assets (asset_id, tenant_id, owner_id, title, alt_text, classification, compartment, honey,
                           blob_key, content_type, width, height, original_dhash, kek_id)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)`,
      [a.assetId, a.tenantId, a.ownerId, a.title, a.altText, a.classification, a.compartment, a.honey, a.blobKey, a.contentType, a.width, a.height, a.originalDhash, a.kekId],
    );
  }

  async getAsset(assetId: string): Promise<AssetRecord | null> {
    const r = await this.db.query<Row>("SELECT * FROM assets WHERE asset_id = $1", [assetId]);
    return r.rows[0] ? toAsset(r.rows[0]) : null;
  }

  /** Catalogue for the workspace. Deliberately omits the honey flag. */
  async listAssets(tenantId: string): Promise<Array<{ assetId: string; title: string; classification: Classification }>> {
    const r = await this.db.query<Row>(
      "SELECT asset_id, title, classification FROM assets WHERE tenant_id = $1 AND revoked_at IS NULL ORDER BY created_at, asset_id",
      [tenantId],
    );
    return r.rows.map((x) => ({ assetId: x.asset_id as string, title: x.title as string, classification: x.classification as Classification }));
  }

  /** Full records, for entitlement filtering inside the service. Never sent to a client as-is. */
  async listAssetRecords(tenantId: string): Promise<AssetRecord[]> {
    const r = await this.db.query<Row>("SELECT * FROM assets WHERE tenant_id = $1 AND revoked_at IS NULL ORDER BY created_at, asset_id", [tenantId]);
    return r.rows.map(toAsset);
  }

  async revokeAsset(assetId: string, now: number): Promise<boolean> {
    return this.db.transaction(async (tx) => {
      const r = await tx.query("UPDATE assets SET revoked_at = $2 WHERE asset_id = $1 AND revoked_at IS NULL RETURNING asset_id", [assetId, iso(now)]);
      await tx.query("UPDATE views SET revoked_at = $2 WHERE asset_id = $1 AND revoked_at IS NULL", [assetId, iso(now)]);
      return r.rows.length > 0;
    });
  }

  async insertGrant(g: Grant & { createdBy: string }) {
    await this.db.query(
      `INSERT INTO grants (grant_id, tenant_id, subject_user_id, subject_role, asset_id, compartment, actions, purpose, not_before, expires_at, created_by)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)`,
      [g.grantId, g.tenantId, g.subjectUserId, g.subjectRole, g.assetId, g.compartment, g.actions, g.purpose, iso(g.notBefore * 1000), iso(g.expiresAt * 1000), g.createdBy],
    );
  }

  async revokeGrant(grantId: string, now: number) {
    await this.db.query("UPDATE grants SET revoked_at = $2 WHERE grant_id = $1 AND revoked_at IS NULL", [grantId, iso(now)]);
  }

  async listActiveGrants(tenantId: string): Promise<Grant[]> {
    const r = await this.db.query<Row>("SELECT * FROM grants WHERE tenant_id = $1 AND revoked_at IS NULL", [tenantId]);
    return r.rows.map(toGrant);
  }

  // ---- views, capabilities, receipts ----

  async insertView(v: Omit<ViewRecord, "consumedAt" | "revokedAt" | "derivativeDhash">) {
    await this.db.query(
      `INSERT INTO views (view_id, tenant_id, asset_id, session_id, user_id, viewer_pseudonym, trace_token, capability_id,
                          capability_expires_at, watermark_density, rotation_seconds, max_width, risk_state, policy_version,
                          decision_reasons, purpose, created_at)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17)`,
      [
        v.viewId, v.tenantId, v.assetId, v.sessionId, v.userId, v.viewerPseudonym, v.traceToken, v.capabilityId,
        iso(v.capabilityExpiresAt), v.watermarkDensity, v.rotationSeconds, v.maxWidth, v.riskState, v.policyVersion,
        v.decisionReasons, v.purpose, iso(v.createdAt),
      ],
    );
  }

  async getView(viewId: string): Promise<ViewRecord | null> {
    const r = await this.db.query<Row>("SELECT * FROM views WHERE view_id = $1", [viewId]);
    return r.rows[0] ? toView(r.rows[0]) : null;
  }

  /**
   * Single use, enforced atomically: only the first request whose capability id,
   * view, and session all match flips consumed_at. A replay or a race loses.
   */
  async consumeCapability(viewId: string, capabilityId: string, sessionId: string, now: number): Promise<ViewRecord | null> {
    const r = await this.db.query<Row>(
      `UPDATE views SET consumed_at = $4
        WHERE view_id = $1 AND capability_id = $2 AND session_id = $3
          AND consumed_at IS NULL AND revoked_at IS NULL AND capability_expires_at > $4
        RETURNING *`,
      [viewId, capabilityId, sessionId, iso(now)],
    );
    return r.rows[0] ? toView(r.rows[0]) : null;
  }

  async setDerivativeHash(viewId: string, dhash: string) {
    await this.db.query("UPDATE views SET derivative_dhash = $2 WHERE view_id = $1", [viewId, dhash]);
  }

  async findViewByTrace(tenantId: string, traceToken: string): Promise<ViewRecord | null> {
    const r = await this.db.query<Row>("SELECT * FROM views WHERE tenant_id = $1 AND trace_token = $2", [tenantId, traceToken]);
    return r.rows[0] ? toView(r.rows[0]) : null;
  }

  async perceptualIndex(tenantId: string) {
    const assets = await this.db.query<Row>("SELECT asset_id, original_dhash FROM assets WHERE tenant_id = $1", [tenantId]);
    const views = await this.db.query<Row>(
      "SELECT view_id, asset_id, derivative_dhash FROM views WHERE tenant_id = $1 AND derivative_dhash IS NOT NULL",
      [tenantId],
    );
    return {
      assets: assets.rows.map((r) => ({ assetId: r.asset_id as string, dhash: r.original_dhash as string })),
      views: views.rows.map((r) => ({ viewId: r.view_id as string, assetId: r.asset_id as string, dhash: r.derivative_dhash as string })),
    };
  }

  async insertReceipt(rec: ReceiptRecord) {
    await this.db.query("INSERT INTO view_receipts (receipt_id, view_id, payload, signature, key_id) VALUES ($1, $2, $3, $4, $5)", [
      rec.receiptId,
      rec.viewId,
      JSON.stringify(rec.payload),
      rec.signature,
      rec.keyId,
    ]);
  }

  async getReceiptForView(viewId: string): Promise<ReceiptRecord | null> {
    const r = await this.db.query<Row>("SELECT * FROM view_receipts WHERE view_id = $1", [viewId]);
    const row = r.rows[0];
    return row
      ? { receiptId: row.receipt_id as string, viewId: row.view_id as string, payload: row.payload as Record<string, unknown>, signature: row.signature as string, keyId: row.key_id as string }
      : null;
  }

  // ---- risk events ----

  async addRiskEvent(sessionId: string, kind: string, now: number, assetId: string | null = null) {
    await this.db.query("INSERT INTO risk_events (session_id, kind, asset_id, created_at) VALUES ($1, $2, $3, $4)", [sessionId, kind, assetId, iso(now)]);
  }

  async riskCounts(sessionId: string, now: number) {
    const r = await this.db.query<Row>(
      `SELECT kind,
              count(*) FILTER (WHERE created_at > $2) AS last_1m,
              count(*) FILTER (WHERE created_at > $3) AS last_15m
         FROM risk_events WHERE session_id = $1 AND created_at > $3 GROUP BY kind`,
      [sessionId, iso(now - 60_000), iso(now - 15 * 60_000)],
    );
    const distinct = await this.db.query<Row>(
      "SELECT count(DISTINCT asset_id) AS n FROM risk_events WHERE session_id = $1 AND kind = 'view_request' AND created_at > $2",
      [sessionId, iso(now - 5 * 60_000)],
    );
    const counts: Record<string, { last1m: number; last15m: number }> = {};
    for (const row of r.rows) counts[row.kind as string] = { last1m: Number(row.last_1m), last15m: Number(row.last_15m) };
    return { counts, distinctAssetsLast5m: Number(distinct.rows[0]?.n ?? 0) };
  }

  // ---- incidents ----

  async insertIncident(i: Omit<IncidentRecord, "status">) {
    await this.db.query(
      "INSERT INTO incidents (incident_id, tenant_id, kind, session_id, view_id, asset_id, summary) VALUES ($1, $2, $3, $4, $5, $6, $7)",
      [i.incidentId, i.tenantId, i.kind, i.sessionId, i.viewId, i.assetId, i.summary],
    );
  }

  async listIncidents(tenantId: string): Promise<IncidentRecord[]> {
    const r = await this.db.query<Row>("SELECT * FROM incidents WHERE tenant_id = $1 ORDER BY created_at", [tenantId]);
    return r.rows.map((x) => ({
      incidentId: x.incident_id as string,
      tenantId: (x.tenant_id as string | null) ?? null,
      kind: x.kind as IncidentRecord["kind"],
      status: x.status as string,
      sessionId: (x.session_id as string | null) ?? null,
      viewId: (x.view_id as string | null) ?? null,
      assetId: (x.asset_id as string | null) ?? null,
      summary: x.summary as string,
    }));
  }

  // ---- audit chain ----

  /** Appends one event under a row lock on the chain head, so concurrent writers serialise. */
  async appendAudit(input: AuditEventInput, now: number): Promise<AuditEvent> {
    return this.db.transaction(async (tx) => {
      const head = (await tx.query<Row>("SELECT seq, hash FROM audit_chain_head WHERE id FOR UPDATE")).rows[0];
      const prevSeq = Number(head?.seq ?? 0);
      const prevHash = (head?.hash as string | undefined) ?? GENESIS_HASH;
      const base = {
        seq: prevSeq + 1,
        eventId: randomId(),
        ts: iso(now),
        type: input.type,
        tenantId: input.tenantId,
        actor: input.actor,
        severity: input.severity,
        subject: input.subject ?? {},
        data: redact(input.data),
        prevHash,
      };
      const event: AuditEvent = { ...base, hash: computeEventHash(base) };
      await tx.query(
        `INSERT INTO audit_events (seq, event_id, ts, type, tenant_id, actor, severity, subject, data, prev_hash, hash)
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)`,
        [event.seq, event.eventId, event.ts, event.type, event.tenantId, event.actor, event.severity, JSON.stringify(event.subject), JSON.stringify(event.data), event.prevHash, event.hash],
      );
      await tx.query("UPDATE audit_chain_head SET seq = $1, hash = $2 WHERE id", [event.seq, event.hash]);
      return event;
    });
  }

  async listAudit(): Promise<AuditEvent[]> {
    return (await this.db.query<Row>("SELECT * FROM audit_events ORDER BY seq")).rows.map(toEvent);
  }

  async insertCheckpoint(cp: Checkpoint) {
    await this.db.query("INSERT INTO audit_checkpoints (seq, hash, ts, key_id, signature) VALUES ($1, $2, $3, $4, $5)", [cp.seq, cp.hash, cp.ts, cp.keyId, cp.signature]);
  }

  async listCheckpoints(): Promise<Checkpoint[]> {
    const r = await this.db.query<Row>("SELECT * FROM audit_checkpoints ORDER BY seq");
    return r.rows.map((x) => ({ seq: Number(x.seq), hash: x.hash as string, ts: x.ts as string, keyId: x.key_id as string, signature: x.signature as string }));
  }

  async ping(): Promise<boolean> {
    const r = await this.db.query<{ ok: number }>("SELECT 1 AS ok");
    return r.rows[0]?.ok === 1;
  }
}
