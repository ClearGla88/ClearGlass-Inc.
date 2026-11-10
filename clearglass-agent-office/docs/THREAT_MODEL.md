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
| T2 | Approve one payload, execute another (T) | Approval bound to SHA-256 of the canonical payload; executor compares digests; the approval is consumed before the tool runs, so it is used once | `test_approvals.py::test_approved_payload_executes_once_and_only_that_payload`, `test_governance_controls.py::test_approval_is_consumed_before_the_tool_runs` |
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
| T18 | A broad grant is used past its intent, or after it should have ended (E) | Grant limits: spend cap, parameter allow-list, expiry, operator revocation; limits survive unrelated edits; PostgreSQL CHECKs on the limit shape | `test_governance_controls.py` (grant tests), `test_postgres_schema.py::test_grant_limits_and_revocation_are_checked` |
| T19 | Risk understated for sensitive data, irreversible actions, or payments (E) | Modifiers lift sensitive data and `reversible: false` to high and any `amount_cents > 0` to critical; malformed amounts denied; the loader refuses a finance action below critical | `test_governance_controls.py::test_sensitive_data_raises_to_high`, `::test_irreversible_raises_to_high_but_only_for_false`, `::test_any_payment_is_critical`, `::test_policy_loader_refuses_weak_or_malformed_rules` |
| T20 | Untested code reaches production (T) | `deploy.production` denied without a passed sandbox test run from the same mission; evidence from another mission or a failed run is refused; the runner takes suite ids, never commands | `test_governance_controls.py::test_passing_run_unlocks_the_deploy_approval`, `::test_failing_run_blocks_the_deploy`, `::test_evidence_must_come_from_the_same_mission`, `::test_runner_refuses_commands_outside_the_allow_list` |
| T21 | Work continues on a paused or cancelled mission, or a simulation acts on production (E) | The gate refuses any mission that is not active; lifecycle changes need a human and a reason; cancel also cancels open tasks and approvals; simulation missions cannot take external or production actions | `test_governance_controls.py::test_pause_resume_cancel`, `::test_paused_mission_approval_cannot_be_decided`, `::test_cancel_cancels_pending_approvals`, `::test_simulation_missions_cannot_touch_production` |
| T22 | An action runs and leaves no record (R) | `action.intent` sealed before the tool runs; no intent, no execution; a lost outcome record raises a critical incident and is flagged by the next security review | `test_governance_controls.py::test_intent_is_sealed_before_execution`, `::test_no_intent_record_means_nothing_runs`, `::test_lost_outcome_opens_an_incident_and_the_review_flags_it` |
| T23 | Approval edited after it was filed, decided twice, or the queue flooded with duplicates (T, R, D) | Request stored once in an append-only record and compared before every decision and use; one decision per approval enforced by a unique index; identical pending requests for a task are merged | `test_governance_controls.py::test_edited_approval_document_is_refused`, `::test_request_record_is_append_only`, `::test_database_allows_one_decision`, `::test_identical_pending_requests_are_merged`, `test_postgres_schema.py` |
| T24 | A policy change ships without knowing what it would block (T) | Shadow rules run on every request and are never enforced; divergences are recorded and reported; the shadow file is validated at load | `test_governance_controls.py::test_shadow_rules_are_reported_not_enforced`, `::test_shadow_rules_do_not_fire_without_divergence`, `::test_shadow_file_is_validated` |
| T25 | A retried or duplicated request acts twice (T) | Idempotency keys: a completed key replays its stored result, a different payload under the same key is refused, a failed attempt can retry; workflow tasks carry a key per attempt | `test_governance_controls.py::test_same_key_replays_instead_of_acting_twice`, `::test_reusing_a_key_for_a_different_request_is_refused`, `::test_a_failed_attempt_can_be_retried_with_its_key`, `::test_workflow_tasks_carry_keys` |

## Residual risks (accepted for the MVP, tracked on the roadmap)

- **Single-operator model.** One human approves everything. Two-person approval for critical actions is week 4.
- **Bearer tokens instead of OIDC.** Rotate them; move to OIDC with MFA (week 3).
- **SQLite on one host.** A host compromise exposes the database file. The hash chain detects edits but cannot
  prevent them on a compromised host; ship ledger heads to an external store (week 3).
- **Injection markers are a list, not a classifier.** They catch common phrasings only. The real defense is that
  untrusted text never authorizes anything: external effects still need the operator.
- **The sandbox test runner is not an isolation boundary.** It runs allow-listed suites in a subprocess with no
  shell, a scrubbed environment, and a timeout. It does not restrict the network or the filesystem. Suites are
  the office's own tests, and `config/sandbox.json` is a reviewed file. Container isolation is on the roadmap.
- **Shadow rules cost one evaluation per request and can be noisy.** They never change an outcome.
- **Dry-run connectors.** When live adapters arrive, each needs scoped credentials, an allow-listed destination,
  idempotency keys, and its own review before registration ("Connector activation", below).

## Connector activation checklist

Before any connector moves from `dry_run` to `live`:

1. Scoped credential in a managed secret store; `vault:` reference only in config.
2. Destination allow-list (accounts, domains, environments) enforced inside the adapter.
3. Idempotency key = approval id, passed to the provider as well as to the executor; a replay is a no-op.
4. Receipt includes the provider's id for the effect and the approved digest.
5. Rollback or retraction procedure written for the action.
6. Adapter tests, then a security review run with the new tool, then operator sign-off recorded in the ledger.
