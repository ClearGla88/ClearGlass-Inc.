# ClearGlass Active Defense

**CLEARGLASS: See Through Everything.** A lab-first active-defense framework for ClearGlass Inc.: deception sensors (HTTP decoy, TCP tripwire, honeyfiles, honeytokens) feed an authenticated control API that correlates evidence, opens cases, and proposes single-asset network isolation. Nothing is isolated without an approval bound to the exact plan, and the only isolation adapter in this build is a mock.

> **Status: `0.1.0.dev0`, lab only.** Verified 2026-11-19 in the authoring session: 119 tests pass on Python 3.13, the end-to-end demo runs over real loopback sockets, and `docker compose config` validates the stack. Python 3.11 runs in CI only. The Docker image was **not built** (no Docker daemon in the authoring environment). No vendor adapter exists. Nothing in this package changes a real firewall, endpoint, credential, or network.

"Active defense" here means deception, monitoring, evidence collection, and containment of inventoried, owner-authorized assets. It never means hack-back, scanning third parties, deploying malware, or touching anything outside the authorized inventory.

## Unresolved requirement: "CA ART"

The brief names "CA ART" without a definition. It is recorded as `REQ-00` in [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md) and is **not implemented**, and no expansion has been guessed. **[DECISION REQUIRED]** The owner needs to say what it means. Everything else was built without it.

## What exists

| Component | State | Evidence |
|---|---|---|
| Normalized event schema (strict, typed) | Implemented, tested | `active_defense/models.py`; `tests/test_ingest.py` |
| Authenticated ingestion: per-sensor HMAC, clock-skew window, nonce replay, dedup, size limits, category, environment and scope checks | Implemented, tested | `active_defense/engine.py`; `tests/test_ingest.py` (25 tests) |
| Asset identity: static and DHCP bindings, NAT and proxy ranges, ambiguity, staleness, authorized scanners, conflicting assertions | Implemented, tested | `active_defense/assets.py`; `tests/test_policy.py` |
| Detection and correlation rules (YAML, versioned, exact-match only) | Implemented, tested | `rules/detections.yaml` |
| Deterministic containment policy (12 recorded checks, three modes) | Implemented, tested | `active_defense/policy.py`; `tests/test_policy.py` |
| Eight playbooks (YAML) and the persisted case state machine | Implemented, tested | `playbooks/`; `active_defense/store.py` |
| Hash-bound, single-use, expiring approvals with requester separation | Implemented, tested | `active_defense/operations.py`; `tests/test_approvals.py` |
| Durable executor: leases, reconciliation, bounded retries, circuit breaker, kill switch, deadlines | Implemented, tested | `active_defense/executor.py`; `tests/test_executor.py` |
| Mock isolation adapter with fault injection | Implemented, tested | `active_defense/adapters/mock.py` |
| Evidence artifacts, SHA-256 manifests, custody, retention; hash-chained append-only audit | Implemented, tested | `active_defense/evidence.py`, `store.py`; `tests/test_evidence_audit.py` |
| FastAPI control API with role-based access (analyst, approver, admin) | Implemented, tested | `active_defense/api.py`; `tests/test_api.py` |
| HTTP decoy, TCP tripwire, honeyfile watcher (inotify on Linux, polling elsewhere), honeytokens | Implemented, tested over loopback | `active_defense/sensors/`; `tests/test_sensors.py` |
| Benign synthetic event generator (7 scenarios) | Implemented | `active_defense/simulate.py` |
| End-to-end demo | Runs | `python3 defense.py demo`; `tests/test_boundaries.py` |
| Docker image and local-only compose stack | Written; compose validated; **not built** | `Dockerfile`, `docker-compose.yml` |
| EDR, firewall, SIEM and ticketing adapters | **Not implemented.** Contract only | [docs/INTEGRATION_CONTRACT.md](docs/INTEGRATION_CONTRACT.md) |
| PostgreSQL runtime | **Not implemented.** SQLite only | [docs/PRODUCTION_READINESS.md](docs/PRODUCTION_READINESS.md) |
| Model-assisted summaries | **Not wired.** Deterministic templates only | `active_defense/assist.py` |

"Tested" means covered by this package's automated tests against synthetic data. It does not mean validated against real attacks, real networks, or real vendor products.

## Quick start

Requires Python 3.11 or newer.

```bash
cd clearglass-active-defense
python3 -m pip install -r requirements-dev.txt
python3 -m pytest                  # 119 tests
python3 defense.py demo            # end-to-end lab walk-through on 127.0.0.1
```

Output of `demo` from the authoring session (2026-11-19, abridged; IDs, ports and hashes change on every run):

