# 30-day implementation roadmap

Day 0 is the merge of this MVP. Each week ends with a working, tested increment and a go/no-go check. Nothing in a
later week weakens a gate from an earlier one.

Landed since day 0: grant limits, risk escalation for sensitive data, irreversible actions and payments, the
test-evidence gate on production deploys, mission pause/resume/cancel with simulation mode, the pre-execution
intent record, approval integrity, shadow policies, and idempotency keys. These were ported from the earlier
`agent-office/` kernel as tested JSON-rule behavior.

## Week 1 (days 1-7): run it for real, every day

| Deliverable | Done when |
|---|---|
| Deploy API + console + worker on one host (compose), behind TLS, `OFFICE_ENV=production` | `/ready` is 200 from outside; console requires sign-in |
| Daily loop on a schedule (weekdays) against real ClearGlass missions, not the demo | 5 consecutive end-of-day reports with a verified chain |
| Replace the sample prospect list with an operator-curated list from approved sources | Lead research runs on it; sample-data label gone |
| Operator review rhythm: approvals checked twice a day | Median decision time measured (KPI) |
| Backups: nightly SQLite backup + ledger head exported | Restore tested once; `verify()` passes on the restored copy |

Go/no-go: zero unapproved external actions, 22/22 control tests, no open critical findings.

## Week 2 (days 8-14): durable state and concurrency

| Deliverable | Done when |
|---|---|
| PostgreSQL store adapter implementing `Store` on `001_init.sql` | Full test suite passes on PostgreSQL; parity test still green |
| One-time migration SQLite to PostgreSQL | Ledger `verify()` identical before and after (same head hash) |
| Queue-backed worker (Redis or a managed queue): one job per ready task, reusing the per-attempt idempotency key already on every task (`task:<id>:attempt:<n>`) | A wave's tasks run concurrently; audit order stays consistent per task |
| Move `tests.run_sandbox` from a subprocess into an isolated container; add a `code.commit_branch` handler (branch-only push) | Test runs have no network or host access; engineering missions produce real branches |

## Week 3 (days 15-21): identity and the first live connector

| Deliverable | Done when |
|---|---|
| OIDC sign-in with MFA for the console; API accepts short-lived JWTs; bearer tokens retired | Sign-in through the identity provider; token rotation documented |
| Ledger head anchoring: daily head hash written to an external, write-once store | A tampered database is detectable from outside the host |
| First live connector: `social.publisher` (LinkedIn), through the activation checklist in THREAT_MODEL.md | One approved post published; receipt carries the provider's post id |
| Claude tool-use loop for drafting agents, inside the gate: the model proposes actions, the executor decides | Every model-proposed action has a trace; denials are visible in the console |

## Week 4 (days 22-30): scale the controls

| Deliverable | Done when |
|---|---|
| Two-person rule for critical actions (second approver or a time delay) | `deploy.production` needs two decisions |
| Live `email.outbox` connector with per-recipient allow-list and daily cap | Outreach to an approved prospect sends; caps enforced |
| Weekly performance report scheduled; KPI trends in the Briefing Room | Four weeks of KPI history visible |
| Observability: structured logs, request ids, metrics (RED per route, gate outcomes, approval latency) | Dashboards and alerts for `/ready` failures and halted state |
| Security review on a schedule, plus an external review of the gate and connectors | Findings triaged; criticals fixed before day 30 |

## Day-30 exit criteria

1. 20 working days of daily loops with a verified chain on PostgreSQL.
2. At least one live connector, with zero unapproved external actions.
3. OIDC sign-in, anchored ledger heads, and the two-person rule for critical actions.
4. KPIs from `docs/KPIS.md` reported weekly, with real (non-sample) pipeline data.
