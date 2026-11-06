import { maxDensity, type AuthLevel, type Classification, type RiskState } from "./classification";
import { authorize, entitlementFor, type Grant, type Subject } from "./policy";
import { assessRisk, CLIENT_SIGNALS, RESPONSES, type ClientSignal, type ResponseAction, type RiskAssessment } from "./risk";
import { issueCapability, sessionBinding, verifyCapability } from "./capability";
import { issueTraceToken, pseudonym, verifyTraceToken } from "./trace";
import { epochFor, layoutFor, rotationSecondsFor, watermarkLines } from "./watermark";
import { CHECKPOINT_EVERY, signCheckpoint, verifyChain, type AuditEventInput, type ChainVerification } from "./audit";
import { assetAad, openObject, sealObject, type KeyWrapper } from "./envelope";
import { blobKeyFor, type BlobStore } from "./blobstore";
import { dHash, derivePreview, hamming, inspectUpload } from "./image";
import { canonicalJson, randomId, signBytes, verifyBytes } from "./crypto";
import type { AegisConfig } from "./config";
import type { AegisStore, AssetRecord, ReceiptRecord, SessionRecord, UserRecord } from "./store";

// The customer journey, end to end:
//   requestView -> policy -> risk -> single-use capability (+ watermark spec)
//   serveMedia  -> verify capability -> consume once -> re-run policy -> decrypt
//               -> derive watermarked preview -> sign receipt -> audit
// Every branch, including every refusal, writes to the audit chain.

export const PERCEPTUAL_MATCH_MAX_DISTANCE = 10;

export interface NetworkSignals {
  newDevice: boolean;
  impossibleTravel: boolean;
  badAsnReputation: boolean;
}

export interface ServiceDeps {
  config: AegisConfig;
  store: AegisStore;
  blobs: BlobStore;
  wrapper: KeyWrapper;
  now?: () => number;
  /** Integration point for IdP / edge risk feeds. Defaults to "no signal". */
  networkSignals?: (session: SessionRecord) => Promise<NetworkSignals>;
}

export type Refusal = { ok: false; httpStatus: 400 | 401 | 403 | 404 | 422; reasons: string[] };

export type ViewRequestResult =
  | {
      ok: true;
      status: "permit";
      viewId: string;
      capability: string;
      mediaPath: string;
      expiresAt: string;
      title: string;
      altText: string;
      classification: Classification;
      riskState: RiskState;
      watermark: { density: string; rotationSeconds: number; seed: string; lines: [string, string] };
    }
  | { ok: false; status: "step_up"; httpStatus: 401; requiredAuth: AuthLevel; reasons: string[] }
  | (Refusal & { status: "deny" });

export type MediaResult = { ok: true; bytes: Buffer; contentType: string; receiptId: string; width: number; height: number } | Refusal;

type ActiveSession = { session: SessionRecord; user: UserRecord };

const sec = (ms: number) => Math.floor(ms / 1000);
const iso = (ms: number) => new Date(ms).toISOString();

export class AegisService {
  private readonly now: () => number;
  private readonly networkSignals: (s: SessionRecord) => Promise<NetworkSignals>;

  constructor(private readonly deps: ServiceDeps) {
    this.now = deps.now ?? Date.now;
    this.networkSignals = deps.networkSignals ?? (async () => ({ newDevice: false, impossibleTravel: false, badAsnReputation: false }));
  }

  get store(): AegisStore {
    return this.deps.store;
  }

  private get keys() {
    return this.deps.config.keys;
  }

  // ---------------------------------------------------------------- audit

  async audit(input: AuditEventInput) {
    const event = await this.deps.store.appendAudit(input, this.now());
    if (event.seq % CHECKPOINT_EVERY === 0) await this.checkpoint(event.seq, event.hash, event.ts);
    return event;
  }

  private async checkpoint(seq: number, hash: string, ts: string) {
    await this.deps.store.insertCheckpoint(signCheckpoint(this.keys.signing, seq, hash, ts));
  }

