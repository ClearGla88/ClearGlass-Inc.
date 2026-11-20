# ClearGuard

**CLEARGLASS: See Through Everything.** ClearGuard is the ClearGlass build of the owner's *Guardian Sentinel* personal-safety specification ([SPEC.md](SPEC.md)). It is the deterministic core that a safety app would sit on: a signed configuration, an observation integrity gate, hazard events that keep facts apart from guesses, a safety-policy engine, fixed alert templates, delivery tracking, an emergency action workflow, readiness checks, and a hash-chained audit trail.

> **Status: `0.1.0.dev0`, design mode only.** No live monitoring or headphone alerting is active. This build reads no sensor, plays no sound, and contacts no one, because it has no host app, sensor adapter, audio output, or emergency interface. The software controls are unit-tested; no detector is validated for real use. Activation always refuses, and says why. Evidence per requirement: [TRACEABILITY.md](TRACEABILITY.md). Release gates: [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md). Limits: [SECURITY.md](SECURITY.md).

## What exists, and what does not

| Part | State | Notes |
|---|---|---|
| Signed configuration, closed schema | Tested | HMAC-SHA256. Unsigned or altered files are refused. Voice cannot change it. |
| Observation integrity gate | Tested | Rejects or quarantines malformed, stale, replayed, duplicate, out-of-order, clock-inconsistent and implausible input. Judges independence from lineage. |
| Safety-policy engine | Tested | Deterministic. Unvalidated detectors can alert only in simulation, labelled `[SIMULATED]`. |
| Alert templates and delivery tracking | Tested | 10 fixed templates, 3 to 10 words each, linted for banned phrases ("you are safe", "safe to cross", "run", escape routes). |
| Emergency workflow | Tested | Signed action matrix, consent window, confirmation, countdown, de-duplication, bounded retries, expiry. Never contacts real emergency services in design or test use. |
| Readiness, coverage, lifecycle | Tested | Per-detector limitations. Activation needs a live host, validated detectors and a tested alert channel. |
| Audit trail | Tested | SHA-256 chain. Refuses location and raw-media fields. |
| Commands | Tested, typed text | The 10 commands in the spec, plus `Guardian, confirm.` |
| Headphone, watch and phone output | Specified only | No integration. |
| Fall, official-warning and camera-obstacle detectors | Specified only | Contracts exist; every review field is empty. |
| Speech recognition, background execution, emergency interface | Specified only | No integration. |

"Tested" means unit-tested in this repository against the requirement it implements. It does not mean validated in real conditions.

## Requirements

Python 3.10 or newer. Standard library only, so there is nothing to install. Verified on 2026-11-16 with Python 3.13.18. Python 3.10 to 3.12 run in CI only.

## Quick start

From this directory:

```bash
python3 clearguard.py startup
```

```bash
python3 clearguard.py say "Guardian, what is unavailable?"
```

```bash
python3 clearguard.py simulate examples/scenario_design_walkthrough.json
```

Or install it as a command:

```bash
python3 -m pip install ./clearguard
```

Real output of `startup` with no configuration (2026-11-16, abridged in the middle):

```
SIR, Guardian is not monitoring yet. I will verify authorized devices, sensor coverage, alert delivery, and emergency preferences.
Mode: design (lifecycle UNCONFIGURED)
...
Coverage: NONE
  - platform-fall-detection (device_fall_event): detector not validated; no live host integration; input platform_fall_detection: unavailable
...
Headphone and fallback test results:
  - headphones: not tested: no host integration
...
Remaining readiness failures: 9
...
Missing setup information:
  - a signed configuration: fill in clearguard.example.json, create a key with 'clearguard keygen', then 'clearguard sign-config'
Design mode only. No live monitoring or headphone alerting is active.
```

And part of the simulation (synthetic inputs, nothing sent anywhere):

