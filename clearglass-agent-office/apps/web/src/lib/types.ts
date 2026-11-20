// Shapes returned by GET /snapshot (apps/api/snapshot.py). Only the fields the console reads are typed.

export type Tier = "low" | "medium" | "high" | "critical";
export type AgentStatus =
  | "idle" | "working" | "waiting_for_approval" | "blocked" | "completed" | "failed" | "paused" | "retired";

export interface Objective {
  id: string; title: string; metric: string; target: number; due: string;
  target_source?: string; current: number | null; measured: boolean;
}

export interface Room { id: string; name: string; floor: number; kind: string; department?: string; view?: string }

export interface Department {
  id: string; name: string; room: string; head: string; mission: string;
  responsibilities: string[]; boundaries: string[];
}

export interface Agent {
  id: string; callsign: string; name: string; department: string; reports_to: string; objective: string;
  room: string; success_criteria: string[]; skills: string[]; tools: string[]; permissions: Record<string, string>;
  memory_scopes: string[]; clearance: string; boundaries: string[]; status: AgentStatus;
  current_task_id: string | null; version: number;
  metrics: { tasks_completed: number; tasks_failed: number; approvals_requested: number; policy_denials: number };
}

export interface TraceStep { step: number; name: string; state: "pass" | "fail" | "pending" | "skipped"; detail: string }

export interface Task {
  id: string; key: string; mission_id: string; title: string; assignee: string;
  action: { type: string; params: Record<string, unknown> };
  depends_on: string[]; status: string; wave: number; attempts: number; error: string | null;
  approval_id: string | null; completed_at: string | null;
  output: {
    summary?: string; artifact?: unknown;
    governance?: { outcome: string; tier: Tier; score: number; digest: string; trace: TraceStep[]; policy_version: string };
  } | null;
}

export interface Mission {
  id: string; key: string; title: string; objective: string; department: string; owner: string; priority: number;
  deadline: string | null; deliverables: string[]; constraints: string[]; approval_rules: string[]; goal_ids: string[];
  status: string; mode: "production" | "simulation" | "plan_first"; workflow_status: string | null; waves: string[][]; tasks: Task[];
}

export interface Grant {
  id: string; agent_id: string; domain: string; level: string; granted_by: string; granted_at: string;
  constraints: { spend_limit_cents?: number; payload_allowlist?: Record<string, unknown[]> };
  expires_at: string | null; revoked_at: string | null; revoked_by: string | null;
}

export interface ShadowReport {
  shadow_version: string | null; enforced: false; total: number;
  rules: { id: string; description: string; effect: string; when: Record<string, unknown> }[];
  by_rule: { rule_id: string; divergences: number; would_deny: number; would_require_approval: number }[];
  recent: { id: string; rule_ids: string[]; action_type: string; agent_id: string; enforced_outcome: string;
    shadow_outcome: string; created_at: string }[];
}

export interface ApprovalDecision {
  seq: number; decision: string; reason: string; decided_by: string; decided_at: string;
  modifications: Record<string, unknown> | null; resulting_digest: string | null;
}

export interface Approval {
  id: string; action_type: string;
  action: { agent_id: string; action_type: string; params: Record<string, unknown>; tool_id: string | null };
  action_digest: string; requested_by: string; risk_tier: Tier; reasons: string[]; task_id: string | null;
  mission_id: string | null; change_plan: string | null; rollback_plan: string | null; verification_plan: string | null;
  status: string; approved_digest: string | null; decisions: ApprovalDecision[];
  execution: { receipt?: Record<string, unknown>; executed_at?: string } | null;
  expires_at: string; created_at: string;
}

export interface Message {
  id: string; thread_id: string; sender: string; recipient: string; kind: string; subject: string; body: string;
  mission_id: string | null; task_id: string | null; refs: string[]; created_at: string;
}

export interface DecisionRecord {
  id: string; made_by: string; kind: string; summary: string; rationale: string; outcome: string; created_at: string;
}

export interface MemoryRecord {
  id: string; layer: "short_term" | "long_term"; scope: string; title: string; content: string; source: string;
  classification: string; status: string; created_by: string; approved_by: string | null; tags: string[];
  created_at: string; expires_at: string | null;
}

export interface Quantiles { p10: number; p50: number; p90: number; mean: number }

