# Database schema

The production schema is [`infra/db/postgres/001_init.sql`](../infra/db/postgres/001_init.sql) followed by
[`002_governance_controls.sql`](../infra/db/postgres/002_governance_controls.sql),
[`003_plan_first_mode.sql`](../infra/db/postgres/003_plan_first_mode.sql) and
[`004_revenue_operations.sql`](../infra/db/postgres/004_revenue_operations.sql) (PostgreSQL 16).
`tests/test_schema_parity.py` fails if a model field has no column or a migration is misnumbered;
`tests/test_postgres_schema.py` applies every migration to a real server and checks the constraints below.

## Entities

```mermaid
erDiagram
  companies ||--o{ departments : has
  departments ||--o{ agents : staffs
  agents ||--o{ agent_tools : granted
  tools ||--o{ agent_tools : grants
  agents ||--o{ permissions : holds
  departments ||--o{ missions : owns
  agents ||--o{ missions : leads
  missions ||--|| workflows : runs_as
  workflows ||--o{ tasks : contains
  tasks ||--o{ task_dependencies : depends
  agents ||--o{ tasks : assigned
  tasks |o--o| approvals : held_by
  approvals ||--o{ approval_decisions : decided_by
  missions ||--o{ messages : threads
  missions ||--o{ decisions : records
  agents ||--o{ simulations : runs
  reports }o--|| companies : about
  risk_assessments }o--|| tasks : assesses
  audit_events }o--|| companies : seals
  memory_records }o--|| companies : remembers
```

| Model (`agent_core.models`) | Table | Notes |
|---|---|---|
| Company | `companies` | objectives, ICP, approved sources, brand guidelines as JSONB |
| Department | `departments` | `head` FK to agents (deferrable, circular) |
| Agent | `agents` + `agent_tools` + `permissions` | `reports_to` checked by a deferred constraint trigger (agent id or `operator`) |
| Permission | `permissions` | `level` CHECK excludes `approve` (human-only). `constraints` accepts only `spend_limit_cents` (>= 0) and `payload_allowlist`; `revoked_at` and `revoked_by` must be set together |
| Tool | `tools` | connector in (internal, dry_run, live); `secret_ref` pattern-checked |
| Mission | `missions` | unique non-empty `key`; FK to its workflow (deferrable); `mode` in (production, simulation) |
| Workflow | `workflows` | `task_ids` and `waves` derive from `tasks.workflow_id` and `tasks.wave` |
| Task | `tasks` + `task_dependencies` | unique (workflow_id, key); no self-dependency |
| Approval | `approvals` | critical rows must carry all three plans; approved/executed rows must carry `approved_digest`. A guard trigger keeps the request columns and a set `approved_digest` immutable, freezes executed, rejected, cancelled, and expired rows, and rejects DELETE |
| Approval decisions | `approval_decisions` | **append-only**; reason >= 12 characters; a partial unique index allows one approve, reject, or modify per approval |
| Approval use | `approval_executions` | **append-only**; primary key is the approval id, so an approval is used once |
| Idempotency key | `idempotency_keys` | key, request digest, status (in_progress, completed, failed); a completed row must carry its result |
| Message | `messages` | **append-only**; closed set of kinds |
| Decision | `decisions` | **append-only** |
| MemoryRecord | `memory_records` | layer/status combinations enforced; approved rows need `approved_by` |
| AuditEvent | `audit_events` | **append-only**; hashes are 64 hex characters; `prev_hash` chain verified by the app |
| Simulation | `simulations` | runs 100-20000; disclaimer required |
| Report | `reports` | briefing, eod, weekly, incident, after_action, security_review |
| RiskAssessment | `risk_assessments` | **append-only**; score 0-100; outcome allow/approval_required/deny |
| ShadowDivergence | `shadow_divergences` | **append-only**; enforced and shadow outcomes must differ; at least one rule id |

Append-only tables reject UPDATE, DELETE, and TRUNCATE with `insufficient_privilege`. Every foreign key has an index.

## Revenue Floor (004)

| Table | Holds | Rules the database enforces |
|---|---|---|
| `opportunities` | One sales opportunity: stage, contact, consent, facts, drafts, terms, timeline | Closed stage set; `(source, source_ref)` unique; a lost opportunity has a reason |
| `external_actions` | An email, proposal or invoice from request to verification | One action per approval; a released action has its ticket, an executed one its receipt |
| `external_action_receipts` | One row per provider reference a person recorded | Append-only; `(connector, external_ref)` unique |
| `money_events` | Every fact about money, with the record behind it | Append-only; `(provider, record_type, external_ref, kind)` unique; `payment_received` only on a provider record; `payment_reported` only unverified |
| `suppressions` | Addresses and @domains no message may reach | Append-only; lowercase |
| `offer_decisions` | Each operator decision on an offer, with the digest of the content approved | Append-only; reason of 12+ characters; refused if recorded in an agent's name |

The SQLite runtime keeps the same append-only tables (`packages/agent_core/store.py`).

## Migration notes

- Each migration runs in one transaction. Apply them in number order with `psql -v ON_ERROR_STOP=1 -f <file>`.
  `001_init.sql` is never edited after release; changes go in a new numbered file.
- `002_governance_controls.sql` adds grant limits, mission mode, the approval guard and one-decision index,
  `approval_executions`, `idempotency_keys`, and `shadow_divergences`.
- The SQLite store keeps the immutable request in its own `approval_requests` table; PostgreSQL enforces the same
  rule with the guard trigger on `approvals`.
- Grant the application role INSERT and SELECT only on the append-only tables. The triggers are the second line.
- The MVP's SQLite store keeps the same record shapes as JSON; moving to PostgreSQL is a store adapter plus a one-time
  copy, with `verify()` run on the ledger before and after (roadmap week 2).