  /** Signs a checkpoint at the current head (e.g. before export or at shift change). */
  async checkpointNow(): Promise<number> {
    const events = await this.deps.store.listAudit();
    const head = events[events.length - 1];
    if (!head) return 0;
    const existing = await this.deps.store.listCheckpoints();
    if (!existing.some((c) => c.seq === head.seq)) await this.checkpoint(head.seq, head.hash, head.ts);
    return head.seq;
  }

  async verifyAudit(actorSessionId: string): Promise<(ChainVerification & { checkedAt: string }) | Refusal> {
    const a = await this.activeSession(actorSessionId);
    if ("httpStatus" in a) return a;
    if (!a.user.roles.some((r) => r === "investigator" || r === "tenant_admin")) return refuse(403, "role_required:investigator_or_tenant_admin");
    const result = verifyChain(await this.deps.store.listAudit(), await this.deps.store.listCheckpoints(), this.keys.signing.publicKey);
    await this.audit({ type: "audit.verified", tenantId: a.session.tenantId, actor: a.user.userId, severity: result.ok ? "info" : "critical", data: { ...result } });
    return { ...result, checkedAt: iso(this.now()) };
  }

  // ------------------------------------------------------------- sessions

  async createSession(input: { tenantId: string; userId: string; authLevel: AuthLevel; authTime?: number }): Promise<string> {
    const now = this.now();
    const sessionId = randomId();
    await this.deps.store.insertSession({
      sessionId,
      tenantId: input.tenantId,
      userId: input.userId,
      authLevel: input.authLevel,
      authTime: input.authTime ?? now,
      createdAt: now,
      expiresAt: now + this.deps.config.sessionTtlSeconds * 1000,
    });
    await this.audit({ type: "auth.session_created", tenantId: input.tenantId, actor: input.userId, severity: "info", subject: { sessionId }, data: { authLevel: input.authLevel } });
    return sessionId;
  }

  async activeSession(sessionId: string | null): Promise<ActiveSession | Refusal> {
    if (!sessionId) return refuse(401, "session_required");
    const session = await this.deps.store.getSession(sessionId);
    if (!session) return refuse(401, "session_invalid");
    if (session.revokedAt !== null) return refuse(401, "session_revoked");
    if (session.expiresAt <= this.now()) return refuse(401, "session_expired");
    if (session.pausedAt !== null) return refuse(401, "session_paused");
    const user = await this.deps.store.getUser(session.userId);
    if (!user || user.tenantId !== session.tenantId) return refuse(401, "session_invalid");
    return { session, user };
  }

  async revokeSession(actorSessionId: string, targetSessionId: string): Promise<{ ok: true } | Refusal> {
    const a = await this.activeSession(actorSessionId);
    if ("httpStatus" in a) return a;
    const target = await this.deps.store.getSession(targetSessionId);
    if (!target || target.tenantId !== a.session.tenantId) return refuse(404, "not_found");
    if (target.userId !== a.user.userId && !a.user.roles.includes("tenant_admin")) return refuse(403, "role_required:tenant_admin");
    await this.deps.store.revokeSession(targetSessionId, this.now());
    await this.audit({ type: "auth.session_revoked", tenantId: target.tenantId, actor: a.user.userId, severity: "notice", subject: { sessionId: targetSessionId } });
    return { ok: true };
  }

  async revokeAsset(actorSessionId: string, assetId: string): Promise<{ ok: true } | Refusal> {
    const a = await this.activeSession(actorSessionId);
    if ("httpStatus" in a) return a;
    const asset = await this.deps.store.getAsset(assetId);
    if (!asset || asset.tenantId !== a.session.tenantId) return refuse(404, "not_found");
    if (asset.ownerId !== a.user.userId && !a.user.roles.includes("tenant_admin")) return refuse(403, "role_required:owner_or_tenant_admin");
    await this.deps.store.revokeAsset(assetId, this.now());
    await this.audit({ type: "asset.revoked", tenantId: asset.tenantId, actor: a.user.userId, severity: "notice", subject: { assetId } });
    return { ok: true };
  }

