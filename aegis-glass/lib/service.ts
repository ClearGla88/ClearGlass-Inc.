// The enforcement core. Route handlers stay thin: they turn HTTP into calls on
// this service and its results back into HTTP. Every decision, allow or deny,
// lands in the audit chain.

import { randomInt, randomUUID, type KeyObject } from "node:crypto";
import { AuditLog, verifyChain, type AuditEvent } from "./audit.ts";
import { newTokenId, signCapability, verifyCapability, type CapabilitySigner } from "./capability.ts";
import { openObject, sealObject, type Kms } from "./envelope.ts";
import { authorize, type Decision } from "./policy.ts";
import { renderPreview } from "./preview.ts";
import { newReceiptId, signReceipt, verifyReceipt, type ViewReceipt } from "./receipts.ts";
import type { IncidentCase, ObjectStore, Repository } from "./repository.ts";
import { assessRisk, type RiskAssessment } from "./risk.ts";
import { rateLimit, type KeyValueStore } from "./store.ts";
import type { Asset, Principal, RiskState } from "./types.ts";
import { classificationLabel, RISK_STATES } from "./types.ts";
import { newTraceToken, pseudonym, watermarkLines } from "./watermark.ts";
import { epochAt, layoutFor, ROTATE_SECONDS } from "./watermark-layout.ts";

export interface AegisKeys {
  capability: CapabilitySigner;
  auditMac: Buffer;
  pseudonym: Buffer;
  receiptPrivate: KeyObject;
  receiptPublic: KeyObject;
  receiptKeyId: string;
}

export interface AegisDeps {
  repo: Repository;
  objects: ObjectStore;
  kv: KeyValueStore;
  kms: Kms;
  audit: AuditLog;
  keys: AegisKeys;
  /** Milliseconds since epoch. */
  now: () => number;
}

export interface RequestContext {
  /** Random per-browser ID from an HttpOnly cookie. Not a fingerprint. */
  deviceId?: string;
  networkReputation?: "good" | "unknown" | "bad";
  impossibleTravel?: boolean;
  outsideConfiguredHours?: boolean;
}

export interface CapabilityGrantBody {
  url: string;
  expiresAt: string;
  title: string;
  altText: string;
  classification: string;
  riskState: RiskState;
  previewMaxWidth: number;
  watermark: { lines: string[]; seed: number; density: number; rotateSeconds: number };
}

export type CapabilityResult =
  | { status: 200; body: CapabilityGrantBody }
  | { status: 401 | 403 | 404 | 429; body: { error: string } };

export type MediaResult =
  | { status: 200; bytes: Buffer; mime: string; traceToken: string }
  | { status: 401 | 403 | 404 | 410 | 429; error: string };

const LIMITS = {
  capabilityPerMinute: 30,
  mediaPerMinute: 60,
};

const HUMAN_ERRORS: Record<string, string> = {
  step_up_required: "step_up_required",
  grant_required: "forbidden",
  role_insufficient: "forbidden",
  export_forbidden_for_classification: "forbidden",
  risk_critical: "session_paused",
  tenant_mismatch: "not_found",
};

export class AegisService {
  readonly deps: AegisDeps;

  constructor(deps: AegisDeps) {
    this.deps = deps;
  }

  private nowSeconds(): number {
    return Math.floor(this.deps.now() / 1000);
  }

  private log(event: AuditEvent): Promise<unknown> {
    return this.deps.audit.append(event);
  }

  private viewerIdentity(p: Principal) {
    const { pseudonym: key } = this.deps.keys;
    return {
      tenantPseudonym: pseudonym(key, "O", p.tenantId),
      viewerPseudonym: pseudonym(key, "V", `${p.tenantId}:${p.userId}`),
      sessionFragment: pseudonym(key, "S", p.sessionId).slice(0, 6),
    };
  }

  // ---------------------------------------------------------------- sessions

  /** Records which tenant a session belongs to, so revocation stays tenant-scoped. */
  async registerSession(p: Principal, ttlSeconds: number): Promise<void> {
    await this.deps.kv.set(`sess:${p.sessionId}`, p.tenantId, ttlSeconds);
  }

  async isSessionRevoked(sessionId: string): Promise<boolean> {
    return (await this.deps.kv.get(`revoked:${sessionId}`)) !== undefined;
  }

