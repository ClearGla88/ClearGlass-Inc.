// Policy decision point. Pure and deterministic: same inputs, same decision.
// It is called when a view is requested AND again when the media is served,
// so a grant revoked between those two moments still stops delivery.

import {
  CLASSIFICATION_POLICY,
  DENSITY_FLOOR_BY_RISK,
  MAX_WIDTH_BY_RISK,
  authRank,
  maxDensity,
  riskRank,
  type AuthLevel,
  type Classification,
  type RiskState,
  type WatermarkDensity,
} from "./classification";
import { rotationSecondsFor } from "./watermark";

export const POLICY_VERSION = "aegis-pdp/2026-11-06.1";

export const ROLES = ["member", "tenant_admin", "investigator"] as const;
export type Role = (typeof ROLES)[number];

export const ACTIONS = ["view", "export", "download_original", "manage"] as const;
export type Action = (typeof ACTIONS)[number];

export interface Subject {
  userId: string;
  tenantId: string;
  roles: readonly Role[];
  authLevel: AuthLevel;
  /** Epoch seconds of the last authentication ceremony. */
  authTime: number;
}

export interface Resource {
  assetId: string;
  tenantId: string;
  classification: Classification;
  ownerId: string;
  compartment: string | null;
  honey: boolean;
  revoked: boolean;
}

export interface Grant {
  grantId: string;
  tenantId: string;
  subjectUserId: string | null;
  subjectRole: Role | null;
  assetId: string | null;
  compartment: string | null;
  actions: readonly Action[];
  purpose: string | null;
  notBefore: number;
  expiresAt: number;
  revoked: boolean;
}

export interface DecisionContext {
  /** Epoch seconds. */
  now: number;
  riskState: RiskState;
  purpose?: string | null;
}

export interface Obligations {
  watermark: WatermarkDensity;
  rotationSeconds: number;
  maxWidth: number;
  capabilityTtlSeconds: number;
  alert: "honey_access" | null;
}

export type Decision =
  | { effect: "permit"; reasons: string[]; obligations: Obligations; grantId: string | null; policyVersion: string }
  | { effect: "deny"; reasons: string[]; policyVersion: string }
  | { effect: "step_up"; reasons: string[]; requiredAuth: AuthLevel; policyVersion: string };

const deny = (...reasons: string[]): Decision => ({ effect: "deny", reasons, policyVersion: POLICY_VERSION });

function matchingGrant(subject: Subject, action: Action, resource: Resource, grants: readonly Grant[], now: number) {
  return grants.find(
    (g) =>
      !g.revoked &&
      g.tenantId === resource.tenantId &&
      g.notBefore <= now &&
      now < g.expiresAt &&
      g.actions.includes(action) &&
      (g.subjectUserId === subject.userId || (g.subjectRole !== null && subject.roles.includes(g.subjectRole))) &&
      (g.assetId === resource.assetId || (g.compartment !== null && g.compartment === resource.compartment)),
  );
}

export type Entitlement = { kind: "owner" | "investigator_honey" | "member_default"; grant: null } | { kind: "grant"; grant: Grant };

/**
 * Who may see this resource at all, before purpose, authentication strength,
 * or risk are considered. Shared by authorize() and the workspace catalogue,
 * so the catalogue never lists a title the person has no route to.
 */
export function entitlementFor(subject: Subject, action: Action, resource: Resource, grants: readonly Grant[], now: number): Entitlement | null {
  if (subject.tenantId !== resource.tenantId || resource.revoked) return null;
  const policy = CLASSIFICATION_POLICY[resource.classification];
  if (action === "view" && resource.ownerId === subject.userId) return { kind: "owner", grant: null };
  if (action === "view" && resource.honey && subject.roles.includes("investigator")) return { kind: "investigator_honey", grant: null };
  if (action === "view" && policy.memberDefaultView && (subject.roles.includes("member") || subject.roles.includes("tenant_admin"))) {
    return { kind: "member_default", grant: null };
  }
  const grant = matchingGrant(subject, action, resource, grants, now);
  return grant ? { kind: "grant", grant } : null;
}