  // --------------------------------------------------------------- assets

  async registerAsset(input: {
    tenantId: string;
    ownerId: string;
    title: string;
    altText: string;
    classification: Classification;
    compartment: string | null;
    honey: boolean;
    bytes: Buffer;
  }): Promise<string> {
    const meta = await inspectUpload(input.bytes);
    const assetId = randomId();
    const blobKey = blobKeyFor(input.tenantId, assetId);
    const { sealed, keyId } = await sealObject(this.deps.wrapper, input.bytes, assetAad(input.tenantId, assetId));
    await this.deps.blobs.put(blobKey, sealed);
    const record: AssetRecord & { kekId: string } = {
      assetId,
      tenantId: input.tenantId,
      ownerId: input.ownerId,
      title: input.title,
      altText: input.altText,
      classification: input.classification,
      compartment: input.compartment,
      honey: input.honey,
      revoked: false,
      blobKey,
      contentType: meta.contentType,
      width: meta.width,
      height: meta.height,
      originalDhash: await dHash(input.bytes),
      kekId: keyId,
    };
    await this.deps.store.insertAsset(record);
    await this.audit({
      type: "asset.registered",
      tenantId: input.tenantId,
      actor: input.ownerId,
      severity: "info",
      subject: { assetId },
      // The honey flag is recorded for investigators; it is never shown in the catalogue.
      data: { classification: input.classification, compartment: input.compartment, honey: input.honey, width: meta.width, height: meta.height, kekId: keyId },
    });
    return assetId;
  }

  /** Upload through the API: the uploader owns the asset; only investigators may plant honey assets. */
  async uploadAsset(
    actorSessionId: string,
    input: { title: string; altText: string; classification: Classification; compartment: string | null; honey: boolean; bytes: Buffer },
  ): Promise<{ ok: true; assetId: string } | Refusal> {
    const a = await this.activeSession(actorSessionId);
    if ("httpStatus" in a) return a;
    if (input.honey && !a.user.roles.includes("investigator")) return refuse(403, "role_required:investigator");
    const assetId = await this.registerAsset({ ...input, tenantId: a.session.tenantId, ownerId: a.user.userId });
    return { ok: true, assetId };
  }

  async createGrant(grant: Omit<Grant, "grantId" | "revoked">, createdBy: string): Promise<string> {
    const grantId = randomId();
    await this.deps.store.insertGrant({ ...grant, grantId, revoked: false, createdBy });
    await this.audit({
      type: "grant.created",
      tenantId: grant.tenantId,
      actor: createdBy,
      severity: "notice",
      subject: { grantId, ...(grant.assetId ? { assetId: grant.assetId } : {}) },
      data: { subjectUserId: grant.subjectUserId, subjectRole: grant.subjectRole, compartment: grant.compartment, actions: [...grant.actions], purpose: grant.purpose, expiresAt: grant.expiresAt },
    });
    return grantId;
  }

  /**
   * The workspace lists only assets the person is entitled to. Titles of
   * everything else in the tenant stay hidden, consistent with the policy's
   * rule that a refusal never confirms an asset exists. The honey flag is
   * never included.
   */
  async listCatalogue(sessionId: string) {
    const a = await this.activeSession(sessionId);
    if ("httpStatus" in a) return a;
    const subject = this.subject(a);
    const grants = await this.deps.store.listActiveGrants(a.session.tenantId);
    const now = sec(this.now());
    const assets = (await this.deps.store.listAssetRecords(a.session.tenantId))
      .filter((asset) => entitlementFor(subject, "view", asset, grants, now) !== null)
      .map((asset) => ({ assetId: asset.assetId, title: asset.title, classification: asset.classification }));
    return { ok: true as const, user: a.user, session: a.session, assets };
  }

  // ----------------------------------------------------------------- risk