  async revokeSession(actor: Principal, sessionId: string, reason: string): Promise<{ ok: boolean; error?: string }> {
    const tenant = await this.deps.kv.get(`sess:${sessionId}`);
    const self = actor.sessionId === sessionId;
    if (!self && (!actor.roles.includes("tenant_admin") || tenant !== actor.tenantId)) {
      return { ok: false, error: "forbidden" };
    }
    await this.deps.kv.set(`revoked:${sessionId}`, reason.slice(0, 120), 7 * 24 * 3600);
    await this.log({ type: "session.revoked", tenantId: actor.tenantId, actor: actor.userId, subject: sessionId, data: { reason: reason.slice(0, 120), self } });
    return { ok: true };
  }

  async revokeGrant(actor: Principal, grantId: string): Promise<{ ok: boolean; error?: string }> {
    if (!actor.roles.some((r) => r === "owner" || r === "tenant_admin")) return { ok: false, error: "forbidden" };
    const ok = await this.deps.repo.revokeGrant(actor.tenantId, grantId, this.nowSeconds());
    if (ok) await this.log({ type: "grant.revoked", tenantId: actor.tenantId, actor: actor.userId, subject: grantId, data: {} });
    return ok ? { ok } : { ok, error: "not_found" };
  }

  // -------------------------------------------------------------------- risk

  private async counters(p: Principal, assetId: string, ctx: RequestContext) {
    const { kv } = this.deps;
    const sid = p.sessionId;
    const viewRequests5m = await kv.increment(`cnt:views:${sid}`, 300);
    if (await kv.setIfAbsent(`seen:${sid}:${assetId}`, "1", 300)) await kv.increment(`cnt:distinct:${sid}`, 300);
    const distinctAssets5m = Number((await kv.get(`cnt:distinct:${sid}`)) ?? 0);
    const deniedAttempts10m = Number((await kv.get(`cnt:denied:${sid}`)) ?? 0);
    const honeyTouches = Number((await kv.get(`cnt:honey:${sid}`)) ?? 0);

    let newDevice = false;
    if (ctx.deviceId) {
      newDevice = await kv.setIfAbsent(`dev:${p.tenantId}:${p.userId}:${ctx.deviceId}`, "1", 180 * 24 * 3600);
    }
    return { viewRequests5m, distinctAssets5m, deniedAttempts10m, honeyTouches, newDevice };
  }

  private async currentRisk(p: Principal, assetId: string, ctx: RequestContext): Promise<RiskAssessment & { sticky: boolean }> {
    const { kv } = this.deps;
    const c = await this.counters(p, assetId, ctx);
    const assessment = assessRisk({
      newDevice: c.newDevice,
      impossibleTravel: ctx.impossibleTravel ?? false,
      networkReputation: ctx.networkReputation ?? "good",
      deniedAttempts10m: c.deniedAttempts10m,
      viewRequests5m: c.viewRequests5m,
      distinctAssets5m: c.distinctAssets5m,
      honeyTouches: c.honeyTouches,
      outsideConfiguredHours: ctx.outsideConfiguredHours ?? false,
    });

    // CRITICAL sticks to the session until a person reviews it or the user signs in again.
    const sticky = (await kv.get(`risk:critical:${p.sessionId}`)) !== undefined;
    const state: RiskState = sticky ? "CRITICAL" : assessment.state;

    const previous = (await kv.get(`risk:${p.sessionId}`)) as RiskState | undefined;
    if (previous !== state) {
      await kv.set(`risk:${p.sessionId}`, state, 24 * 3600);
      await this.log({
        type: "risk.state_changed",
        tenantId: p.tenantId,
        actor: p.userId,
        subject: p.sessionId,
        data: {
          from: previous ?? "LOW",
          to: state,
          score: assessment.score,
          reasons: assessment.contributions.map((x) => `${x.signal}+${x.points}`).join(","),
        },
      });
    }
    if (state === "CRITICAL" && !sticky) {
      await kv.set(`risk:critical:${p.sessionId}`, "1", 24 * 3600);
      await this.openCaseOnce(p, "risk_critical", undefined, `Session reached CRITICAL risk (score ${assessment.score}): ${assessment.contributions.map((x) => x.reason).join("; ")}.`);
    }
    return { ...assessment, state, sticky };
  }

  private async storedRisk(sessionId: string): Promise<RiskState> {
    if ((await this.deps.kv.get(`risk:critical:${sessionId}`)) !== undefined) return "CRITICAL";
    const s = await this.deps.kv.get(`risk:${sessionId}`);
    return s && (RISK_STATES as readonly string[]).includes(s) ? (s as RiskState) : "LOW";
  }