```
[01] honeytoken minted and registered: token_id=ht-07387cda63b4e9e3, stored=fingerprint only
[03] HTTP decoy answered a request carrying the honeytoken: status=401
[06] loopback source is not an inventoried asset, so its case can only be investigated: cases=[('ip:127.0.0.1', 'enriched')]
[07] synthetic tripwire hit from 10.66.10.21: http=200, identity=RESOLVED, subject=asset:lab-ws-001, case=case-6f0999560e48f378
[08] decoy alone: alert raised, no proposal: state=enriched, proposals=0
[09] endpoint alert on lab-ws-001 corroborates the decoy hit: http=200, correlation=COR-COMPROMISE-001, state=awaiting_approval
[10] isolation proposal awaiting approval: proposal=prop-b4e4d70c594b76f6, plan_hash=1ea92d8a7c06cf16, target=lab-ws-001, preserved=['10.66.0.10/32:22', '10.66.0.11/32:443']
[11] refused: analyst cannot approve; altered plan hash is rejected: analyst=403, tampered=409, reason=submitted plan hash does not match the proposal; review the current plan
[12] approver-1 approved the exact plan; a replayed approval is refused: http=200, replay=409, reason=proposal is approved; one decision is recorded per proposal
[13] worker applied mock isolation and verified it: result=verified, state=verified, adapter_rules=5
[14] analyst requested recovery with every criterion evidenced: http=200, proposal=prop-1c3269396fd2f356
[15] approver-2 approved release; worker released and verified: http=200, result=verified, state=closed, baseline_rules_untouched=True
[16] audit chain verified: ok=True, records=55
[17] case evidence verified: ok=True, artifacts=2
```

## Running it as services

```bash
python3 defense.py init-secrets config/defense.example.yaml   # 0600 files in ./secrets, never overwrites
python3 defense.py check-config config/defense.example.yaml
python3 defense.py serve  config/defense.example.yaml          # API on 127.0.0.1:8088
python3 defense.py worker config/defense.example.yaml          # executor; loads no sensor key or API token
python3 defense.py sensor tcp --sensor-id sensor-tcp-01 --key-file secrets/sensor-tcp-01.key \
    --scope clearglass-lab-01 --port 2222                      # each sensor holds only its own key
python3 defense.py send-synthetic config/defense.example.yaml --scenario corroborated
```

The example configuration starts in **observe** mode: cases, alerts, and a recorded "what policy would have done", with no proposals. Change `mode` to `recommend` to get approval-gated proposals. `enforce` needs `response.enforce_acknowledged: true` and a named preauthorized playbook, and even then never auto-executes against a critical or protected asset, or one with high-criticality dependents.

The API refuses to listen on a non-loopback address without TLS (`--tls-cert`, `--tls-key`). The compose stack is the one exception, and it has to be opted into explicitly; see [docs/RUNBOOK.md](docs/RUNBOOK.md).

## Commands

`check-config`, `init-secrets`, `init-db`, `serve`, `worker`, `demo`, `verify-audit`, `verify-evidence CASE`, `metrics`, `mint-honeytoken`, `create-honeyfile PATH`, `kill-switch on|off`, `retention`, `send-synthetic`, `sensor http|tcp|honeyfile`. Run `python3 defense.py <command> --help` for options.

## Layout

```
clearglass-active-defense/
  defense.py                 command line
  active_defense/
    models.py config.py      strict schemas; fail-closed loading and cross-validation
    signing.py engine.py     request signing; ingestion, identity, rules, correlation, playbook runner
    assets.py policy.py      identity resolution; deterministic containment policy
    operations.py api.py     approvals, recovery, emergency stop, queries; FastAPI control API
    executor.py              the only caller of an isolation adapter
    adapters/                contract, mock adapter, explicit "unimplemented" placeholders
    sensors/                 HTTP decoy, TCP tripwire, honeyfile watcher, signed client
    evidence.py store.py     artifacts, manifests, custody, retention; SQLite schema and audit chain
    honeytokens.py simulate.py lab.py demo.py assist.py
  config/ rules/ playbooks/  synthetic inventory, example deployment, detections, 8 playbooks
  deploy/                    container configuration for docker-compose.yml
  docs/                      architecture, runbook, integration contract, requirements, readiness
  tests/                     119 tests
```

## Documents

- [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md): assumptions, the unresolved "CA ART" requirement, authorization boundaries, and requirement-to-test traceability.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): diagram, trust boundaries, data flows, state machine, threat model.
- [docs/RUNBOOK.md](docs/RUNBOOK.md): operator procedures, emergency stop, recovery checklist.
- [docs/INTEGRATION_CONTRACT.md](docs/INTEGRATION_CONTRACT.md): what an EDR, firewall, SIEM or ticketing adapter must do before it may be enabled.
- [docs/PRODUCTION_READINESS.md](docs/PRODUCTION_READINESS.md): staged checklist and prioritized backlog.
- [SECURITY.md](SECURITY.md): limits, evidence limits, and how to report a problem.

Never commit a key, token, filled-in inventory, database, or evidence file. The repository is public.