  private async assess(session: SessionRecord): Promise<RiskAssessment> {
    const now = this.now();
    const { counts, distinctAssetsLast5m } = await this.deps.store.riskCounts(session.sessionId, now);
    const net = await this.networkSignals(session);
    const clientSignalsLast15m: Partial<Record<ClientSignal, number>> = {};
    for (const k of CLIENT_SIGNALS) clientSignalsLast15m[k] = counts[k]?.last15m ?? 0;
    const assessment = assessRisk({
      ...net,
      sessionAgeSeconds: (now - session.createdAt) / 1000,
      failedAuthzLast15m: (counts.authz_denied?.last15m ?? 0) + (counts.capability_rejected?.last15m ?? 0),
      viewRequestsLastMinute: counts.view_request?.last1m ?? 0,
      distinctAssetsLast5m,
      clientSignalsLast15m,
    });
    if (assessment.state !== session.lastRiskState) {
      await this.deps.store.setSessionRisk(session.sessionId, assessment.state);
      await this.audit({
        type: "risk.state_changed",
        tenantId: session.tenantId,
        actor: "system",
        severity: assessment.state === "CRITICAL" ? "critical" : assessment.state === "HIGH" ? "warning" : "notice",
        subject: { sessionId: session.sessionId },
        data: { from: session.lastRiskState, to: assessment.state, score: assessment.score, contributions: assessment.contributions },
      });
    }
    if (assessment.state === "CRITICAL" && session.pausedAt === null) {
      // Automatic, reversible containment: pause the session and void its views.
      // Judging the person is left to a human; the case starts in needs_human_review.
      await this.deps.store.pauseSession(session.sessionId, now);
      await this.audit({ type: "auth.session_paused", tenantId: session.tenantId, actor: "system", severity: "critical", subject: { sessionId: session.sessionId }, data: { score: assessment.score } });
      await this.openIncident({ tenantId: session.tenantId, kind: "critical_risk", sessionId: session.sessionId, viewId: null, assetId: null, summary: `Session paused at risk score ${assessment.score}; review the contributing signals before any action.` });
    }
    return assessment;
  }

  async recordClientSignal(sessionId: string, viewId: string, kind: string): Promise<{ ok: true; riskState: RiskState; score: number; actions: readonly ResponseAction[] } | Refusal> {
    if (!(CLIENT_SIGNALS as readonly string[]).includes(kind)) return refuse(422, "unknown_signal");
    const a = await this.activeSession(sessionId);
    if ("httpStatus" in a) return a;
    const view = await this.deps.store.getView(viewId);
    if (!view || view.sessionId !== sessionId) return refuse(404, "not_found");
    await this.deps.store.addRiskEvent(sessionId, kind, this.now(), view.assetId);
    await this.audit({ type: "risk.signal_recorded", tenantId: a.session.tenantId, actor: a.user.userId, severity: "info", subject: { sessionId, viewId }, data: { kind, source: "client_untrusted" } });
    const assessment = await this.assess((await this.deps.store.getSession(sessionId)) as SessionRecord);
    return { ok: true, riskState: assessment.state, score: assessment.score, actions: RESPONSES[assessment.state] };
  }

  private async openIncident(i: { tenantId: string; kind: "honey_access" | "critical_risk" | "leak_report"; sessionId: string | null; viewId: string | null; assetId: string | null; summary: string }) {
    const incidentId = randomId();
    await this.deps.store.insertIncident({ incidentId, ...i });
    await this.audit({ type: "incident.opened", tenantId: i.tenantId, actor: "system", severity: i.kind === "leak_report" ? "warning" : "critical", subject: { incidentId, ...(i.viewId ? { viewId: i.viewId } : {}), ...(i.sessionId ? { sessionId: i.sessionId } : {}) }, data: { kind: i.kind, status: "needs_human_review" } });
    return incidentId;
  }

  // ---------------------------------------------------------------- views

  private subject(a: ActiveSession): Subject {
    return { userId: a.user.userId, tenantId: a.session.tenantId, roles: a.user.roles, authLevel: a.session.authLevel, authTime: sec(a.session.authTime) };
  }

