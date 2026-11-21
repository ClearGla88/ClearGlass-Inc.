// Policy decision point (PDP). Deny by default: every path that does not reach
// an explicit allow returns a denial with a machine-readable reason.
//
// Inputs: who (principal), what (asset), which action, which grants exist, and
// the session's current risk state. Output: allow/deny plus the obligations the
// enforcement points must apply (preview width, watermark density, TTL).

import type { Action, Asset, AuthLevel, Classification, Grant, Principal, RiskState, Role } from "./types.ts";
import { AUTH_LEVELS, classificationRank } from "./types.ts";

export const POLICY_VERSION = "2026-11-21.1";

export interface ClassificationRule {
  minAuthLevel: AuthLevel;
  /** Maximum seconds since authentication; undefined means no freshness requirement. */
  maxAuthAgeSeconds?: number;
  /** Explicit, unexpired grant (asset or compartment) required for any access. */
  requiresGrant: boolean;
  /** Export is never allowed above this classification. */
  exportAllowed: boolean;
  previewMaxWidth: number;
  capabilityTtlSeconds: number;
  /** 0 = no watermark, 4 = densest. */
  watermarkDensity: number;
}

export const CLASSIFICATION_RULES: Record<Classification, ClassificationRule> = {
  PUBLIC: {
    minAuthLevel: "password",
    requiresGrant: false,
    exportAllowed: true,
    previewMaxWidth: 2048,
    capabilityTtlSeconds: 300,
    watermarkDensity: 0,
  },
  INTERNAL: {
    minAuthLevel: "password",
    requiresGrant: false,
    exportAllowed: true,
    previewMaxWidth: 1600,
    capabilityTtlSeconds: 120,
    watermarkDensity: 1,
  },
  CONFIDENTIAL: {
    minAuthLevel: "mfa",
    maxAuthAgeSeconds: 12 * 3600,
    requiresGrant: false,
    exportAllowed: true,
    previewMaxWidth: 1280,
    capabilityTtlSeconds: 60,
    watermarkDensity: 2,
  },
  RESTRICTED: {
    minAuthLevel: "phishing_resistant",
    maxAuthAgeSeconds: 4 * 3600,
    requiresGrant: true,
    exportAllowed: false,
    previewMaxWidth: 1024,
    capabilityTtlSeconds: 45,
    watermarkDensity: 3,
  },
  CROWN_JEWEL: {
    minAuthLevel: "phishing_resistant",
    maxAuthAgeSeconds: 15 * 60,
    requiresGrant: true,
    exportAllowed: false,
    previewMaxWidth: 800,
    capabilityTtlSeconds: 30,
    watermarkDensity: 4,
  },
};

/** Roles that may perform each action, before classification and grant checks. */
const ACTION_ROLES: Record<Action, Role[]> = {
  view: ["viewer", "editor", "owner", "tenant_admin"],
  export: ["editor", "owner"],
};

export interface Obligations {
  previewMaxWidth: number;
  capabilityTtlSeconds: number;
  watermarkDensity: number;
}

export type DenyReason =
  | "tenant_mismatch"
  | "risk_critical"
  | "role_insufficient"
  | "export_forbidden_for_classification"
  | "step_up_required"
  | "grant_required";

export type Decision =
  | { allow: true; reason: "allowed"; matchedGrantId?: string; obligations: Obligations; policyVersion: string }
  | { allow: false; reason: DenyReason; stepUp: boolean; policyVersion: string };

export interface AuthorizeInput {
  principal: Principal;
  asset: Asset;
  action: Action;
  grants: Grant[];
  risk: RiskState;
  /** Epoch seconds. */
  now: number;
}

function authLevelRank(level: AuthLevel): number {
  return AUTH_LEVELS.indexOf(level);
}

function deny(reason: DenyReason, stepUp = false): Decision {
  return { allow: false, reason, stepUp, policyVersion: POLICY_VERSION };
}

/** A grant counts only if it is for this tenant, user, action, and asset or compartment, and is live. */
export function findGrant(input: AuthorizeInput): Grant | undefined {
  const { principal, asset, action, grants, now } = input;
  return grants.find(
    (g) =>
      g.tenantId === asset.tenantId &&
      g.userId === principal.userId &&
      g.actions.includes(action) &&
      g.revokedAt === undefined &&
      g.expiresAt > now &&
      (g.assetId === asset.id || (g.compartment !== undefined && asset.compartments.includes(g.compartment))),
  );
}

export function authorize(input: AuthorizeInput): Decision {
  const { principal, asset, action, risk, now } = input;
  const rule = CLASSIFICATION_RULES[asset.classification];

  // 1. Tenant isolation comes first and is never overridden.
  if (principal.tenantId !== asset.tenantId) return deny("tenant_mismatch");

  // 2. A CRITICAL session gets nothing until a human clears it.
  if (risk === "CRITICAL") return deny("risk_critical");

  // 3. Role gate (RBAC). Owners may always view their own asset.
  const isOwner = asset.ownerId === principal.userId;
  const roleOk = principal.roles.some((r) => ACTION_ROLES[action].includes(r)) || (isOwner && action === "view");
  if (!roleOk) return deny("role_insufficient");

  // 4. Export is a classification property, not a role property.
  if (action === "export" && !rule.exportAllowed) return deny("export_forbidden_for_classification");

  // 5. Authentication strength and freshness (step-up). HIGH risk demands fresh
  //    phishing-resistant authentication for RESTRICTED and above.
  const highRiskSensitive = risk === "HIGH" && classificationRank(asset.classification) >= classificationRank("RESTRICTED");
  const requiredLevel: AuthLevel = highRiskSensitive ? "phishing_resistant" : rule.minAuthLevel;
  const maxAge = highRiskSensitive ? Math.min(rule.maxAuthAgeSeconds ?? 900, 900) : rule.maxAuthAgeSeconds;
  if (authLevelRank(principal.authLevel) < authLevelRank(requiredLevel)) return deny("step_up_required", true);
  if (maxAge !== undefined && now - principal.authTime > maxAge) return deny("step_up_required", true);

  // 6. Attribute gate (ABAC): explicit grants for sensitive classes and for any
  //    compartmented asset. Being a tenant admin is not a substitute (separation
  //    of duties); only the owner is exempt for viewing.
  const grant = findGrant(input);
  const needsGrant = rule.requiresGrant || asset.compartments.length > 0;
  if (needsGrant && !grant && !(isOwner && action === "view")) return deny("grant_required");

  // 7. Obligations, tightened by risk.
  let density = rule.watermarkDensity;
  let width = rule.previewMaxWidth;
  let ttl = rule.capabilityTtlSeconds;
  if (risk === "GUARDED") density = Math.min(4, density + 1);
  if (risk === "HIGH") {
    density = 4;
    width = Math.min(width, 640);
    ttl = Math.min(ttl, 20);
  }

  return {
    allow: true,
    reason: "allowed",
    matchedGrantId: grant?.id,
    obligations: { previewMaxWidth: width, capabilityTtlSeconds: ttl, watermarkDensity: density },
    policyVersion: POLICY_VERSION,
  };
}
