# Security threat model

Scope: the Agent Office core, API, console, and their data. Method: assets, trust boundaries, STRIDE per boundary,
then the controls and where they are tested.

## Assets

| Asset | Why it matters |
|---|---|
| External effect (publish, send, deploy, pay, sign, delete) | Irreversible harm to clients, reputation, money, legal position |
| Approval decisions | The authority that turns a draft into an action |
| Audit ledger | The evidence of who decided what |
| Company memory | What every agent treats as true |
| Credentials | Access to external systems |
| Client and prospect data | Privacy obligations |

## Trust boundaries

1. Browser to console server. 2. Console server to API. 3. API to core (`GovernedExecutor`). 4. Core to connectors
(external systems). 5. Core to the model provider. 6. Untrusted content (prospect notes, web pages, documents) entering
agent inputs.

## Threats and controls

| # | Threat (STRIDE) | Control | Verified by |
|---|---|---|---|
| T1 | Agent takes an external action without approval (E) | Tiers in policy; high and critical always need approval; external actions cannot be low or medium (policy loader refuses) | `test_policy_engine.py`, control tests 1-7, KPI `external_actions_without_approval` |
| T2 | Approve one payload, execute another (T) | Approval bound to SHA-256 of the canonical payload; executor compares digests; replay after execution refused | `test_approvals.py::test_approved_payload_executes_once_and_only_that_payload` |
| T3 | Agent approves its own action (E, S) | No `approve` level for agents (config, schema CHECK); Desk requires a human principal with an approver role; refusals audited | `test_approvals.py`, `test_config.py`, `test_postgres_schema.py` |
| T4 | Prompt injection via prospect notes or documents (T, E) | Markers scanned in all inputs; matches force human review; the lead tool quarantines records; quarantined records never reach scoring; escalation to Risk & Compliance | `test_daily_loop.py::test_untrusted_input_is_quarantined_not_obeyed`, control test "Injected instructions force review" |
| T5 | Memory poisoning (T) | Agents can only propose long-term memory; operator approves with a reason; scope and clearance filters on reads | `test_memory_and_simulation.py` |
| T6 | Audit log tampering or deletion (T, R) | Hash chain with `verify()`; SQLite and PostgreSQL triggers abort UPDATE/DELETE/TRUNCATE; `/ready` fails on a broken chain | `test_audit_ledger.py`, `test_api.py::test_readiness_reports_a_broken_chain` |
| T7 | Secret leakage into prompts, memory, logs, outputs (I) | Secrets referenced by name only; resolved at the connector boundary for the owning tool; memory rejects credential-shaped text; ledger and outputs redact it | `test_audit_ledger.py::test_credentials_are_redacted_before_hashing`, `test_memory_and_simulation.py` |
| T8 | Stolen or missing API token (S) | Production refuses to start without a 32+ character operator token; constant-time compare; viewer role read-only | `test_api.py` |
| T9 | CSRF or cross-origin action from the console (S, E) | Proxy allow-lists paths, requires same-origin `Origin`, signed HttpOnly SameSite=Strict session; token never sent to the browser | code review: `apps/web/src/app/api/office/[...path]/route.ts` |
| T10 | Brute-force console sign-in (S) | Constant-time compare; 5 attempts per minute per client | `apps/web/src/app/api/session/route.ts` |
| T11 | Mass assignment / over-posting (T) | Pydantic bodies with `extra="forbid"`; agent edits limited to an allow-list of fields; `modify` limited to existing keys | `test_api.py::test_unknown_fields_are_rejected`, `test_approvals.py` |
| T12 | Runaway automation (D) | Emergency stop pauses all agents and cancels open approvals; per-IP mutation rate limit; workflow round cap; bounded retries | `test_emergency_stop.py`, `test_api.py::test_rate_limit_on_mutations` |
| T13 | Simulation used to act on the world (E) | Simulation package imports nothing from the runtime; `simulation.run` sandbox-only; War Room department rule; sandbox cannot use external actions | `test_policy_engine.py::test_sandbox_rules`, `test_memory_and_simulation.py` |
| T14 | Model output invents facts or numbers (T) | Provider returns text only, no tools; rewrites adding new figures are discarded; brand checks; citations required for research | `test_providers.py` |
| T15 | Unlawful research or surveillance (legal, reputational) | Hard blocks on surveillance, intrusion, harassment; approved-source list; cyber research needs an authorized scope | `test_policy_engine.py`, control tests |
| T16 | Privilege creep through edits (E) | Every grant edit validated, versioned, audited at high tier with before/after; least-privilege findings in each security review | `test_config.py`, security review |
| T17 | Path traversal through datasets (T, I) | Dataset paths resolved and confined to `demo/` and `data/`, `.json` only | `skills.py::_safe_dataset` |

## Residual risks (accepted for the MVP, tracked on the roadmap)

- **Single-operator model.** One human approves everything. Two-person approval for critical actions is week 4.
- **Bearer tokens instead of OIDC.** Rotate them; move to OIDC with MFA (week 3).
- **SQLite on one host.** A host compromise exposes the database file. The hash chain detects edits but cannot
  prevent them on a compromised host; ship ledger heads to an external store (week 3).
- **Injection markers are a list, not a classifier.** They catch common phrasings only. The real defense is that
  untrusted text never authorizes anything: external effects still need the operator.
- **Dry-run connectors.** When live adapters arrive, each needs scoped credentials, an allow-listed destination,
  idempotency keys, and its own review before registration ("Connector activation", below).

## Connector activation checklist

Before any connector moves from `dry_run` to `live`:

1. Scoped credential in a managed secret store; `vault:` reference only in config.
2. Destination allow-list (accounts, domains, environments) enforced inside the adapter.
3. Idempotency key = approval id; a replay is a no-op.
4. Receipt includes the provider's id for the effect and the approved digest.
5. Rollback or retraction procedure written for the action.
6. Adapter tests, then a security review run with the new tool, then operator sign-off recorded in the ledger.