  private watermarkFor(a: { tenantPseudonym: string; viewerPseudonym: string; sessionId: string; traceToken: string; classification: Classification; issuedAt: number }) {
    return watermarkLines({
      classification: a.classification,
      tenantPseudonym: a.tenantPseudonym,
      viewerPseudonym: a.viewerPseudonym,
      sessionFragment: pseudonym(this.keys.pseudonym, "S", a.sessionId),
      traceToken: a.traceToken,
      issuedAt: iso(a.issuedAt),
    });
  }

  async requestView(sessionId: string | null, assetId: string, purpose: string | null): Promise<ViewRequestResult> {
    const now = this.now();
    const a = await this.activeSession(sessionId);
    if ("httpStatus" in a) return { ...a, status: "deny" };
    const sid = a.session.sessionId;
    const tenantId = a.session.tenantId;

    const asset = await this.deps.store.getAsset(assetId);
    if (!asset || asset.tenantId !== tenantId) {
      // Same answer for "missing" and "other tenant's", so ids cannot be probed.
      await this.deps.store.addRiskEvent(sid, "authz_denied", now, null);
      await this.audit({ type: "authz.deny", tenantId, actor: a.user.userId, severity: "warning", subject: { sessionId: sid }, data: { reasons: [asset ? "tenant_isolation" : "not_found"], requestedAssetId: assetId } });
      return { ok: false, status: "deny", httpStatus: 404, reasons: ["not_found"] };
    }

    await this.deps.store.addRiskEvent(sid, "view_request", now, assetId);
    const risk = await this.assess(a.session);
    if (risk.state === "CRITICAL") return { ok: false, status: "deny", httpStatus: 401, reasons: ["session_paused"] };

    const grants = await this.deps.store.listActiveGrants(tenantId);
    const decision = authorize(this.subject(a), "view", asset, grants, { now: sec(now), riskState: risk.state, purpose });

    if (decision.effect === "deny") {
      await this.deps.store.addRiskEvent(sid, "authz_denied", now, assetId);
      await this.audit({ type: "authz.deny", tenantId, actor: a.user.userId, severity: "warning", subject: { assetId, sessionId: sid }, data: { reasons: decision.reasons, riskState: risk.state, policyVersion: decision.policyVersion } });
      return { ok: false, status: "deny", httpStatus: 403, reasons: decision.reasons };
    }
    if (decision.effect === "step_up") {
      await this.audit({ type: "auth.step_up_required", tenantId, actor: a.user.userId, severity: "notice", subject: { assetId, sessionId: sid }, data: { reasons: decision.reasons, requiredAuth: decision.requiredAuth } });
      return { ok: false, status: "step_up", httpStatus: 401, requiredAuth: decision.requiredAuth, reasons: decision.reasons };
    }

    const o = decision.obligations;
    const viewId = randomId();
    const capabilityId = randomId();
    const traceToken = issueTraceToken(this.keys.trace);
    const viewerPseudonym = pseudonym(this.keys.pseudonym, "V", tenantId, a.user.userId);
    const tenantPseudonym = (await this.deps.store.tenantPseudonym(tenantId)) ?? pseudonym(this.keys.pseudonym, "T", tenantId);
    const expiresAt = now + o.capabilityTtlSeconds * 1000;
    const mediaPath = `/api/media/${viewId}`;

    await this.deps.store.insertView({
      viewId,
      tenantId,
      assetId,
      sessionId: sid,
      userId: a.user.userId,
      viewerPseudonym,
      traceToken,
      capabilityId,
      capabilityExpiresAt: expiresAt,
      watermarkDensity: o.watermark,
      rotationSeconds: o.rotationSeconds,
      maxWidth: o.maxWidth,
      riskState: risk.state,
      policyVersion: decision.policyVersion,
      decisionReasons: decision.reasons,
      purpose: purpose?.trim() || null,
      createdAt: now,
    });

    const capability = issueCapability(this.keys.capability, {
      v: 1,
      cid: capabilityId,
      vid: viewId,
      aid: assetId,
      tid: tenantId,
      sb: sessionBinding(this.keys.capability, sid),
      path: mediaPath,
      iat: sec(now),
      exp: sec(expiresAt),
    });

    await this.audit({
      type: "view.capability_issued",
      tenantId,
      actor: a.user.userId,
      severity: "info",
      subject: { assetId, viewId, sessionId: sid },
      data: { traceToken, classification: asset.classification, reasons: decision.reasons, obligations: { ...o }, riskScore: risk.score, policyVersion: decision.policyVersion },
    });

    if (o.alert === "honey_access") {
      // The viewer sees an ordinary permit; the alert goes to investigators only.
      await this.audit({ type: "honey.accessed", tenantId, actor: a.user.userId, severity: "critical", subject: { assetId, viewId, sessionId: sid }, data: { traceToken } });
      await this.openIncident({ tenantId, kind: "honey_access", sessionId: sid, viewId, assetId, summary: "Canary asset opened. Preserve evidence and review context before contacting anyone." });
    }

    return {
      ok: true,
      status: "permit",
      viewId,
      capability,
      mediaPath,
      expiresAt: iso(expiresAt),
      title: asset.title,
      altText: asset.altText,
      classification: asset.classification,
      riskState: risk.state,
      watermark: {
        density: o.watermark,
        rotationSeconds: o.rotationSeconds,
        seed: traceToken,
        lines: this.watermarkFor({ tenantPseudonym, viewerPseudonym, sessionId: sid, traceToken, classification: asset.classification, issuedAt: now }),
      },
    };
  }

