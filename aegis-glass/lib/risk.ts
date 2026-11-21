// Explainable risk scoring. Every point added carries the signal and the reason,
// so a reviewer can see exactly why a session changed state. No biometrics, no
// keystroke data, no hidden behavioural profile: the signals are server-side
// request counts plus facts the identity provider already reports.

import type { RiskState } from "./types.ts";

export interface RiskSignals {
  /** First time this browser's device cookie has been seen for the user. */
  newDevice: boolean;
  /** Reported by the identity provider or edge; not computed here. */
  impossibleTravel: boolean;
  networkReputation: "good" | "unknown" | "bad";
  /** Denied authorization attempts by this session in the last 10 minutes. */
  deniedAttempts10m: number;
  /** Capability requests by this session in the last 5 minutes. */
  viewRequests5m: number;
  /** Distinct assets requested by this session in the last 5 minutes. */
  distinctAssets5m: number;
  /** Honey (decoy) assets touched by this session, ever. */
  honeyTouches: number;
  /** Outside the tenant's configured working hours (disclosed to users). */
  outsideConfiguredHours: boolean;
}

export interface RiskContribution {
  signal: keyof RiskSignals;
  points: number;
  reason: string;
}

export interface RiskAssessment {
  score: number;
  state: RiskState;
  contributions: RiskContribution[];
}

/** Score thresholds, inclusive lower bounds. */
export const RISK_THRESHOLDS: Record<RiskState, number> = {
  LOW: 0,
  GUARDED: 20,
  HIGH: 45,
  CRITICAL: 70,
};

export function stateForScore(score: number): RiskState {
  if (score >= RISK_THRESHOLDS.CRITICAL) return "CRITICAL";
  if (score >= RISK_THRESHOLDS.HIGH) return "HIGH";
  if (score >= RISK_THRESHOLDS.GUARDED) return "GUARDED";
  return "LOW";
}

export function assessRisk(s: RiskSignals): RiskAssessment {
  const c: RiskContribution[] = [];
  const add = (signal: keyof RiskSignals, points: number, reason: string) => c.push({ signal, points, reason });

  if (s.newDevice) add("newDevice", 10, "first request from this device");
  if (s.impossibleTravel) add("impossibleTravel", 35, "identity provider reported impossible travel");
  if (s.networkReputation === "bad") add("networkReputation", 25, "network on a bad-reputation list");
  else if (s.networkReputation === "unknown") add("networkReputation", 5, "network reputation unknown");
  if (s.deniedAttempts10m >= 3) add("deniedAttempts10m", Math.min(30, s.deniedAttempts10m * 5), `${s.deniedAttempts10m} denied requests in 10 minutes`);
  if (s.viewRequests5m > 40) add("viewRequests5m", 20, `${s.viewRequests5m} view requests in 5 minutes`);
  if (s.distinctAssets5m > 15) add("distinctAssets5m", 25, `${s.distinctAssets5m} distinct assets in 5 minutes (bulk viewing)`);
  if (s.honeyTouches > 0) add("honeyTouches", 45, "decoy asset requested");
  if (s.outsideConfiguredHours) add("outsideConfiguredHours", 5, "outside configured working hours");

  const score = c.reduce((sum, x) => sum + x.points, 0);
  return { score, state: stateForScore(score), contributions: c };
}

/** What each state does. Irreversible actions always go to a human queue. */
export const RISK_RESPONSES: Record<RiskState, { automatic: string[]; humanReview: string[] }> = {
  LOW: { automatic: [], humanReview: [] },
  GUARDED: { automatic: ["watermark density +1"], humanReview: [] },
  HIGH: {
    automatic: ["preview width capped at 640px", "watermark density 4", "capability TTL 20s", "fresh phishing-resistant login for RESTRICTED and above"],
    humanReview: [],
  },
  CRITICAL: {
    automatic: ["all media capabilities denied for this session (re-login clears the session state)"],
    humanReview: ["revoke grants", "suspend account", "open or escalate an incident case"],
  },
};