export interface Simulation {
  id: string; scenario_type: string; title: string; assumptions: Record<string, unknown>;
  options: Record<string, unknown>[]; seed: number; runs: number; results: Record<string, Record<string, Quantiles>>;
  recommendation: { option: string; objective: string; direction: string; rationale: string; conditions: string };
  disclaimer: string; created_by: string; created_at: string;
}

export interface Scenario {
  description: string; objective: string; direction: "maximize" | "minimize"; metrics: string[];
  example: { assumptions: Record<string, unknown>; options: Record<string, unknown>[] };
}

export interface Report {
  id: string; kind: string; title: string; period: string; generated_by: string; generated_at: string;
  sections: Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
  metrics: Record<string, unknown>;
}

export interface AuditEvent {
  seq: number; event_id: string; ts: string; actor: string; actor_type: string; event_type: string; subject: string;
  payload: Record<string, unknown>; risk_tier: Tier | null; policy_version: string | null; prev_hash: string; hash: string;
}

export interface Kpis {
  agents: { total: number; active: number; by_status: Record<string, number>; success_rate: number | null };
  tasks: { total: number; by_status: Record<string, number>; completion_rate: number | null };
  approvals: { by_status: Record<string, number>; pending: number; median_decision_minutes: number | null };
  policy: { evaluations: number; by_outcome: Record<string, number> };
  pipeline: { qualified_leads: number | null; prospects_scored: number | null; quarantined_inputs: number | null; is_sample_data: boolean };
  content: { published: number };
  deployments: { executed: number; failed: number; success_rate: number | null };
  risk: {
    external_actions_without_approval: number; security_findings: Record<string, number> | null;
    control_tests_passed: number | null; control_tests: number | null; audit_chain_ok: boolean; audit_events: number;
  };
}

export interface Snapshot {
  generated_at: string;
  source: "live" | "snapshot";
  company: { id: string; name: string; tagline: string; brand_line: string; region: string; mission: string;
    operator: { id: string; name: string }; brand_guidelines: string[] };
  objectives: Objective[];
  rooms: Room[];
  departments: Department[];
  agents: Agent[];
  grants: Grant[];
  shadow: ShadowReport;
  missions: Mission[];
  approvals: Approval[];
  messages: Message[];
  decisions: DecisionRecord[];
  memory: MemoryRecord[];
  simulations: Simulation[];
  scenarios: Record<string, Scenario>;
  reports: { briefing: Report | null; eod: Report | null; weekly: Report | null; security_review: Report | null;
    incident: Report | null; index: { id: string; kind: string; title: string; period: string; generated_at: string }[] };
  kpis: Kpis;
  alerts: { severity: Tier; title: string; detail: string | null }[];
  audit: { verify: { ok: boolean; count: number; head: string; broken_at: number | null; reason: string | null };
    events: AuditEvent[] };
  policy: { version: string; tiers: Record<Tier, { score: number; approval: string; summary: string }>;
    actions: Record<string, { domain: string; level: string; tier: Tier; external: boolean }>;
    hard_blocked: Record<string, string> };
  tools: { id: string; name: string; connector: string; actions: string[]; external: boolean; risk_ceiling: Tier;
    secret_ref: string | null }[];
  vault: { ref: string; configured: boolean; owners: string[] }[];
  emergency: { halted: boolean; reason?: string; engaged_at?: string; incident_id?: string };
  revenue?: Revenue;
}

// -- Revenue Floor (packages/revenue_ops/desk.py, RevenueDesk.snapshot) --------------------------------------

export type DeskState =
  | "idle" | "queued" | "working" | "awaiting_approval" | "waiting_for_customer" | "waiting_for_payment"
  | "blocked" | "completed" | "failed" | "paused";

export interface RevenuePlan {
  kind: "do" | "wait" | "blocked" | "done"; role: string | null; step: string | null; label: string; state: string;
  detail?: string; operator_step?: string;
}

export interface RevenueOffer {
  sku: string; name: string; summary: string; scope: string[]; price_cents: number; currency: string; price_text: string;
  price_type: string; published_at: string[]; published_checked: string; assessment: boolean;
  fulfillment_requirements: string[]; status: string; approved_digest: string | null;
  decision: Record<string, unknown> | null; total_cents: number | null; missing_decisions: string[];
  last_decision: { seq: number; decision: string; reason: string; decided_by: string; decided_at: string } | null;
}

export interface TimelineEntry { at: string; kind: string; detail: string; by: string; ref: string | null }