  private async noteDenied(p: Principal): Promise<void> {
    await this.deps.kv.increment(`cnt:denied:${p.sessionId}`, 600);
  }

  private async openCaseOnce(p: Principal, kind: IncidentCase["kind"], assetId: string | undefined, summary: string): Promise<void> {
    const dedupe = `case:${kind}:${p.sessionId}:${assetId ?? "-"}`;
    if (!(await this.deps.kv.setIfAbsent(dedupe, "1", 30 * 24 * 3600))) return;
    const c: IncidentCase = {
      id: randomUUID(),
      tenantId: p.tenantId,
      kind,
      status: "needs_review",
      subjectUserId: p.userId,
      subjectSessionId: p.sessionId,
      assetId,
      openedAt: new Date(this.deps.now()).toISOString(),
      summary,
    };
    await this.deps.repo.openCase(c);
    await this.log({ type: "case.opened", tenantId: p.tenantId, actor: "system", subject: c.id, data: { kind, assetId: assetId ?? null, sessionId: p.sessionId } });
  }

  // ------------------------------------------------------------ capability

  async requestCapability(p: Principal, assetId: string, ctx: RequestContext = {}): Promise<CapabilityResult> {
    const { kv, repo } = this.deps;
    const now = this.nowSeconds();

    if (await this.isSessionRevoked(p.sessionId)) return { status: 401, body: { error: "session_revoked" } };

    const rl = await rateLimit(kv, `cap:${p.sessionId}`, LIMITS.capabilityPerMinute, 60, now);
    if (!rl.allowed) {
      await this.noteDenied(p);
      await this.log({ type: "rate.limited", tenantId: p.tenantId, actor: p.userId, subject: p.sessionId, data: { bucket: "capability", count: rl.count } });
      return { status: 429, body: { error: "rate_limited" } };
    }

    // Tenant-scoped lookup: an asset in another tenant is indistinguishable from a missing one.
    const asset = await repo.getAsset(p.tenantId, assetId);
    if (!asset) {
      await this.noteDenied(p);
      await this.log({ type: "capability.denied", tenantId: p.tenantId, actor: p.userId, subject: assetId.slice(0, 64), data: { reason: "not_found" } });
      return { status: 404, body: { error: "not_found" } };
    }

    if (asset.isHoney) {
      await kv.increment(`cnt:honey:${p.sessionId}`, 30 * 24 * 3600);
      await this.log({ type: "honey.accessed", tenantId: p.tenantId, actor: p.userId, subject: asset.id, data: { sessionId: p.sessionId } });
      await this.openCaseOnce(p, "honey_access", asset.id, `Decoy asset "${asset.title}" was requested. Review context before drawing any conclusion: access may be legitimate exploration.`);
    }

    const risk = await this.currentRisk(p, asset.id, ctx);
    const grants = await repo.grantsFor(p.tenantId, p.userId);
    const decision = authorize({ principal: p, asset, action: "view", grants, risk: risk.state, now });

    if (!decision.allow) {
      await this.noteDenied(p);
      await this.log({
        type: "capability.denied",
        tenantId: p.tenantId,
        actor: p.userId,
        subject: asset.id,
        data: { reason: decision.reason, risk: risk.state, policyVersion: decision.policyVersion },
      });
      const error = HUMAN_ERRORS[decision.reason] ?? "forbidden";
      const status = decision.stepUp || decision.reason === "risk_critical" ? 401 : decision.reason === "tenant_mismatch" ? 404 : 403;
      return { status, body: { error } };
    }

    const { previewMaxWidth, capabilityTtlSeconds, watermarkDensity } = decision.obligations;
    const traceToken = newTraceToken();
    const seed = randomInt(0, 2 ** 31);
    const jti = newTokenId();
    const exp = now + capabilityTtlSeconds;
    const token = signCapability(this.deps.keys.capability, {
      jti, aid: asset.id, tid: asset.tenantId, uid: p.userId, sid: p.sessionId, act: "view",
      nbf: now, exp, w: previewMaxWidth, d: watermarkDensity, tr: traceToken, seed,
    });

    const identity = this.viewerIdentity(p);
    const lines = watermarkLines({ classification: asset.classification, traceToken, ...identity }, new Date(this.deps.now()));

    await this.log({
      type: "capability.issued",
      tenantId: p.tenantId,
      actor: p.userId,
      subject: asset.id,
      data: {
        capabilityId: jti, traceToken, ttl: capabilityTtlSeconds, width: previewMaxWidth, density: watermarkDensity,
        risk: risk.state, grantId: decision.matchedGrantId ?? null, policyVersion: decision.policyVersion,
      },
    });

    return {
      status: 200,
      body: {
        url: `/api/media/${token}`,
        expiresAt: new Date(exp * 1000).toISOString(),
        title: asset.title,
        altText: asset.altText,
        classification: classificationLabel(asset.classification),
        riskState: risk.state,
        previewMaxWidth,
        watermark: { lines, seed, density: watermarkDensity, rotateSeconds: ROTATE_SECONDS },
      },
    };
  }

