# ClearGlass Agent Office

**Your company, operated by intelligence.**

A governed headquarters where ClearGlass Inc.'s AI agents work as a company: 35 agents in 7 departments, missions run
as dependency graphs, and every action passes a nine-step policy pipeline. Agents draft, research, analyze, review, and
plan on their own. Anything that sends, publishes, deploys, pays, signs, deletes, or touches credentials stops at the
Approval Desk until a named human approves that exact payload.

CLEARGLASS: See Through Everything

## Status (verified 2026-11-13)

| Area | State | Verified by |
|---|---|---|
| Policy engine, nine-step pipeline, risk tiers, hard blocks | Runs | `tests/test_policy_engine.py`, control tests in every security review |
| Approval Desk (payload-bound, reason required, append-only history, modify-and-approve) | Runs | `tests/test_approvals.py` |
| Hash-chained audit ledger with database-level append-only triggers | Runs | `tests/test_audit_ledger.py`, `/ready` |
| Emergency stop (pause all, cancel open approvals, preserve state, incident record, notify) | Runs | `tests/test_emergency_stop.py` |
| Grant limits (spend caps, parameter allow-lists, expiry, revocation) | Runs | `tests/test_governance_controls.py`, `tests/test_postgres_schema.py` |
| Risk escalation (sensitive data and irreversible actions are high; any payment is critical) | Runs | `tests/test_governance_controls.py`, control tests |
| Production deploy needs a passing sandbox test run from the same mission | Runs. The runner executes allow-listed suites in a subprocess; it is **not** a container or network sandbox | `tests/test_governance_controls.py` |
| Mission pause, resume, cancel; simulation-mode missions cannot act externally or on production | Runs | `tests/test_governance_controls.py`, `tests/test_api.py` |
| Intent sealed before a tool runs; incident raised if the outcome record fails | Runs | `tests/test_governance_controls.py` |
| Approval integrity (immutable request, one decision, one use, duplicate requests merged) | Runs | `tests/test_governance_controls.py`, `tests/test_postgres_schema.py` |
| Shadow policies (evaluated on every request, never enforced) with a divergence report | Runs | `tests/test_governance_controls.py`, `GET /policy/shadow-report` |
| Idempotency keys (replay, conflict, retry after failure) | Runs | `tests/test_governance_controls.py`, `tests/test_api.py` |
| Plan-first missions (research, analysis and drafts only; every send, publish, record write and spend is denied) | Runs | `tests/test_plan_first.py`, `tests/test_postgres_schema.py` |
| Plan-first contract check for a revenue plan payload (`office.py plan-check`) | Runs. The stored plan is valid and **not ready**: approval is pending | `tests/test_plan_first.py`, [docs/REVENUE_GATEWAY.md](docs/REVENUE_GATEWAY.md) |
| Consent and suppression checks, budget reservation ledger, per-action parameter schemas | **Not built.** Required before any live connector; see [docs/REVENUE_GATEWAY.md](docs/REVENUE_GATEWAY.md) | — |
| Workflow engine (DAG, waves, retries, downstream blocking, input references) | Runs | `tests/test_workflow.py` |
| Daily Operations Loop (8 agents, 4 departments, 1 approval, briefing, end-of-day report) | Runs | `tests/test_daily_loop.py`, CI smoke run |
| Memory (task memory, operator-approved company memory, secret rejection) | Runs | `tests/test_memory_and_simulation.py` |
| Simulation Chamber (4 seeded scenario types, sandbox-only) | Runs | `tests/test_memory_and_simulation.py` |
| FastAPI API (operator/viewer roles, fails closed in production, rate limits) | Runs | `tests/test_api.py` |
| Console: 9 views, dark-glass UI, server-side action proxy, passphrase sign-in | Builds; checked in Chromium | `npm run build`, Playwright run in this session |
| PostgreSQL 16 schema with append-only triggers and integrity checks | Applies to a real server | `tests/test_postgres_schema.py` (CI service container) |
| External connectors (publish, email, deploy, payments, contracts) | **Dry-run only.** Approved actions produce a receipt; nothing leaves the machine. | `tests/test_approvals.py` |
| Runtime on PostgreSQL, Redis queue, OIDC sign-in, live connectors | **Not built.** See [docs/ROADMAP.md](docs/ROADMAP.md). | — |
| Docker images and compose stack | Written, **not built in this session** (no Docker daemon available). | — |

Agents run on deterministic skills by default, so CI and the demo need no model access. Setting
`OFFICE_LLM_PROVIDER=claude` lets drafting skills ask Claude (`claude-opus-5-5`) to rewrite a template; the provider
returns text only, and a rewrite that adds figures absent from the template is discarded.

## Run it

```bash
cd clearglass-agent-office
python3 -m pip install -r requirements-dev.txt

python office.py daily-loop                 # run today's loop against var/office.db
python office.py serve                      # API on http://127.0.0.1:8000 (docs at /docs)

cd apps/web && npm ci
OFFICE_API_URL=http://127.0.0.1:8000 npm run dev    # console on http://localhost:3000
```