export function authorize(
  subject: Subject,
  action: Action,
  resource: Resource,
  grants: readonly Grant[],
  ctx: DecisionContext,
): Decision {
  // 1. Tenant isolation comes before anything that could reveal the resource.
  if (subject.tenantId !== resource.tenantId) return deny("tenant_isolation");
  if (resource.revoked) return deny("asset_revoked");
  if (ctx.riskState === "CRITICAL") return deny("risk_critical");

  // 2. Masters never leave storage through this layer; every view is a derivative.
  if (action === "download_original") return deny("originals_never_served");

  if (action === "manage") {
    return subject.roles.includes("tenant_admin")
      ? { effect: "permit", reasons: ["role:tenant_admin"], obligations: noObligations(), grantId: null, policyVersion: POLICY_VERSION }
      : deny("role_required:tenant_admin");
  }

  const policy = CLASSIFICATION_POLICY[resource.classification];
  if (riskRank(ctx.riskState) > riskRank(policy.maxRisk)) return deny("risk_exceeds_classification_ceiling");
  if (action === "export" && !policy.exportAllowed) return deny("export_disabled_for_classification");

  // 3. Entitlement. Checked before authentication strength, so a person with no
  //    access is never prompted to step up (that prompt would confirm the asset exists).
  const reasons: string[] = [];
  let grantId: string | null = null;
  const isInvestigator = subject.roles.includes("investigator");

  const entitlement = entitlementFor(subject, action, resource, grants, ctx.now);
  if (!entitlement) return deny("no_entitlement");
  if (entitlement.kind !== "grant") {
    reasons.push({ owner: "owner", investigator_honey: "investigator:honey_asset", member_default: "tenant_member_default" }[entitlement.kind]);
  } else {
    const grant = entitlement.grant;
    if (policy.requirePurpose) {
      if (!grant.purpose) return deny("grant_missing_purpose");
      if ((ctx.purpose ?? "").trim() !== grant.purpose) return deny("purpose_mismatch");
      reasons.push("purpose_bound");
    }
    grantId = grant.grantId;
    reasons.push(`grant:${grant.grantId}`);
  }

  // 4. Authentication strength and freshness.
  const authAge = ctx.now - subject.authTime;
  if (authRank(subject.authLevel) < authRank(policy.minAuth)) {
    return { effect: "step_up", reasons: ["insufficient_auth_strength"], requiredAuth: policy.minAuth, policyVersion: POLICY_VERSION };
  }
  if (authAge > policy.maxAuthAgeSeconds) {
    return { effect: "step_up", reasons: ["auth_too_old"], requiredAuth: policy.minAuth, policyVersion: POLICY_VERSION };
  }
  if (ctx.riskState !== "LOW" && policy.freshAuthAtElevatedRiskSeconds !== null && authAge > policy.freshAuthAtElevatedRiskSeconds) {
    return { effect: "step_up", reasons: ["elevated_risk_requires_fresh_auth"], requiredAuth: policy.minAuth, policyVersion: POLICY_VERSION };
  }

  // 5. Obligations scale with both the label and the session's risk.
  const watermark = maxDensity(policy.watermark, DENSITY_FLOOR_BY_RISK[ctx.riskState]);
  const riskKey = ctx.riskState as Exclude<RiskState, "CRITICAL">;
  const ttl = ctx.riskState === "HIGH" ? Math.max(30, Math.floor(policy.capabilityTtlSeconds / 2)) : policy.capabilityTtlSeconds;
  const alert = resource.honey && !isInvestigator ? "honey_access" : null;
  reasons.push(`risk:${ctx.riskState}`, `class:${resource.classification}`);

  return {
    effect: "permit",
    reasons,
    grantId,
    policyVersion: POLICY_VERSION,
    obligations: {
      watermark,
      rotationSeconds: rotationSecondsFor(watermark),
      maxWidth: MAX_WIDTH_BY_RISK[riskKey],
      capabilityTtlSeconds: ttl,
      alert,
    },
  };
}

function noObligations(): Obligations {
  return { watermark: "none", rotationSeconds: 0, maxWidth: 0, capabilityTtlSeconds: 0, alert: null };
}