  // ------------------------------------------------------------------ media

  async serveMedia(p: Principal | undefined, token: string): Promise<MediaResult> {
    const { kv, repo, objects, kms, keys } = this.deps;
    const nowMs = this.deps.now();
    const now = Math.floor(nowMs / 1000);

    const verified = verifyCapability(keys.capability.keys, token, now);
    if (!verified.ok) {
      await this.log({ type: "media.denied", tenantId: p?.tenantId ?? "unknown", actor: p?.userId ?? "anonymous", data: { reason: verified.reason } });
      return verified.reason === "expired" ? { status: 410, error: "expired" } : { status: 401, error: "invalid_capability" };
    }
    const cap = verified.payload;

    // The URL alone is worthless: it only works inside the session it was issued to.
    if (!p || p.sessionId !== cap.sid || p.userId !== cap.uid || p.tenantId !== cap.tid) {
      if (p) await this.noteDenied(p);
      await this.log({
        type: "media.denied",
        tenantId: cap.tid,
        actor: p?.userId ?? "anonymous",
        subject: cap.aid,
        data: { reason: p ? "session_mismatch" : "no_session", capabilityId: cap.jti, traceToken: cap.tr },
      });
      return { status: p ? 403 : 401, error: p ? "forbidden" : "unauthenticated" };
    }

    if (await this.isSessionRevoked(p.sessionId)) {
      await this.log({ type: "media.denied", tenantId: p.tenantId, actor: p.userId, subject: cap.aid, data: { reason: "session_revoked", capabilityId: cap.jti } });
      return { status: 403, error: "session_revoked" };
    }

    const rl = await rateLimit(kv, `media:${p.sessionId}`, LIMITS.mediaPerMinute, 60, now);
    if (!rl.allowed) {
      await this.log({ type: "rate.limited", tenantId: p.tenantId, actor: p.userId, subject: p.sessionId, data: { bucket: "media", count: rl.count } });
      return { status: 429, error: "rate_limited" };
    }

    // Single use: a replayed URL fails even inside the right session.
    if (!(await kv.setIfAbsent(`jti:${cap.jti}`, "1", Math.max(60, cap.exp - now + 60)))) {
      await this.log({ type: "media.denied", tenantId: p.tenantId, actor: p.userId, subject: cap.aid, data: { reason: "replay", capabilityId: cap.jti } });
      return { status: 410, error: "already_used" };
    }

    // Re-check policy at delivery time, so a grant revoked after issuance takes effect now.
    const asset = await repo.getAsset(cap.tid, cap.aid);
    if (!asset) return { status: 404, error: "not_found" };
    const grants = await repo.grantsFor(p.tenantId, p.userId);
    const decision: Decision = authorize({ principal: p, asset, action: "view", grants, risk: await this.storedRisk(p.sessionId), now });
    if (!decision.allow) {
      await this.noteDenied(p);
      await this.log({ type: "media.denied", tenantId: p.tenantId, actor: p.userId, subject: asset.id, data: { reason: decision.reason, capabilityId: cap.jti } });
      return { status: 403, error: HUMAN_ERRORS[decision.reason] ?? "forbidden" };
    }
    // Apply whichever is stricter: the obligations at issuance or now.
    const width = Math.min(cap.w, decision.obligations.previewMaxWidth);
    const density = Math.max(cap.d, decision.obligations.watermarkDensity);

    const sealed = await objects.get(asset.storageKey);
    if (!sealed) return { status: 404, error: "not_found" };
    const original = await openObject(kms, asset.tenantId, asset.id, sealed);

    const identity = this.viewerIdentity(p);
    const epoch = epochAt(nowMs);
    let rendered;
    try {
      rendered = await renderPreview(original, {
        maxWidth: width,
        density,
        layout: layoutFor(cap.seed, epoch, density),
        lines: watermarkLines({ classification: asset.classification, traceToken: cap.tr, ...identity }, new Date(nowMs)),
      });
    } finally {
      original.fill(0);
    }

    const receipt = signReceipt(
      {
        receiptId: newReceiptId(),
        traceToken: cap.tr,
        tenantId: asset.tenantId,
        assetId: asset.id,
        classification: asset.classification,
        userId: p.userId,
        viewerPseudonym: identity.viewerPseudonym,
        sessionFragment: identity.sessionFragment,
        capabilityId: cap.jti,
        policyVersion: decision.policyVersion,
        issuedAt: new Date(cap.nbf * 1000).toISOString(),
        servedAt: new Date(nowMs).toISOString(),
        previewWidth: rendered.width,
        previewHeight: rendered.height,
        watermarkDensity: density,
        watermarkEpoch: epoch,
        servedSha256: rendered.sha256,
        servedDhash: rendered.dhash,
      },
      keys.receiptPrivate,
      keys.receiptKeyId,
    );
    await repo.putReceipt(receipt);
    await this.log({
      type: "media.served",
      tenantId: p.tenantId,
      actor: p.userId,
      subject: asset.id,
      data: { capabilityId: cap.jti, traceToken: cap.tr, receiptId: receipt.body.receiptId, sha256: rendered.sha256, dhash: rendered.dhash, width: rendered.width, density },
    });

    return { status: 200, bytes: rendered.bytes, mime: rendered.mime, traceToken: cap.tr };
  }

