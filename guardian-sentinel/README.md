# Guardian Sentinel

**Design mode only. No live monitoring or headphone alerting is active.**

This package is the deterministic core of the consent-based personal-safety assistant specified in [`SPEC.md`](SPEC.md). It holds the parts that can be built and tested without hardware: trusted configuration, observation integrity, hazard events and detector contracts, the alert and emergency state machines, the health supervisor, the user commands and a tamper-evident audit log.

It contains **no** sensor adapters, detectors, headphone output, watch haptics, location sharing or emergency dispatch. It runs no background process and watches nothing. Nothing in it calls a phone number or an emergency service.

"Grade" words in the request (NSA, DARPA, NSC) mean engineering rigor here. They are not an assurance level, endorsement or certification, and this package has none.

## Capability states

Per SPEC section 1. The startup report prints the same registry (`guardian_core/capability.py`).

| Capability | State | Evidence |
|---|---|---|
| Trusted configuration (HMAC-authenticated, strict schema) | VERIFIED | `tests/test_gs_config.py` |
| Observation integrity gate | VERIFIED | `tests/test_gs_observation.py` |
| Detector safety contracts | VERIFIED | `tests/test_gs_contracts_hazards.py` |
| Safety-policy rules (triggers, consent, expiry, authorization) | VERIFIED | `tests/test_gs_emergency.py` |
| Alert controller (templates, routing, delivery states, dedupe, expiry) | VERIFIED | `tests/test_gs_alerts.py` |
| Health supervisor (lifecycle, coverage, routing, integrity) | VERIFIED | `tests/test_gs_health_commands.py` |
| Emergency workflow state machine | VERIFIED | `tests/test_gs_emergency.py` |
| User commands | VERIFIED | `tests/test_gs_health_commands.py` |
| Audit log | VERIFIED | `tests/test_gs_audit.py` |
| Sensor adapters, obstacle and fall detectors, official-warning feed | SPECIFIED | SPEC.md only |
| Headphone output, watch haptic fallback, location sharing, emergency dispatch | SPECIFIED | SPEC.md only |

VERIFIED means unit-tested against the requirement in `TRACEABILITY.md`. Nothing is VALIDATED (no field or controlled-exercise evidence) and nothing is ACTIVE.

## What the code enforces

- **Authority.** Configuration is accepted only with a valid HMAC-SHA256 tag under the enrollment key. Every level refuses unknown fields, so a permission can be added only by a new, re-authenticated file. Free text has no path into configuration.
- **Observations.** Malformed, unpermitted, failed, duplicate and stale input is rejected. Out-of-order, clock-inconsistent and physically implausible input is quarantined, and never drives an alert. A jump check runs only where a contract supplies the limit. Sources that share an upstream are not counted as independent, and disagreement is reported, never averaged.
- **Hazards.** Only the six supported categories exist. Nothing models another person's intent or presence, weapons, substances, radiation, explosives or medical diagnosis. A numeric confidence is accepted only from a detector whose contract says it is calibrated.
- **Contracts.** No defaults: a detector contract with any gap, or with its owner as reviewer, blocks VALIDATED.
- **Alerts.** Fixed templates only, linted to 3 to 10 words for urgent levels and free of safety claims. Delivery goes only to channels whose test passed, and each delivery state is recorded separately. Playback is never treated as acknowledgement. A duplicate is suppressed only inside an explicit window, and escalation always passes. Expired alerts repeat only as history.
- **Emergency actions.** Only actions in the approved matrix can run, for their exact trigger, while consent is valid, through a host dispatcher. Instance ids deduplicate repeats. Cancellation works only before an attempt; a sent message is never described as recalled. With no dispatcher, the refusal is immediate and points to the phone's own emergency call.
- **Integrity faults.** A recorded fault blocks external actions and keeps local alerting working.
- **Wording.** No reply says the user is safe. "No supported hazard detected in the available inputs." appears only while monitoring with fresh coverage.

## Layout

| Path | Contents |
|---|---|
| `guardian_core/` | The package (standard library only, Python 3.10+) |
| `tests/` | 108 offline tests with a fixed clock, fake channels and a fake dispatcher |
| `SPEC.md` | The owner's specification, verbatim |
| `TRACEABILITY.md` | Requirement → control → test, with residual risk and what is still open |
| `guardian.example.json` | A synthetic, unsigned configuration showing every field |

## Run it

```bash
cd guardian-sentinel
python3 -m guardian_core startup            # design-mode startup report
python3 -m guardian_core lint-templates     # check every alert template
python3 -m guardian_core keygen guardian.key.hex
python3 -m guardian_core sign-config my-plain-config.json guardian.signed.json --key guardian.key.hex
python3 -m guardian_core check-config guardian.signed.json --key guardian.key.hex
python3 -m pytest -q                        # needs pytest
```

Never commit a real configuration or key file: a configuration names real contacts, and the key authenticates it. `.gitignore` covers the default names. An HMAC key is a shared secret, so anyone holding it can sign a configuration.

## What would have to exist before any monitoring

These come from SPEC sections 2, 7, 12 and 14, and none is here:

1. A host application on the actual devices, exposing sensors, outputs and dispatch through its own permission prompts.
2. Sensor adapters that attach provenance and quality to each observation.
3. Detectors, each with a reviewed safety contract and controlled-exercise evidence.
4. Channel tests for headphones and each fallback.
5. A dispatcher that honors the platform's own confirmation rules.
6. Independent security testing.
7. Accessibility and comprehension testing of the alerts.
8. A documented residual-risk review and an accountable release approval.