Without `OFFICE_API_URL` the console renders the committed demo snapshot (fictional sample data) read-only.
`python office.py demo` rebuilds that snapshot from a fresh deterministic run.

Other commands: `verify-audit`, `approve <id> --reason ...`, `emergency-stop --reason ...`, `release-stop --reason ...`,
`plan-check <plan.json>` (validates a plan-first payload; exit 0 ready, 2 valid but blocked, 1 invalid).

### Checks

```bash
ruff check . && ruff format --check .
python -m pytest -rs                                       # 165 tests; 11 more with a PostgreSQL server:
OFFICE_TEST_PG_URL=postgresql://user:pass@localhost:5432/postgres python -m pytest -rs
cd apps/web && npm audit --audit-level=high && npm run typecheck && npm run build
```

`.github/workflows/agent-office-ci.yml` runs all of these on Python 3.11 and 3.13 with a PostgreSQL 16 service.

### Production settings

| Variable | Where | Meaning |
|---|---|---|
| `OFFICE_ENV=production` | API, console | API refuses to start without `OFFICE_OPERATOR_TOKEN` (32+ chars); console refuses actions without sign-in |
| `OFFICE_OPERATOR_TOKEN`, `OFFICE_VIEWER_TOKEN` | API | Bearer tokens for the two roles |
| `OFFICE_API_URL`, `OFFICE_API_TOKEN` | console (server only) | Where the API is and the operator token the action proxy forwards |
| `OFFICE_CONSOLE_PASSPHRASE`, `OFFICE_SESSION_SECRET` | console | Operator sign-in; signed HttpOnly SameSite=Strict cookie |
| `OFFICE_LLM_PROVIDER=claude` | API, worker | Optional Claude rewrites of drafts (needs `pip install anthropic` and credentials) |

## Deliverables

| # | Deliverable | Where |
|---|---|---|
| 1 | Product vision and positioning | [docs/PRODUCT.md](docs/PRODUCT.md) |
| 2 | System architecture | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| 3 | Repository file tree | [docs/ARCHITECTURE.md#repository-layout](docs/ARCHITECTURE.md#repository-layout) |
| 4 | Database schema | [infra/db/postgres/](infra/db/postgres/) (`001_init.sql`, `002_governance_controls.sql`), [docs/DATABASE.md](docs/DATABASE.md) |
| 5 | API specification | [docs/API.md](docs/API.md); live OpenAPI at `/docs` |
| 6 | Agent schema and permission model | [docs/AGENT_MODEL.md](docs/AGENT_MODEL.md), [config/org.json](config/org.json), [config/policy.json](config/policy.json) |
| 7 | Workflow engine design | [docs/WORKFLOW_ENGINE.md](docs/WORKFLOW_ENGINE.md) |
| 8 | UI/UX specification | [docs/UI_SPEC.md](docs/UI_SPEC.md) |
| 9 | Core code scaffolding | `packages/`, `apps/api`, `apps/worker`, `apps/web` |
| 10 | First working multi-agent workflow | `apps/worker/daily_loop.py`, [demo/missions.json](demo/missions.json) |
| 11 | Security threat model | [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md) |
| 12 | 30-day implementation roadmap | [docs/ROADMAP.md](docs/ROADMAP.md) |
| 13 | KPIs | [docs/KPIS.md](docs/KPIS.md) |

## Layout

```
clearglass-agent-office/
  office.py            CLI: daily-loop, serve, demo, verify-audit, approve, emergency-stop
  config/              company.json, org.json (7 departments, 35 agents, 12 rooms), policy.json, tools.json,
                       policy.shadow.json (candidate rules, never enforced), sandbox.json (allow-listed test suites)
  plans/               plan-first payloads awaiting approval, with their decision records and mission templates
  demo/                demo missions and a fictional prospect list
  packages/
    agent_core/        models, office runtime, governed executor, approval desk, workflow engine, skills, reports
    policy_engine/     policy-as-code loader and the gate (steps 1-6), output verification (step 8)
    audit_ledger/      hash-chained append-only ledger, canonical JSON, secret redaction
    memory_vault/      task memory and operator-approved company memory
    tool_registry/     tool registry, dry-run connector, secret references
    simulation/        seeded what-if scenarios (no imports from the runtime)
    plan_contract/     strict validator for a plan-first payload (no imports from the runtime)
    ui/                design tokens for the console
  apps/
    api/               FastAPI service
    worker/            Daily Operations Loop
    web/               Next.js console
  infra/               PostgreSQL schema, Dockerfiles, compose stack
  docs/                the deliverables above
  tests/               176 tests (11 need PostgreSQL)
```

The brief named the Python packages `agent-core`, `policy-engine`, `memory`, `tools`, and `audit`. They are
`agent_core`, `policy_engine`, `memory_vault`, `tool_registry`, and `audit_ledger` here: hyphens cannot be imported in
Python, and `memory`, `tools`, and `audit` would collide with other modules (the repository root already has `tools/`).