  async serveMedia(sessionId: string | null, viewId: string, capabilityToken: string | null): Promise<MediaResult> {
    const now = this.now();
    const a = await this.activeSession(sessionId);
    if ("httpStatus" in a) return a;
    const sid = a.session.sessionId;

    const reject = async (httpStatus: 401 | 403 | 404, reason: string) => {
      await this.deps.store.addRiskEvent(sid, "capability_rejected", now, null);
      await this.audit({ type: "view.capability_rejected", tenantId: a.session.tenantId, actor: a.user.userId, severity: "warning", subject: { viewId, sessionId: sid }, data: { reason } });
      return refuse(httpStatus, reason);
    };

    const check = verifyCapability(this.keys.capability, capabilityToken, { now: sec(now), path: `/api/media/${viewId}`, sessionId: sid });
    if (!check.ok) return reject(403, `capability_${check.reason}`);
    if (check.claims.vid !== viewId || check.claims.tid !== a.session.tenantId) return reject(403, "capability_wrong_view");

    const view = await this.deps.store.consumeCapability(viewId, check.claims.cid, sid, now);
    if (!view) return reject(403, "capability_replayed_revoked_or_expired");

    // Zero trust at delivery: policy is evaluated again, with the risk as it is now.
    const asset = await this.deps.store.getAsset(view.assetId);
    if (!asset) return reject(404, "not_found");
    const risk = await this.assess((await this.deps.store.getSession(sid)) as SessionRecord);
    const decision = authorize(this.subject(a), "view", asset, await this.deps.store.listActiveGrants(asset.tenantId), {
      now: sec(now),
      riskState: risk.state,
      purpose: view.purpose,
    });
    if (decision.effect !== "permit") return reject(403, `policy_changed:${decision.reasons.join(",")}`);

    // Obligations only tighten between issue and delivery.
    const density = maxDensity(view.watermarkDensity, decision.obligations.watermark);
    const maxWidth = Math.min(view.maxWidth, decision.obligations.maxWidth);
    const rotation = rotationSecondsFor(density);

    const original = await openObject(this.deps.wrapper, await this.deps.blobs.get(asset.blobKey), assetAad(asset.tenantId, asset.assetId));
    const tenantPseudonym = (await this.deps.store.tenantPseudonym(asset.tenantId)) ?? "T-UNKNOWN";
    const lines = this.watermarkFor({ tenantPseudonym, viewerPseudonym: view.viewerPseudonym, sessionId: sid, traceToken: view.traceToken, classification: asset.classification, issuedAt: view.createdAt });
    let derived;
    try {
      derived = await derivePreview(original, { maxWidth, density, lines, layout: layoutFor(view.traceToken, epochFor(now, rotation), density) });
    } finally {
      original.fill(0);
    }
    await this.deps.store.setDerivativeHash(viewId, derived.dhash);

    const receiptId = randomId();
    const payload = {
      v: 1,
      receiptId,
      viewId,
      assetId: asset.assetId,
      tenantPseudonym,
      viewerPseudonym: view.viewerPseudonym,
      traceToken: view.traceToken,
      classification: asset.classification,
      issuedAt: iso(view.createdAt),
      servedAt: iso(now),
      derivativeDhash: derived.dhash,
      width: derived.width,
      height: derived.height,
      watermark: density,
      policyVersion: decision.policyVersion,
      decisionReasons: view.decisionReasons,
    };
    const receipt: ReceiptRecord = {
      receiptId,
      viewId,
      payload,
      keyId: this.keys.signing.keyId,
      signature: signBytes(this.keys.signing.privateKey, Buffer.from(canonicalJson(payload))),
    };
    await this.deps.store.insertReceipt(receipt);
    await this.audit({
      type: "view.started",
      tenantId: asset.tenantId,
      actor: a.user.userId,
      severity: "info",
      subject: { assetId: asset.assetId, viewId, sessionId: sid, receiptId },
      data: { traceToken: view.traceToken, derivativeDhash: derived.dhash, width: derived.width, watermark: density },
    });
    return { ok: true, bytes: derived.bytes, contentType: derived.contentType, receiptId, width: derived.width, height: derived.height };
  }

