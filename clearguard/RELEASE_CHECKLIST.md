# ClearGuard release gates

The specification (§14) sets seven gates before operational release. On 2026-11-16 none is met. This build is a design-mode core and is **not** releasable for real use.

| # | Gate | Status | What it needs |
|---|---|---|---|
| 1 | Intended use and foreseeable misuse reviewed | Not started | A written review naming supported activities, environments and exclusions, signed by the owner. |
| 2 | Controlled detector and integration testing | Not started | Sensor adapters and a host app (neither exists), then controlled exercises per detector contract. |
| 3 | Failure, recovery, cancellation and consent-revocation tests | Logic only | Unit tests cover the state machines. Tests on real devices, with real permission revocation and app suspension, are needed. |
| 4 | Malicious environmental instructions | Not applicable yet | No camera text or audio transcription exists to attack. Re-open when one is added. |
| 5 | Accessibility and alert comprehension | Not started | Testing with real listeners, in real noise, at the configured volume limits. |
| 6 | Residual risk documented | Partial | [TRACEABILITY.md](TRACEABILITY.md) lists open risks per section. |
| 7 | Accountable release approval | Not started | A named reviewer's decision, recorded with the evidence above. |

## Metrics §14 asks for

None can be reported. There is no field or controlled-exercise data: no missed-event counts, false-alert rates, latency distributions, delivery or fallback failures, coverage availability, battery or thermal data, or sample sizes. A passing unit suite is not any of these.

## What has been verified

On 2026-11-16, in an Ubuntu 24.04 container with Python 3.13.18:

- `python -m pytest -q` in `clearguard/`: every unit and integration test passes;
- `ruff check --select E9,F .`: clean;
- `python3 clearguard.py simulate examples/scenario_design_walkthrough.json`: runs, exit 0, audit chain intact.

Python 3.10, 3.11 and 3.12 run in CI only (`.github/workflows/clearguard-ci.yml`).
