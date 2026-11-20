# API specification

FastAPI service in `apps/api/main.py`. The running service publishes the full OpenAPI document at `/openapi.json`
and interactive docs at `/docs`. This page is the contract summary.

## Authentication and roles

`Authorization: Bearer <token>`.

| Role | Token | Can |
|---|---|---|
| operator | `OFFICE_OPERATOR_TOKEN` | everything, including approvals, hiring, grants, emergency stop |
| viewer | `OFFICE_VIEWER_TOKEN` | every GET |

- `OFFICE_ENV=production` without an operator token (or with one under 32 characters): the app refuses to start.
- `OFFICE_ENV=development` with no tokens: open local mode; requests act as the operator, and every response carries
  `X-Office-Auth: development-open`. Bind to 127.0.0.1.
- Mutating routes are rate-limited per client IP (`OFFICE_MUTATIONS_PER_MINUTE`, default 30) and return 429 past it.
- Request bodies reject unknown fields (422). Errors return `{"detail": "..."}` and never a stack trace.
- `tests/test_api.py` fails if any POST/PATCH route is added without the operator dependency.

## Endpoints

| Method | Path | Role | Purpose |
|---|---|---|---|
| GET | `/health` | public | Liveness, no dependencies |
| GET | `/ready` | public | 200 only if the database answers and the audit chain verifies; 503 with reasons otherwise |
| GET | `/session` | viewer | Who you are and the auth mode |
| GET | `/snapshot` | viewer | Everything the console renders, in one read model |
| GET | `/kpis` | viewer | Computed KPIs (`docs/KPIS.md`) |
| GET | `/departments` | viewer | Departments |
| GET | `/agents` | viewer | Agent directory |
| GET | `/agents/{id}` | viewer | Agent plus its last 50 audit events |
| POST | `/agents` | operator | Hire: validated against the org rules; base grants added |
| POST | `/agents/{id}/clone` | operator | Clone grants into a new identity (`new_id`, `callsign`) |
| PATCH | `/agents/{id}` | operator | Edit objective, tools, permissions, scopes; version bumps; grant edits audited as high |
| POST | `/agents/{id}/{pause\|resume\|retire}` | operator | Lifecycle; retired agents keep their history |
| GET | `/agents/{id}/grants` | viewer | The agent's grant records with limits, expiry, and revocation |
| POST | `/agents/{id}/grants` | operator | Issue or replace a grant: `{domain, level, constraints?, expires_at?}`. `level` is read, propose, write, or execute |
| POST | `/agents/{id}/grants/{domain}/revoke` | operator | Revoke a grant (`{reason}`, 12+ characters) |
| GET | `/missions` | viewer | Missions |
| POST | `/missions` | operator | Create: validates keys, assignees, dependencies, cycles. `mode` is `production` (default) or `simulation` |
| GET | `/missions/{id}` | viewer | Mission, workflow waves, tasks with governance traces |
| POST | `/missions/{id}/run` | operator | Advance the workflow until nothing more can move |
| POST | `/missions/{id}/{pause\|resume\|cancel}` | operator | Lifecycle (`{reason}`, 12+ characters). Cancel also cancels the mission's open tasks and approvals. 400 if the mission is not in a state that allows it |
| POST | `/daily-loop/run` | operator | Run the Daily Operations Loop now |
| GET | `/messages?thread_id=&kind=&limit=` | viewer | Collaboration Floor |
| GET | `/decisions` | viewer | Decision records |
| GET | `/approvals?status=` | viewer | Approval queue and history |
| GET | `/approvals/{id}` | viewer | One approval with its decision history |
| POST | `/approvals/{id}/decision` | operator | `{decision: approve\|reject\|modify, reason, modifications?}` |
| GET | `/memory?layer=` | viewer | Knowledge Vault |
| POST | `/memory` | operator | Add an approved long-term record |
| POST | `/memory/{id}/decision` | operator | Approve or reject an agent's proposal (`{approve, reason}`) |
| GET | `/simulations/scenarios` | viewer | Scenario types with example inputs |
| GET | `/simulations` | viewer | Runs on file |
| GET | `/simulations/{id}` | viewer | One run |
| POST | `/simulations` | operator | Run a scenario in the sandbox as an agent (goes through the gate). With an `Idempotency-Key` header, a repeat returns the first run with `replayed: true` |
| GET | `/reports?kind=` | viewer | Report index |
| GET | `/reports/latest/{kind}` | viewer | Latest briefing, eod, weekly, security_review, or incident |
| GET | `/reports/{id}` | viewer | One report |
| GET | `/audit?limit=&offset=&subject=&event_type=` | viewer | Ledger events, newest first |
| GET | `/audit/verify` | viewer | Replay the hash chain |
| GET | `/policy` | viewer | The policy-as-code document |
| POST | `/policy/evaluate` | operator | Dry run of steps 1-6; nothing executes or is written |
| GET | `/policy/shadow-report` | viewer | Shadow rules and where each would have changed an outcome. `enforced` is always false |
| GET | `/tools` | viewer | Tool registry |
| GET | `/vault` | viewer | Secret references and whether each is configured (never values) |
| GET | `/emergency-stop` | viewer | Current stop state |
| POST | `/emergency-stop` | operator | Engage (`{reason}`, 12+ characters) |
| POST | `/emergency-stop/release` | operator | Release (`{reason}`) |

## Approval decision semantics

```http
POST /approvals/apr_0076/decision
{"decision": "modify", "reason": "Shorter opening line before it goes out.",
 "modifications": {"text": "Before you connect AI to client files: three checks.\n\nCLEARGLASS: See Through Everything"}}
```

| Response | When |
|---|---|
| 200, status `executed` | approved; the held task resumed, ran through the connector, and produced a receipt |
| 409 | reason under 12 characters, approval not pending or already decided, expired, office halted, stored request edited since it was filed, unknown keys in `modifications`, or the edited action no longer passes policy |
| 401 / 403 | missing token / viewer token |

`modify` may only change parameter keys that already exist. The edited action is re-evaluated by the policy engine and
its digest becomes `approved_digest`. The executor runs only a payload whose digest equals it.

An approval is used once. It is consumed when execution starts, before the tool runs, so if the run then fails the
action needs a new approval. A second identical request from the same task while one is pending returns the pending
approval instead of filing another.

## Error codes

| Code | Meaning |
|---|---|
| 400 | Domain rule violated (invalid mission graph, bad grants, bad simulation inputs, rejected memory write) |
| 401 | No or wrong bearer token |
| 403 | Viewer token on an operator route |
| 404 | Unknown id |
| 409 | Approval or emergency-stop state conflict |
| 422 | Body failed schema validation or carried unknown fields |
| 429 | Mutation rate limit |
| 503 | `/ready` only: database or audit chain unhealthy |
