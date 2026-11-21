// Shared domain types. Erasable TypeScript only (no enums, no parameter
// properties) so Node can run these modules directly with type stripping.

export const CLASSIFICATIONS = [
  "PUBLIC",
  "INTERNAL",
  "CONFIDENTIAL",
  "RESTRICTED",
  "CROWN_JEWEL",
] as const;
export type Classification = (typeof CLASSIFICATIONS)[number];

/** Human label. The identifier uses an underscore; the label keeps the hyphen. */
export function classificationLabel(c: Classification): string {
  return c === "CROWN_JEWEL" ? "CROWN-JEWEL" : c;
}

export function classificationRank(c: Classification): number {
  return CLASSIFICATIONS.indexOf(c);
}

export type Action = "view" | "export";

/** Strength of the session's authentication, lowest to highest. */
export const AUTH_LEVELS = ["password", "mfa", "phishing_resistant"] as const;
export type AuthLevel = (typeof AUTH_LEVELS)[number];

export const ROLES = ["viewer", "editor", "owner", "tenant_admin", "investigator"] as const;
export type Role = (typeof ROLES)[number];

export const RISK_STATES = ["LOW", "GUARDED", "HIGH", "CRITICAL"] as const;
export type RiskState = (typeof RISK_STATES)[number];

export interface Principal {
  userId: string;
  tenantId: string;
  displayName: string;
  roles: Role[];
  authLevel: AuthLevel;
  /** Epoch seconds of the most recent authentication (used for step-up freshness). */
  authTime: number;
  sessionId: string;
}

export interface Asset {
  id: string;
  tenantId: string;
  title: string;
  /** Text alternative written by the owner. Delivered only after authorization. */
  altText: string;
  classification: Classification;
  ownerId: string;
  compartments: string[];
  /** Decoy asset: real-looking, contains no real data; any access opens a case. */
  isHoney: boolean;
  storageKey: string;
  mime: string;
}

export interface Grant {
  id: string;
  tenantId: string;
  userId: string;
  /** Exactly one of assetId or compartment is set. */
  assetId?: string;
  compartment?: string;
  actions: Action[];
  purpose: string;
  /** Epoch seconds. */
  expiresAt: number;
  revokedAt?: number;
}