  // --------------------------------------------------------- investigations

  private canInvestigate(actor: Principal): boolean {
    return actor.roles.includes("investigator") && actor.authLevel === "phishing_resistant";
  }

  async resolveTrace(actor: Principal, traceToken: string): Promise<{ status: 200; receipt: ViewReceipt; signatureValid: boolean } | { status: 403 | 404; error: string }> {
    if (!this.canInvestigate(actor)) return { status: 403, error: "forbidden" };
    const receipt = await this.deps.repo.receiptByTrace(actor.tenantId, traceToken);
    await this.log({ type: "trace.resolved", tenantId: actor.tenantId, actor: actor.userId, subject: traceToken.slice(0, 32), data: { found: Boolean(receipt) } });
    if (!receipt) return { status: 404, error: "not_found" };
    return { status: 200, receipt, signatureValid: verifyReceipt(receipt, this.deps.keys.receiptPublic) };
  }

  async listCases(actor: Principal): Promise<{ status: 200; cases: IncidentCase[] } | { status: 403; error: string }> {
    if (!this.canInvestigate(actor) && !actor.roles.includes("tenant_admin")) return { status: 403, error: "forbidden" };
    return { status: 200, cases: await this.deps.repo.listCases(actor.tenantId) };
  }

  async verifyAudit(actor: Principal) {
    if (!this.canInvestigate(actor) && !actor.roles.includes("tenant_admin")) return { status: 403 as const, error: "forbidden" };
    const result = verifyChain(await this.deps.audit.all(), this.deps.keys.auditMac);
    await this.log({ type: "audit.verified", tenantId: actor.tenantId, actor: actor.userId, data: { ok: result.ok, checked: result.checked } });
    return { status: 200 as const, result };
  }

  /**
   * Titles are content too. List only assets this person could open now, or
   * could open after a step-up sign-in; everything else stays invisible.
   */
  async listVisibleAssets(p: Principal): Promise<Array<{ id: string; title: string; classification: string; needsStepUp: boolean }>> {
    const assets = await this.deps.repo.listAssets(p.tenantId);
    const grants = await this.deps.repo.grantsFor(p.tenantId, p.userId);
    const now = this.nowSeconds();
    const out = [];
    for (const asset of assets) {
      const d = authorize({ principal: p, asset, action: "view", grants, risk: "LOW", now });
      if (d.allow || d.reason === "step_up_required") {
        out.push({ id: asset.id, title: asset.title, classification: classificationLabel(asset.classification), needsStepUp: !d.allow });
      }
    }
    return out.sort((a, b) => a.title.localeCompare(b.title));
  }

  // ----------------------------------------------------------------- ingest

  /** Encrypts an original and registers it. Upload validation happens before this call. */
  async ingest(asset: Asset, original: Buffer): Promise<void> {
    const sealed = await sealObject(this.deps.kms, asset.tenantId, asset.id, original);
    await this.deps.objects.put(asset.storageKey, sealed);
    await this.deps.repo.putAsset(asset);
  }
}
