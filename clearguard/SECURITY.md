# ClearGuard security and limits

ClearGuard `0.1.0.dev0` is a design-mode core. It reads no sensor, plays no sound, and contacts no one. The controls below are real and tested. Everything that would make it a working safety product is absent, and this file says which parts.

## What is protected, and how

| Asset | Control | Limit |
|---|---|---|
| Operational configuration (contacts, actions, consent) | Closed JSON schema plus an HMAC-SHA256 signature checked with the owner's key. Unknown keys are rejected. Unsigned, wrongly signed or invalid files are never used. | Anyone with the key can sign anything. The key is a file with mode 0600, not a hardware-backed store. |
| Permissions | Voice commands come from a closed list of 11 commands. None of them writes configuration. | Typed text only; no speech input exists to attack or test. |
| Emergency actions | Only actions in the signed matrix; consent window and revocation enforced; (action, incident) de-duplication; bounded retries; expiry; optional confirmation at execution time; real emergency services are blocked in design and test use. | No emergency interface exists, so every attempt fails and says so. |
| Decision record | SHA-256 hash chain. Location and raw-media fields are refused. | Tamper-evident, not tamper-proof: whoever can rewrite the whole file can rebuild the chain. There is no off-device checkpoint. |
| Observations | Provenance fields required; stale, replayed, duplicate, out-of-order, clock-inconsistent and implausible input rejected or quarantined. | An input's own `integrity_status` is trusted as reported. A signature on an observation would prove origin, not truth. |

## Not implemented

The specification (§12) asks for implementation evidence on each of these. There is none yet, so none may be claimed:

- encryption in transit and at rest;
- isolated service identities and least-privilege process separation;
- signed updates and rollback controls;
- sandboxed processing of untrusted media (no media is processed at all);
- independent security testing;
- a dependency inventory beyond "standard library only".

## Integrity failures

`check-config` and `verify-audit` exit with status 3 on a signature or chain failure. They describe what failed (which record, which check), never who might have caused it. A configuration that fails verification is not loaded, and the session runs unconfigured, with its readiness report naming the failure.

## Handling keys and personal data

- Never commit a signing key, a filled-in configuration, or an audit file. The repository is public, and contacts are personal data. `tools/repo_hygiene.py` blocks `*.key` files.
- `clearguard keygen` refuses to overwrite an existing key.
- The audit trail stores identifiers, outcomes and reasons. It never stores coordinates, audio, images or transcripts.

## Reporting a problem

Follow the repository's root [SECURITY.md](../SECURITY.md).
