// Explainable risk scoring. Every point in a score is attributed to a named
// signal, so a reviewer can see exactly why a session was throttled or paused.
//
// Browser-reported signals are untrusted: an attacker can suppress them. They
// can only ever ADD risk. Nothing the client sends can lower a score.
//
// Not used, by design: biometrics, keystroke timing, mouse-movement profiling,
// or any inference about the person. Only session, network, and request facts.

import type { RiskState } from "./classification";

export const CLIENT_SIGNALS = [
  "visibility_hidden",
  "focus_lost",
  "devtools_suspected",
  "automation_detected",
  "rapid_navigation",
  "print_attempt",
  "copy_attempt",
  "context_menu",
] as const;
export type ClientSignal = (typeof CLIENT_SIGNALS)[number];

export interface RiskSignals {
  /** Supplied by the identity provider / edge. Defaults to false when no provider is wired in. */
  newDevice: boolean;
  impossibleTravel: boolean;
  badAsnReputation: boolean;
  sessionAgeSeconds: number;
  failedAuthzLast15m: number;
  viewRequestsLastMinute: number;
  distinctAssetsLast5m: number;
  clientSignalsLast15m: Partial<Record<ClientSignal, number>>;
}

export interface Contribution {
  signal: string;
  points: number;
  detail: string;
}

export interface RiskAssessment {
  score: number;
  state: RiskState;
  contributions: Contribution[];
}

export const RISK_THRESHOLDS = Object.freeze({ GUARDED: 20, HIGH: 45, CRITICAL: 70 });

const capped = (count: number, each: number, cap: number) => Math.min(cap, Math.max(0, count) * each);

export function assessRisk(s: RiskSignals): RiskAssessment {
  const c: Contribution[] = [];
  const add = (signal: string, points: number, detail: string) => {
    if (points > 0) c.push({ signal, points, detail });
  };

  if (s.newDevice) add("new_device", 15, "first session from this device");
  if (s.impossibleTravel) add("impossible_travel", 40, "location change faster than travel allows");
  if (s.badAsnReputation) add("asn_reputation", 20, "network flagged by reputation feed");
  if (s.sessionAgeSeconds > 12 * 3600) add("session_age", 10, "session older than 12 hours");
  add("failed_authorization", capped(s.failedAuthzLast15m, 8, 32), `${s.failedAuthzLast15m} denied requests in 15 min`);

  if (s.viewRequestsLastMinute > 60) add("view_rate", 40, `${s.viewRequestsLastMinute} view requests in 1 min`);
  else if (s.viewRequestsLastMinute > 20) add("view_rate", 20, `${s.viewRequestsLastMinute} view requests in 1 min`);
  if (s.distinctAssetsLast5m > 15) add("bulk_access", 25, `${s.distinctAssetsLast5m} distinct assets in 5 min`);

  const n = (k: ClientSignal) => s.clientSignalsLast15m[k] ?? 0;
  add("focus_changes", capped(n("visibility_hidden") + n("focus_lost"), 2, 10), "view hidden or unfocused");
  // Developer-tools detection is a heuristic with false positives; it is weighted low.
  add("devtools_heuristic", n("devtools_suspected") > 0 ? 10 : 0, "developer tools heuristic fired");
  add("automation", n("automation_detected") > 0 ? 35 : 0, "browser reports automation control");
  add("rapid_navigation", capped(n("rapid_navigation"), 5, 15), "rapid switching between protected views");
  add("print_attempt", capped(n("print_attempt"), 10, 20), "print requested on a protected view");
  add("copy_attempt", capped(n("copy_attempt"), 3, 12), "copy requested on a protected view");
  add("context_menu", capped(n("context_menu"), 1, 5), "context menu opened on a protected view");

  const score = Math.min(100, c.reduce((sum, x) => sum + x.points, 0));
  return { score, state: stateForScore(score), contributions: c };
}

export function stateForScore(score: number): RiskState {
  if (score >= RISK_THRESHOLDS.CRITICAL) return "CRITICAL";
  if (score >= RISK_THRESHOLDS.HIGH) return "HIGH";
  if (score >= RISK_THRESHOLDS.GUARDED) return "GUARDED";
  return "LOW";
}

export type ResponseAction =
  | "increase_watermark"
  | "downgrade_resolution"
  | "require_step_up_for_confidential"
  | "pause_session"
  | "revoke_capabilities"
  | "open_incident_for_human_review";

/**
 * Deterministic responses. Everything here is reversible: a paused session ends
 * when the person authenticates again. Account suspension, discipline, or any
 * accusation is never automatic; CRITICAL only opens a case for a human.
 */
export const RESPONSES: Readonly<Record<RiskState, readonly ResponseAction[]>> = Object.freeze({
  LOW: [],
  GUARDED: ["increase_watermark"],
  HIGH: ["increase_watermark", "downgrade_resolution", "require_step_up_for_confidential"],
  CRITICAL: ["pause_session", "revoke_capabilities", "open_incident_for_human_review"],
});