  verifyReceipt(receipt: ReceiptRecord): boolean {
    return verifyBytes(this.keys.signing.publicKey, Buffer.from(canonicalJson(receipt.payload)), receipt.signature);
  }

  async viewStatus(sessionId: string | null, viewId: string): Promise<{ ok: true; active: boolean; reason: string | null } | Refusal> {
    const a = await this.activeSession(sessionId);
    if ("httpStatus" in a) return { ok: true, active: false, reason: a.reasons[0] ?? "session_invalid" };
    const view = await this.deps.store.getView(viewId);
    if (!view || view.sessionId !== a.session.sessionId) return refuse(404, "not_found");
    if (view.revokedAt !== null) return { ok: true, active: false, reason: "view_revoked" };
    const asset = await this.deps.store.getAsset(view.assetId);
    if (!asset || asset.revoked) return { ok: true, active: false, reason: "asset_revoked" };
    return { ok: true, active: true, reason: null };
  }

  // ---------------------------------------------------------- leak intake

  async leakIntake(
    investigatorSessionId: string | null,
    input: { image: Buffer | null; traceToken: string | null },
  ): Promise<
    | {
        ok: true;
        confidence: "confirmed_cryptographic_trace" | "likely_perceptual_match" | "inconclusive";
        incidentId: string;
        trace: Record<string, unknown>;
        perceptual: Record<string, unknown>;
        notes: string[];
      }
    | Refusal
  > {
    const a = await this.activeSession(investigatorSessionId);
    if ("httpStatus" in a) return a;
    if (!a.user.roles.includes("investigator")) return refuse(403, "role_required:investigator");
    const tenantId = a.session.tenantId;
    const notes: string[] = [];

    let trace: Record<string, unknown> = { status: "not_provided" };
    let tracedAssetId: string | null = null;
    if (input.traceToken) {
      const t = verifyTraceToken(this.keys.trace, input.traceToken);
      if (!t.valid) {
        trace = { status: "invalid_token", reason: t.reason };
      } else {
        const view = await this.deps.store.findViewByTrace(tenantId, t.token);
        if (!view) {
          trace = { status: "unknown_token", token: t.token };
        } else {
          const receipt = await this.deps.store.getReceiptForView(view.viewId);
          const receiptValid = receipt !== null && this.verifyReceipt(receipt);
          tracedAssetId = view.assetId;
          trace = {
            status: receiptValid ? "confirmed" : "issued_not_served",
            token: t.token,
            viewId: view.viewId,
            assetId: view.assetId,
            viewerPseudonym: view.viewerPseudonym,
            resolvedUserId: view.userId,
            issuedAt: iso(view.createdAt),
            receiptId: receipt?.receiptId ?? null,
            receiptSignatureValid: receiptValid,
          };
          // Resolving a pseudonym to a person is itself an audited act.
          await this.audit({ type: "leak.trace_resolved", tenantId, actor: a.user.userId, severity: "warning", subject: { viewId: view.viewId, assetId: view.assetId }, data: { token: t.token, receiptValid } });
        }
      }
    }

    let perceptual: Record<string, unknown> = { status: "not_provided" };
    let perceptualAssetId: string | null = null;
    if (input.image) {
      await inspectUpload(input.image);
      const h = await dHash(input.image);
      const idx = await this.deps.store.perceptualIndex(tenantId);
      const scored = [
        ...idx.assets.map((x) => ({ kind: "original", assetId: x.assetId, viewId: null as string | null, distance: hamming(h, x.dhash) })),
        ...idx.views.map((x) => ({ kind: "derivative", assetId: x.assetId, viewId: x.viewId as string | null, distance: hamming(h, x.dhash) })),
      ].sort((p, q) => p.distance - q.distance);
      const best = scored[0];
      if (best && best.distance <= PERCEPTUAL_MATCH_MAX_DISTANCE) {
        perceptualAssetId = best.assetId;
        perceptual = {
          status: "match",
          assetId: best.assetId,
          bestDistance: best.distance,
          threshold: PERCEPTUAL_MATCH_MAX_DISTANCE,
          // Derivatives of one asset look alike; these rank candidates, they do not identify a viewer.
          candidateViews: scored.filter((s) => s.viewId && s.assetId === best.assetId && s.distance <= PERCEPTUAL_MATCH_MAX_DISTANCE).slice(0, 10).map((s) => ({ viewId: s.viewId, distance: s.distance })),
        };
        notes.push("Perceptual similarity identifies the asset, not the person. Use the trace token printed in the image to attribute a view.");
      } else {
        perceptual = { status: "no_match", bestDistance: best?.distance ?? null, threshold: PERCEPTUAL_MATCH_MAX_DISTANCE };
        notes.push("No registered image is within the match threshold. Heavy crops, rotations, and re-photographed screens often fall outside it.");
      }
    }

    let confidence: "confirmed_cryptographic_trace" | "likely_perceptual_match" | "inconclusive" = "inconclusive";
    if (trace.status === "confirmed" && (perceptual.status === "not_provided" || perceptualAssetId === tracedAssetId)) {
      confidence = "confirmed_cryptographic_trace";
    } else if (trace.status === "confirmed") {
      notes.push("The trace token is genuine but the submitted image does not match the traced asset. Treat as inconclusive until reviewed.");
    } else if (perceptual.status === "match") {
      confidence = "likely_perceptual_match";
    }

    const incidentId = await this.openIncident({ tenantId, kind: "leak_report", sessionId: null, viewId: (trace.viewId as string | undefined) ?? null, assetId: tracedAssetId ?? perceptualAssetId, summary: `Leak report: ${confidence}. Requires human review before any contact or action.` });
    await this.audit({ type: "leak.intake_submitted", tenantId, actor: a.user.userId, severity: "warning", subject: { incidentId }, data: { confidence, traceStatus: trace.status, perceptualStatus: perceptual.status } });
    return { ok: true, confidence, incidentId, trace, perceptual, notes };
  }
}

export function refuse(httpStatus: Refusal["httpStatus"], ...reasons: string[]): Refusal {
  return { ok: false, httpStatus, reasons };
}