export interface Opportunity {
  id: string; stage: string; rehearsal: boolean; source: string; source_ref: string;
  contact: { name: string; email: string; role: string | null; organization: string };
  consent: { basis: string; evidence: string | null; date: string | null; quote_requested_at?: string };
  lead_facts: {
    region?: string | null; city?: string | null; sector?: string | null; employees?: number | null;
    stated_need?: string | null; stated_need_present?: boolean; stated_need_quarantined?: boolean;
  };
  offer_sku: string | null; priority: number;
  qualification: {
    outcome?: string; score?: number; threshold?: number; why?: string; missing_evidence?: string[];
    rubric?: { id: string; label: string; result: string; points: number; required: boolean }[];
  };
  research: { items?: { text: string; source: string | null; unverified: boolean }[]; quarantined?: { text: string }[] };
  drafts: Record<string, { subject?: string; body?: string } | undefined>;
  terms: { accepted_at?: string; evidence_ref?: string; quoted_total_cents?: number };
  fulfillment: { handoff_at?: string; authorization_ref?: string; checklist?: string[] };
  timeline: TimelineEntry[]; flags: string[]; lost_reason: string | null; content_version: number;
  created_at: string; plan: RevenuePlan; offer_name: string | null; actions: string[]; money: Record<string, number>;
}

export interface TicketStep { connector: string; tool: string; fields: Record<string, unknown>; note?: string }

export interface ExternalAction {
  id: string; opportunity_id: string; kind: string; action_type: string; agent_id: string; connector: string;
  payload: Record<string, unknown>; payload_digest: string; status: string; approval_id: string | null; rehearsal: boolean;
  ticket: { steps: TicketStep[]; record: string; warning: string; released_at: string; released_by: string } | null;
  receipt: { external_ref: string; executed_at: string; connector: string; recorded_by: string } | null;
  verification: { method: string; mismatches?: string[]; checked_at?: string; checked?: string | null } | null;
  error: string | null; created_at: string;
}

export interface Desk {
  role: string; agent_id: string; title: string; callsign: string; state: DeskState; counts: Record<string, number>;
  current: { opportunity_id: string; organization: string; stage: string; step: string; detail: string } | null;
  approvals: { action_id: string; approval_id: string | null; status: string; kind: string }[];
  last_activity: {
    at: string; action_type: string; opportunity_id: string; status: string; detail: string | null; tier: string;
    approval_id: string | null; replayed: boolean;
  } | null;
  last_connector_execution: {
    action_id: string; kind: string; connector: string; external_ref: string; executed_at: string; status: string;
  } | null;
  errors: string[]; usage: { measured: boolean; note: string };
}

export interface MoneyCategory {
  id: string; label: string; value_cents: number | null; count: number | null; currency: string; definition: string;
}

export interface MetricItem {
  id: string; label: string; value: number | null; unit: string; definition: string;
  numerator: number | null; denominator: number | null;
}

export interface ReadinessItem { id: string; severity: "blocker" | "check"; title: string; detail: string; owner_action: string }

export interface ConnectorEntry { id: string; name: string; status: string; used_for: string[]; can: string[]; limits: string[] }

export interface Revenue {
  config_version: string; execution_model: string;
  paused: { paused: boolean; reason?: string; by?: string; at?: string };
  readiness: { ready_for_first_send: boolean; blockers: number; items: ReadinessItem[] };
  settings: { values: Record<string, unknown>; updated_by: string; updated_at: string; digest: string } | null;
  offers: RevenueOffer[]; team: Desk[]; opportunities: Opportunity[]; actions: ExternalAction[];
  money: {
    currency: string; categories: MoneyCategory[]; revenue_recognition: { available: boolean; reason: string };
    rehearsal_events_excluded: number;
  };
  metrics: { window_days: number; from: string; to: string; excludes: string; items: MetricItem[] };
  suppressions: { count: number; recent: { seq: number; address: string; reason: string; recorded_at: string }[] };
  lead_sources: Record<string, { label: string; connector: string | null; ref_hint: string }>;
  consent_bases: Record<string, { label: string; law: string; max_age_days: number | null; allows_first_contact: boolean }>;
  consent_note: string; contact_rules: Record<string, number>;
  connectors: { checked_at: string; method: string; connectors: ConnectorEntry[] };
  desk_states: DeskState[];
}
