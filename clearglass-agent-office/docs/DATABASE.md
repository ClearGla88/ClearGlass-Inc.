# Database schema

The production schema is [`infra/db/postgres/001_init.sql`](../infra/db/postgres/001_init.sql) (PostgreSQL 16).
`tests/test_schema_parity.py` fails if a model field has no column; `tests/test_postgres_schema.py` applies the file to
a real server and checks the constraints below.

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
| Permission | `permissions` | `level` CHECK excludes `approve` (human-only) |
| Tool | `tools` | connector in (internal, dry_run, live); `secret_ref` pattern-checked |
| Mission | `missions` | unique non-empty `key`; FK to its workflow (deferrable) |
| Workflow | `workflows` | `task_ids` and `waves` derive from `tasks.workflow_id` and `tasks.wave` |
| Task | `tasks` + `task_dependencies` | unique (workflow_id, key); no self-dependency |
| Approval | `approvals` | critical rows must carry all three plans; approved/executed rows must carry `approved_digest` |
| Approval decisions | `approval_decisions` | **append-only**; reason >= 12 characters |
| Message | `messages` | **append-only**; closed set of kinds |
| Decision | `decisions` | **append-only** |
| MemoryRecord | `memory_records` | layer/status combinations enforced; approved rows need `approved_by` |
| AuditEvent | `audit_events` | **append-only**; hashes are 64 hex characters; `prev_hash` chain verified by the app |
| Simulation | `simulations` | runs 100-20000; disclaimer required |
| Report | `reports` | briefing, eod, weekly, incident, after_action, security_review |
| RiskAssessment | `risk_assessments` | **append-only**; score 0-100; outcome allow/approval_required/deny |

Append-only tables reject UPDATE, DELETE, and TRUNCATE with `insufficient_privilege`. Every foreign key has an index.

## Migration notes

- `001_init.sql` runs in one transaction. Apply with `psql -v ON_ERROR_STOP=1 -f 001_init.sql`.
- Grant the application role INSERT and SELECT only on the append-only tables. The triggers are the second line.
- The MVP's SQLite store keeps the same record shapes as JSON; moving to PostgreSQL is a store adapter plus a one-time
  copy, with `verify()` run on the ledger before and after (roadmap week 2).
