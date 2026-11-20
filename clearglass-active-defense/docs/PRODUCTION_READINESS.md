# Production readiness

Status on 2026-11-19: **Stage 0 complete (lab vertical slice). Not ready for any non-lab network.** A stage counts as done only when every box has evidence recorded next to it. Nothing below is marked done without a test or a recorded run.

## Stage 0: lab vertical slice (done)

- [x] End-to-end demo over loopback: tripwire, correlation, case, approval, mock isolation, verification, approved recovery (`defense.py demo`; `test_demo_runs_end_to_end_over_loopback`)
- [x] 119 automated tests covering every test the brief requires ([REQUIREMENTS.md](REQUIREMENTS.md))
- [x] CI workflow (`.github/workflows/active-defense-ci.yml`): lint, tests on Python 3.11 and 3.13, config check, demo, audit verify, compose validation; zizmor-clean
- [x] Compose file validates; services hardened (non-root, read-only, no capabilities, internal sensor network, worker without network)

## Stage 1: inputs the owner must supply (blocking)

- [ ] **[DECISION REQUIRED]** Define "CA ART" (REQ-00)
- [ ] Verified asset inventory: owners, criticality, protected classes, management paths, dependents. Replaces the synthetic file
- [ ] Named approvers (at least two, so requester separation can work) and an on-call admin for the emergency stop
- [ ] Written authorization naming the segments where decoys may run and the assets that may be contained
- [ ] Chosen EDR and firewall products and versions, with sandbox access for contract testing
- [ ] Retention period and legal-hold owner for evidence. **[LEGAL REVIEW]** Captured request metadata can include personal information; confirm the basis for collecting it and how long to keep it (Ontario and federal privacy obligations as they apply to ClearGlass)

## Stage 2: platform

- [ ] Build the image and run the compose stack; record results (not done: no Docker daemon in the authoring session)
- [ ] Pin the base image by digest; generate an SBOM; scan it
- [ ] PostgreSQL store with the same append-only triggers and a schema test against a real server (B-03)
- [ ] TLS for the API with a managed certificate; secrets from a secret manager, not files
- [ ] Per-source rate limiting on `/v1/events` and on failed authentication (B-04)
- [ ] Ship the audit head hash off-host daily (B-05)
- [ ] Backups of the store, with a restore test

## Stage 3: one real adapter, recommend mode only

- [ ] Implement one isolation adapter to [INTEGRATION_CONTRACT.md](INTEGRATION_CONTRACT.md); pass the contract tests against the vendor sandbox; record product version and results
- [ ] Least-privilege service account for the worker only
- [ ] Two-week shadow run in `observe` on the lab segment; review every case and policy decision; tune rules
- [ ] Tabletop: emergency stop, kill switch, partial containment, sensor distrust, recovery
- [ ] Live drill on a sacrificial lab host: approve, isolate, verify, recover; record timings

## Stage 4: wider use (only after Stage 3 evidence is reviewed)

- [ ] Enforce mode for one preauthorized playbook on low-criticality lab assets, with a written policy naming who approved it
- [ ] Any non-lab asset needs a separate written authorization and a fresh Stage 3 drill on that segment

## Measurement plan

Report every measurement with its environment, workload, sample size, and limits. The `metrics` command and endpoint already label their output. Lab numbers are never quoted as production performance.

| Metric | Source | Note |
|---|---|---|
| Alert precision | closed cases not marked false positive / closed cases | Needs a reviewed sample; lab numbers are synthetic |
| Event-to-case latency | `cases.opened_at - events.occurred_at` | Includes sensor clock skew |
| Approval latency | `proposals.decided_at - created_at` | Human time; excludes policy-preauthorized decisions |
| Action-verification latency | `actions.updated_at - created_at` for verified actions | Includes queue wait |
| False containment count | containments on cases later marked false positive | Target: zero; each one gets a review |
| Recovery success | verified releases / release attempts | |

## Prioritized backlog

| ID | Item | Why it matters |
|---|---|---|
| B-01 | Resolve "CA ART" | Undefined requirement |
| B-02 | First real adapter (Stage 3) | Nothing is contained for real until it exists |
| B-03 | PostgreSQL runtime | Multi-host operation and stronger concurrency |
| B-04 | Ingest rate limiting | Rejected requests write audit rows; a flood grows the database |
| B-05 | Off-host audit anchoring | Detects wholesale replacement of the database |
| B-06 | auditd or fanotify honeyfile telemetry | inotify cannot say which process or user opened the file |
| B-07 | SIEM exporter and ticketing (contract sections 3 and 4) | Analyst workflow |
| B-08 | Operator UI | Today it is the API and `curl` |
| B-09 | Optional model-written summaries in `assist.py` | Must stay outside the decision path; the import-boundary test enforces that |