```
[2026-11-16T15:00:10+00:00] event       evt-001                ALERT
    reason: detector not validated: simulation only
    alert: [SIMULATED] Possible fall detected. Do you need help?
    delivery: none: failed (no verified alert channel)
[2026-11-16T15:00:20+00:00] event       evt-002                SUPPRESSED_DUPLICATE
[2026-11-16T15:00:25+00:00] event       evt-003                REJECTED
    reason: unsupported claim 'following the user': no validated instrument supports it
[2026-11-16T15:00:40+00:00] command     Guardian, add my brother as an emergency contact. refused
    Not a supported command. Settings, contacts and permissions change only through the app's authenticated controls, never by voice.
```

## Setting up a configuration

1. Copy `clearguard.example.json` **outside the repository**. Replace every bracketed value and review every number: the countdown, retry count, expiry, consent window and volume limit in the example are placeholders for your decision, not recommendations.
2. Create a key, then sign:

```bash
python3 clearguard.py keygen --output ~/clearguard/config.key
```

```bash
python3 clearguard.py sign-config ~/clearguard/config.json --key ~/clearguard/config.key --output ~/clearguard/config.signed.json
```

3. Check it, then use it with any command that takes `--config` and `--key`:

```bash
python3 clearguard.py check-config ~/clearguard/config.signed.json --key ~/clearguard/config.key
```

```bash
python3 clearguard.py startup --config ~/clearguard/config.signed.json --key ~/clearguard/config.key
```

Never commit a key, a filled-in configuration, or an audit file. The repository is public.

## Command reference

| Command | Purpose | Exit status |
|---|---|---|
| `startup [--config F --key K]` | The §17 startup report. | 0 |
| `status [--config F --key K]` | Answer "Guardian, status." | 0 |
| `activate [--config F --key K]` | The activation flow. Always refused in this build. | 1 when refused |
| `say TEXT [--config F --key K]` | Run one command, e.g. `"Guardian, why did you alert?"` | 1 when the text is not a supported command |
| `keygen --output PATH` | New 32-byte signing key, mode 0600. Refuses to overwrite. | 0 or 2 |
| `sign-config FILE --key K --output OUT` | Validate, then sign. | 0 or 2 |
| `check-config FILE [--key K]` | Schema, signature and placeholders. | 0 accepted, 1 unsigned or unverifiable, 2 invalid, 3 bad signature |
| `contracts` | Detector contracts and every gap that blocks validation. | 0 |
| `capabilities` | Capability states and their evidence. | 0, or 2 if the registry is inconsistent |
| `lint-templates` | Check the alert templates. | 0 or 1 |
| `simulate SCENARIO [--audit-out FILE]` | Replay synthetic steps through the real gate, policy and workflows. | 0, or 3 if the audit chain breaks |
| `verify-audit FILE` | Verify an audit trail written by `simulate --audit-out`. | 0 or 3 |

Every command accepts `--json` before the command name.

## Scenario format

`examples/scenario_design_walkthrough.json` is the reference. Each step has an `at` time (ISO 8601 with an offset) and exactly one of `observation`, `event`, `command`, `tick` (advance emergency countdowns) or `activate`. Observations need every field in §5 of the spec. Events need facts, inferences, unknowns, alternatives and limitations as separate lists.

## Tests

```bash
python3 -m pip install pytest
```

```bash
python3 -m pytest -q
```

The suite also runs from the repository root (Baseline CI) and in `.github/workflows/clearguard-ci.yml` on Python 3.10 to 3.13.

## Layout

```
clearguard.py                 entry point
clearguard_core/
  config.py                   schema, signing, key handling      (spec §3)
  observation.py              integrity gate, lineage            (§5)
  events.py                   hazard events, claim screening     (§6)
  contracts.py                detector contracts, gaps           (§7)
  policy.py                   safety-policy engine               (§4)
  alerts.py                   templates, delivery, fallback      (§9, §10)
  emergency.py                action matrix workflow             (§11)
  health.py                   lifecycle, coverage, readiness     (§2, §8, §13, §17)
  audit.py                    hash-chained audit trail           (§12)
  commands.py, session.py     command grammar, session wiring    (§15, §16, §17)
  capability.py               capability states and evidence     (§1)
  data/                       capability registry, detector contracts
examples/                     synthetic scenario
tests/                        unit and integration tests
```
