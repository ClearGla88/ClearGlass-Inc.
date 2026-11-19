# Operator runbook

Lab procedures for this build. Every command is run from `clearglass-active-defense/`. API calls use a bearer token from `secrets/<principal>.token`. Never paste a token into a ticket or chat.

```bash
API=http://127.0.0.1:8088
AUTH="Authorization: Bearer $(cat secrets/analyst-1.token)"
```

## 1. Start

```bash
python3 defense.py init-secrets config/defense.example.yaml
python3 defense.py check-config config/defense.example.yaml    # exit 2 = fix the named file first
python3 defense.py serve  config/defense.example.yaml &
python3 defense.py worker config/defense.example.yaml &
curl -s $API/ready
```

`/ready` reports the mode. Start in `observe`. Move to `recommend` only after a week of observe-mode cases has been reviewed and the rules tuned.

## 2. Daily triage

1. `curl -s -H "$AUTH" "$API/v1/cases?state=enriched"`: decoy and honeytoken cases. Read the identity status of each one. `ip:` subjects are unverified sources, and the only possible action is investigation.
2. `curl -s -H "$AUTH" "$API/v1/proposals?status=awaiting_approval"`: proposals for approvers.
3. Escalated (`escalated: 1`) and `review_overdue: 1` cases first.

## 3. Approving an isolation

The approver checks, in the proposal's `plan`:

- [ ] `target_asset_id` and `target_hostname` are the asset you expect. Confirm with the owner listed in the inventory.
- [ ] `evidence.signal_ids` include an endpoint signal and an independent decoy or honeytoken signal.
- [ ] `expected_impact` and `dependents` are acceptable now.
- [ ] `preserved_access_paths` include the management path you will use during the incident.
- [ ] All 12 checks in `decision.checks` passed.

Then submit the exact hash and policy version you reviewed:

```bash
curl -s -X POST -H "Authorization: Bearer $(cat secrets/approver-1.token)" -H "Content-Type: application/json" \
  "$API/v1/proposals/$PROPOSAL/decision" \
  -d '{"decision":"approved","plan_hash":"<plan_hash>","policy_version":"<policy_version>","reason":"<why>"}'
```

A 409 means the plan changed, expired, was already decided, or a limit or stop now applies. Read the proposal again before you do anything else.

## 4. Emergency stop

Use it when containment is misbehaving, the adapter is suspect, or the evidence is in doubt.

**Primary (API, admin):**

```bash
curl -s -X POST -H "Authorization: Bearer $(cat secrets/admin-1.token)" -H "Content-Type: application/json" \
  $API/v1/controls/emergency-stop -d '{"engaged":true,"reason":"<why>"}'
```

**Out-of-band (API down, or you cannot reach it):**

```bash
python3 defense.py kill-switch config/defense.example.yaml on
```

Effect:

- The worker stops claiming actions.
- Queued actions are cancelled (API path); their cases move to `failed`, or back to `verified` for a release.
- New proposals fail `no_emergency_stop`, and approvals and recovery requests are refused.
- **Existing containment stays in place.** An emergency stop never reconnects a host.
- An action already inside an adapter call finishes; it cannot be interrupted mid-call.

To clear it, engage `false` through the API and/or `kill-switch off`. Both must be clear for the worker to resume. Record the reason.

## 5. Circuit breaker

After `circuit_breaker_threshold` consecutive adapter failures the worker stops (`control.circuit_opened` in the audit log). Find the cause in `actions.last_error`. Fix the adapter, then:

```bash
curl -s -X POST -H "Authorization: Bearer $(cat secrets/admin-1.token)" -H "Content-Type: application/json" \
  $API/v1/controls/circuit-breaker/reset -d '{"reason":"<what was fixed>"}'
```

## 6. Partial or failed containment

`partially_completed` means some rules were applied. They are left in place on purpose, and management access was allowed first. Decide one of:

- Release what was applied: submit a recovery request (section 8).
- Contain by hand outside this system. Record what you did in the case.

`failed` means nothing is applied, or the action was blocked before execution (`action.blocked` names the reason). New corroborating evidence can produce a fresh proposal.

## 7. False positive

```bash
curl -s -X POST -H "$AUTH" -H "Content-Type: application/json" "$API/v1/cases/$CASE/false-positive" \
  -d '{"rationale":"<what it really was>"}'
```

This cancels pending isolation proposals and queued isolations, then closes the case. If the host is already contained, it stays contained until a release is approved. Send the rule ID to detection engineering.

## 8. Recovery checklist (PB-07)

Before you request recovery, record evidence for each criterion:

- [ ] `root_cause_identified`: cause found and written up.
- [ ] `host_remediated`: reimaged or remediated; change reference.
- [ ] `credentials_rotated`: every credential used on or exposed by the host.
- [ ] `monitoring_confirmed`: endpoint telemetry flowing and clean since remediation.

```bash
curl -s -X POST -H "$AUTH" -H "Content-Type: application/json" "$API/v1/cases/$CASE/recovery-request" \
  -d '{"criteria":{"root_cause_identified":"...","host_remediated":"...","credentials_rotated":"...","monitoring_confirmed":"..."},"reason":"..."}'
```

A **different** approver approves the release plan (section 3 applies). The worker removes only the rules tagged with this incident's key and verifies none remain. The case closes. Review deadlines only flag a case (`review_overdue`). Nothing reconnects a host on a timer.

## 9. Suspected sensor compromise (PB-08)

```bash
curl -s -X POST -H "Authorization: Bearer $(cat secrets/admin-1.token)" -H "Content-Type: application/json" \
  "$API/v1/sensors/sensor-tcp-01/trust" -d '{"trusted":false,"reason":"<why>"}'
```

Its events are still stored, flagged `sensor_trusted: false`, and no longer raise signals. Pending proposals and queued actions that relied on it are invalidated. Rebuild the sensor, rotate its key (`secrets/<id>.key`, then restart the API), and only then restore trust.

## 10. Evidence and audit

```bash
python3 defense.py verify-audit config/defense.example.yaml            # replays the hash chain
python3 defense.py verify-evidence config/defense.example.yaml $CASE   # recomputes artifact hashes
python3 defense.py retention config/defense.example.yaml               # purges content past retention_days
```

Copy the audit `head` hash somewhere outside this host (a ticket, a signed note) at the end of each day. That copy is what makes a wholesale rewrite of the database detectable.

## 11. Compose stack (lab)

```bash
python3 defense.py init-secrets deploy/compose.secrets.yaml
sudo chown 10001 secrets/*          # Linux: compose file secrets keep host ownership
docker compose up --build
```

The API publishes only `127.0.0.1:8088`. Decoys sit on an internal network until you publish them on a lab interface on purpose. The worker has no network. Status: compose validated with `docker compose config`; not built or run in the authoring session.
