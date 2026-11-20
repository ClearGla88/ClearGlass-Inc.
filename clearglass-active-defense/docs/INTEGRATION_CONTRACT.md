# Integration contract

No real EDR, firewall, SIEM or ticketing integration exists in this build. Configuration refuses any adapter name other than `mock`, and `adapters/base.py` holds an `UnimplementedAdapter` placeholder that refuses every call. This document is what an implementation must satisfy **before** that refusal is lifted. No vendor API is named here because none has been verified against current documentation.

## 1. Isolation adapter (EDR network containment or firewall)

Interface: `IsolationAdapter` in `active_defense/adapters/base.py`.

| Method | Must do | Must never do |
|---|---|---|
| `apply_isolation(asset_id, key, steps, preserve)` | Add allow rules for every `preserve` path first, then the deny steps. Tag every object it creates with `key`. Be idempotent: a second call with the same key changes nothing. Return `applied`, `partial` (with the steps applied), or `error` | Flush, reorder or replace existing policy. Touch objects without its tag. Isolate a target not resolved to exactly one device |
| `release_isolation(asset_id, key)` | Remove only objects tagged with `key` | Remove anything else, including other incidents' containment |
| `state(asset_id, key)` | Report the steps actually present on the device, read from the device | Answer from a local cache |
| `verify_isolation(...)`, `verify_released(...)` | Confirm from the device; return `(ok, detail)` | Return success without reading the device |

Operational requirements:

- **Credentials** come from a secret store and are given to the worker process only. Least privilege: create and delete tagged containment objects on in-scope devices, and nothing else.
- **Identity**: map `asset_id` to the vendor's device ID through the inventory, never through an IP address.
- **Timeouts**: every call must finish or fail inside `response.adapter_timeout_seconds`. Ambiguous results are handled by reconciliation, which depends on `state` telling the truth.
- **Rate limits**: respect the vendor's limits. Report a 429-style refusal as `error`; it counts toward the circuit breaker.
- **Tests before enablement**: run the contract tests in `tests/test_executor.py` against a vendor sandbox (apply, idempotent re-apply, partial, timeout, reconciliation, release, unrelated objects unchanged), and record the results with the product version.

## 2. Sensor and EDR event source

Any new source posts to `POST /v1/events` with the signed envelope in `active_defense/signing.py` and the `EventIn` schema in `models.py`.

- One HMAC key per source. Only `edr`-kind sensors may set `asserts_asset_identity`, and only for agents whose asset binding the vendor authenticates.
- Map vendor verdicts to the typed attributes the rules match (`verdict`, `behavior`). Unmapped values raise no signal, by design.
- Never send credentials, tokens, or raw payloads. Send fingerprints (`honeytoken_fingerprints`) and hashes.

## 3. SIEM export (planned, read-only)

Planned: an exporter that reads the audit table after a given `seq` and forwards records with their `hash` and `prev_hash`, so the SIEM can re-verify the chain. It must be read-only against the store and use its own credentials. It must not receive containment credentials.

## 4. Ticketing (planned)

Planned: create or update a ticket from `alert.recorded`, `case.escalated` and `proposal.created` audit records. A ticket comment is never an approval. Approvals happen only through `/v1/proposals/{id}/decision` with an approver token.

## 5. Notifications

Today, `notify` steps are recorded as `notification.recorded` with `delivered: false`. Any channel added later receives case IDs and summaries, never evidence content or tokens.
