// Classification labels, risk states, and the per-label policy table.
// Isomorphic: no Node imports, so client components can read labels and ranks.

export const CLASSIFICATIONS = ["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED", "CROWN_JEWEL"] as const;
export type Classification = (typeof CLASSIFICATIONS)[number];

export const RISK_STATES = ["LOW", "GUARDED", "HIGH", "CRITICAL"] as const;
export type RiskState = (typeof RISK_STATES)[number];

// Authentication strength carried by a session. "phishing_resistant" means a
// passkey / WebAuthn ceremony; "mfa" means a second factor; "pwd" means neither.
export const AUTH_LEVELS = ["pwd", "mfa", "phishing_resistant"] as const;
export type AuthLevel = (typeof AUTH_LEVELS)[number];

export const WATERMARK_DENSITIES = ["none", "light", "standard", "dense"] as const;
export type WatermarkDensity = (typeof WATERMARK_DENSITIES)[number];

export const classificationRank = (c: Classification): number => CLASSIFICATIONS.indexOf(c);
export const riskRank = (r: RiskState): number => RISK_STATES.indexOf(r);
export const authRank = (a: AuthLevel): number => AUTH_LEVELS.indexOf(a);
export const densityRank = (d: WatermarkDensity): number => WATERMARK_DENSITIES.indexOf(d);

export const isClassification = (v: unknown): v is Classification =>
  typeof v === "string" && (CLASSIFICATIONS as readonly string[]).includes(v);

export interface ClassificationPolicy {
  /** Minimum session authentication strength. Weaker sessions get a step-up challenge. */
  minAuth: AuthLevel;
  /** Step up when the last authentication is older than this. */
  maxAuthAgeSeconds: number;
  /** Highest session risk state at which this label can be viewed at all. */
  maxRisk: RiskState;
  /** At GUARDED or HIGH risk, require an authentication no older than this (null: not required). */
  freshAuthAtElevatedRiskSeconds: number | null;
  /** Lifetime of a single-use media capability. */
  capabilityTtlSeconds: number;
  /** Baseline visible watermark. Risk can raise it, never lower it. */
  watermark: WatermarkDensity;
  /** Grants must name a purpose, and the request must state the same purpose. */
  requirePurpose: boolean;
  /** Export of a watermarked derivative is possible with an explicit export grant. */
  exportAllowed: boolean;
  /** Any member of the owning tenant may view without a grant. */
  memberDefaultView: boolean;
}

const HOUR = 3600;

export const CLASSIFICATION_POLICY: Readonly<Record<Classification, ClassificationPolicy>> = Object.freeze({
  PUBLIC: {
    minAuth: "pwd",
    maxAuthAgeSeconds: 12 * HOUR,
    maxRisk: "HIGH",
    freshAuthAtElevatedRiskSeconds: null,
    capabilityTtlSeconds: 300,
    watermark: "none",
    requirePurpose: false,
    exportAllowed: true,
    memberDefaultView: true,
  },
  INTERNAL: {
    minAuth: "pwd",
    maxAuthAgeSeconds: 12 * HOUR,
    maxRisk: "HIGH",
    freshAuthAtElevatedRiskSeconds: null,
    capabilityTtlSeconds: 180,
    watermark: "light",
    requirePurpose: false,
    exportAllowed: true,
    memberDefaultView: true,
  },
  CONFIDENTIAL: {
    minAuth: "mfa",
    maxAuthAgeSeconds: 8 * HOUR,
    maxRisk: "HIGH",
    freshAuthAtElevatedRiskSeconds: 10 * 60,
    capabilityTtlSeconds: 120,
    watermark: "standard",
    requirePurpose: false,
    exportAllowed: true,
    memberDefaultView: false,
  },
  RESTRICTED: {
    minAuth: "mfa",
    maxAuthAgeSeconds: 1 * HOUR,
    maxRisk: "GUARDED",
    freshAuthAtElevatedRiskSeconds: 10 * 60,
    capabilityTtlSeconds: 90,
    watermark: "standard",
    requirePurpose: true,
    exportAllowed: false,
    memberDefaultView: false,
  },
  CROWN_JEWEL: {
    minAuth: "phishing_resistant",
    maxAuthAgeSeconds: 15 * 60,
    maxRisk: "GUARDED",
    freshAuthAtElevatedRiskSeconds: 5 * 60,
    capabilityTtlSeconds: 60,
    watermark: "dense",
    requirePurpose: true,
    exportAllowed: false,
    memberDefaultView: false,
  },
});

/** Preview width ceiling by risk state. CRITICAL never reaches media delivery. */
export const MAX_WIDTH_BY_RISK: Readonly<Record<Exclude<RiskState, "CRITICAL">, number>> = Object.freeze({
  LOW: 1600,
  GUARDED: 1200,
  HIGH: 800,
});

/** Minimum watermark density forced by risk state. */
export const DENSITY_FLOOR_BY_RISK: Readonly<Record<RiskState, WatermarkDensity>> = Object.freeze({
  LOW: "none",
  GUARDED: "standard",
  HIGH: "dense",
  CRITICAL: "dense",
});

export const maxDensity = (a: WatermarkDensity, b: WatermarkDensity): WatermarkDensity =>
  densityRank(a) >= densityRank(b) ? a : b;
