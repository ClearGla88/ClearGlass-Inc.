# Architecture and threat model

Verified against this tree on 2026-11-19.

## Components and trust boundaries

```
 LAB SEGMENT (untrusted traffic)          SENSOR HOSTS                    CONTROL HOST
 ─────────────────────────────            ──────────────────────          ─────────────────────────────────────────────
                                          holds: its own HMAC key only
 attacker / scanner / user ─► HTTP decoy ─┐
                          ─► TCP tripwire ┼─ signed event ─► │B1│ ─► control API (FastAPI) ──────────┐
 file access on host ─────► honeyfile ────┘  (HMAC, ts,      │  │    holds: sensor keys (verify),     │
                                              nonce)          │  │    token hashes; NO adapter         │
 endpoint agent (mock) ───► edr sensor ───────────────────────┘  │                                     ▼
                                                                  │                ┌─ engine: authenticate ► validate ► dedup
 analyst / approver / admin ── bearer token ──────────── │B2│ ───┘                │   ► identity ► rules ► cases
                                                                                  │   ► correlation ► playbook ► policy
                                                                                  │   ► proposal (hash-bound plan)
                                                                                  ▼
                                                                         SQLite store (WAL)
                                                                         cases, signals, proposals, approvals,
                                                                         actions (leased), containments, evidence,
                                                                         custody, append-only hash-chained audit
                                                                                  ▲
                                                                     │B3│ approved action rows only
                                                                                  │
                                                       executor (worker) ─────────┘   holds: adapter access only;
                                                         re-checks approval,          no sensor key, no API token,
                                                         plan hash, policy version,   no network in compose
                                                         deadline, target, trust,
                                                         limits, stop, breaker
                                                                  │ │B4│
                                                                  ▼
                                                       isolation adapter (mock: its own SQLite "device")
```

| Boundary | What crosses it | Controls |
|---|---|---|
| B1 sensor → API | Signed JSON events | Per-sensor HMAC-SHA256 over the timestamp, nonce and body hash; ±300 s skew; nonce store for at least twice the skew; schema with no extra fields; 64 KiB cap; sensor may only report its allowed categories; environment and scope must match; `(sensor_id, event_id)` dedup |
| B2 people → API | Bearer tokens | SHA-256 token lookup; one role per principal; role checked in the API and again in `operations.py`; request bodies forbid extra fields; TLS required off loopback |
| B3 store → executor | Approved action rows | Executor re-validates everything inside a transaction before each adapter call. The approval's plan hash must equal the proposal's stored hash, the recomputed hash, and the action's hash |
| B4 executor → device | Apply, release, state, verify | Adapter touches only rules tagged with the action's idempotency key; management allow rules before deny rules; timeout per call |

## Data flow for one incident

1. A sensor signs and posts an event. The engine authenticates it, validates it, checks the nonce and deduplicates, then stores the exact body as an artifact (SHA-256 and custody record) and the normalized event.
2. Identity: the subject is the event source, the decoy's host, or an asset asserted by an identity-asserting sensor. An IP resolves to an asset only when exactly one inventoried asset holds it under a current binding outside shared ranges.
3. Detection rules raise signals (exact matches on typed fields). Each signal joins the open case for its subject, or opens one: `received → validated → enriched`.
4. A single-signal playbook (PB-01, PB-02, PB-08) records alerts, preserves evidence, and escalates. It can never propose containment, and configuration validation enforces that.
5. Correlation rules evaluate the case's trusted signals inside a window around each signal's occurrence time, so late and out-of-order events still count. A match starts PB-03, PB-04 or PB-05.
6. Policy runs 12 checks and records all of them. Any failure means `denied`, and the case moves to `rejected` and is escalated. Otherwise the proposal is `awaiting_approval`. In enforce mode it is `approved` by policy, but only for a preauthorized playbook and a low-criticality asset with no high-criticality dependents.
7. An approver submits the plan hash and policy version they reviewed. The decision is recorded once (append-only) and queues one action row with an idempotency key and an execution deadline.
8. The executor leases the row, re-checks, calls the adapter with a timeout, then verifies. Ambiguous outcomes (a timeout or a crash) are reconciled against the device's actual state.
9. Recovery: an analyst evidences each PB-07 criterion, a different approver approves the exact release plan, and the executor removes only the tagged rules and verifies none remain. The case closes.

## Case state machine

```
received → validated → enriched → proposed → awaiting_approval → executing → verified → recovery_pending → closed
                │            │        │  │           │   │  │          │  │                 │   │
                └ rejected   └ closed │  └ executing │   │  └ closed   │  └ partially_       │   └ verified (release
                                      │   (enforce)  │   └ expired     │    completed        │     rejected/expired)
                                      └ rejected ◄───┘ rejected        └ failed              └ partially_completed
rejected | expired | failed → proposed (new evidence) or closed;  partially_completed → recovery_pending or proposed
```

Any transition not in `CASE_TRANSITIONS` (`store.py`) raises. Every transition is written to `case_transitions` (append-only) and to the audit chain.

## Threat model

| Threat | Mitigation | Residual risk |
|---|---|---|
| Forged sensor events | HMAC per sensor; category allow-list per sensor kind | A stolen sensor key forges that sensor. Decoy-only sensors cannot authorize containment alone, and PB-08 distrusts a sensor on an integrity-monitor report |
| Replay of captured requests | Timestamp window and nonce store; `nonce_ttl >= 2 × skew` is enforced by configuration | None known within one database |
| Telemetry poisoning to isolate a critical host | Protected classes cannot be authorized; critical assets always need a human; identity must resolve uniquely; non-decoy identity-asserting evidence required; approval required by default | A compromised EDR key plus a decoy hit can produce a proposal for a low-criticality asset, which a human still approves |
| Spoofed source IP to frame a host | Decoy evidence alone never proposes; NAT, shared and ambiguous addresses never resolve | A spoofed completed TCP handshake is hard but possible on a flat LAN; the endpoint-evidence requirement is the control |
| Blinding by forged signature bursts | A burst only recommends distrust; it never distrusts automatically | Operators must review PB-08 cases |
| Prompt injection in captured text | Free text never feeds a rule or policy; no model is wired; summaries quote data as JSON | If a model is added, it must stay outside the decision path (a test enforces the import boundary) |
| Approval tampering or replay | Plan hash bound and recomputed at approval and again at execution; one decision per proposal (database unique key plus append-only triggers); policy version check; expiry | A database administrator can rewrite the whole store. See the evidence limits in `SECURITY.md` |
| Runaway automation | Single asset, one isolation per case, concurrency and hourly limits, circuit breaker, emergency stop in the database plus a kill-switch file, execution deadlines | None for this build: only the mock adapter exists |
| Controller crash mid-action | Leases, reconciliation against device state, idempotent keyed rules | A real adapter must report its state truthfully (see the integration contract) |
| Decoy compromise | Low-interaction, no execution, bounded reads, socket timeouts, internal network in compose, non-root, read-only filesystem, no capabilities | Python's HTTP parser is the attack surface. Keep decoys on isolated segments |
| Evidence tampering | SHA-256 per artifact, manifest hash, custody records, hash-chained audit, append-only triggers | Hashes show change, not who changed it; whole-database replacement is undetectable from inside. Back up the audit head out of band |

## Deployment assumptions

One control host for the API, worker, and SQLite file on local disk. Sensors on separate hosts or containers, each with only its own key. Operators reach the API over loopback or TLS. Container images run as uid 10001 with a read-only root filesystem, no capabilities, `no-new-privileges`, and memory and process limits. The worker has no network in compose.
