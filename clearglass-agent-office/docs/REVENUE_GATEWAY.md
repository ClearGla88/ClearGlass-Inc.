# Revenue plan: plan-first payload and gateway controls

How the ClearGlassInc revenue validation plan is held in the Agent Office, what it is allowed to do, and which of the requested gateway controls exist today.

Verified 2026-11-13 against this tree. Nothing in the plan has run. No research has been done, no message drafted for a recipient, no record written, no money spent.

## State

| Item | State |
|---|---|
| Plan payload | Stored at `plans/revenue/clearglassinc-plan-first.json`, exactly as supplied |
| Contract check | Passes: `python office.py plan-check plans/revenue/clearglassinc-plan-first.json` |
| Approval | `PENDING` |
| Evidence | `INSUFFICIENT`, score 0, source register empty |
| Ready to start the first cycle | **No.** Five blockers, listed by the command above |
| Connectors (HubSpot, Smartlead, Instantly, ad platforms) | None exist. Every external tool in this system is a dry-run receipt |

The plan describes the product as smart-glass maintenance and retrofit packages. The rest of this repository describes ClearGlass Inc. as a cybersecurity and AI advisory. The payload is stored as supplied; which is correct is the owner's call.

## What blocks the first cycle

The command reports these, and exits with status 2 until they are cleared:

1. The plan's approval is `PENDING`.
2. Primary decision: which segment gets the first 90-day test.
3. Qualified-opportunity definition: what makes a lead worth human sales review.
4. Offer boundary: paid diagnostic, retrofit proposal, maintenance subscription, or all three.
5. Claim boundary: which outcomes ClearGlass may claim, and the evidence for each.

Items 2 to 5 are recorded in `plans/revenue/clearglassinc-plan-first.approvals.json`. That file is a record for the audit trail. It authorizes nothing: a status written in a file is not an approval.

## How the first cycle starts

Only the operator can start it, and only through an authenticated surface.

1. The decision owner approves the plan and decides the four items. Record each in the two JSON files (status, decision, who, date).
2. `python office.py plan-check plans/revenue/clearglassinc-plan-first.json` now exits 0.
3. The operator creates the mission in `plans/revenue/market-validation-mission.json` through `POST /missions` with the operator token. Creating it is the authorizing act, and it is audited as `mission.created` with the operator's id. There is no CLI command that creates a mission.
4. The mission runs in `plan_first` mode and produces the Market Validation Brief as nine internal drafts.

Nothing loads or runs the template automatically.

## What a plan-first mission can do

`config/policy.json`, `mission_modes.plan_first`, enforced at step 4 of the policy pipeline:

| Allowed | Refused |
|---|---|
| Actions at permission level `read` or `propose`: research on approved sources, analysis, scoring, pricing models, internal drafts, outreach drafts that are not sent, reports | Every external action: `outreach.send`, `email.send`, `content.publish`, deploys, exports, finance, contracts |
| `memory.write_task`, `message.internal` | Every other write: `data.update_internal` (pipeline records), `content.schedule`, `docs.update`, `workflow.create`, `code.commit_branch` |
| | Any request with `amount_cents` above zero |

A refused action is denied, not queued. There is no approval an operator could give to unlock it inside the mission. Sending, publishing, record writes and spending need a separate production-mode mission, where each one stops at the Approval Desk as usual.

The policy loader refuses a restricted mode that tries to widen itself: an exception cannot be an external or high-risk action, the built-in modes cannot be redefined, and a mode without a stated reason is rejected. A mission whose mode the current policy does not define is denied everything.

## What the contract check enforces

`packages/plan_contract/contract.py`, standard library only.

- **Shape.** Every field is named in the schema. An unknown field or a missing field is an error. Enumerated fields accept only their listed values.
- **Confidence cannot outrun evidence.** With an empty source register, overall confidence must be `INSUFFICIENT`, the evidence score 0, demand direction `UNKNOWN`, and each segment's evidence quality `INSUFFICIENT`. An option with no evidence cannot be rated above `LOW`. A market size cannot state a figure while its confidence is `INSUFFICIENT`. A competitor entry needs a source.
- **Verified means sourced.** A `VERIFIED` claim needs at least two source ids, each present in the source register, and a supporting excerpt. Anything else cannot be rated above `LOW`.
- **Every proposed action waits for a named person.** `approval_required` must be true, with an approver and a rollback plan. A plan that is not approved cannot propose spending.
- **Nothing ran early.** Until the plan is approved, spend to date must be `$0` and no tool may be listed as used.
- **No credentials.** A credential-shaped string anywhere in the payload fails the check. The finding names the rule, never the value.

## The six corrections

Each row says where the control lives and which test pins it. Tests named `test_revenue_gateway.py` were added with this change to hold existing behaviour in place.

| # | Correction asked for | State | Where | Pinned by |
|---|---|---|---|---|
| 1 | Approval timeout defaults to rejected; token expires; audit record kept; new approval needed to resume | **Enforced** | `ApprovalDesk._expire_if_due` marks an unanswered approval `expired` after `approval.ttl_hours` (72). An expired approval cannot be decided or executed. The request and expiry stay in the append-only ledger. A new request gets a new approval | `test_an_unanswered_approval_expires_and_never_executes` |
| 2 | Revalidate state after approval and immediately before execution | **Enforced for what the kernel models; not built for the rest** | `GovernedExecutor.perform` runs the whole policy gate again on the approved request before the tool runs: emergency stop, agent status, mission status and mode, grant revocation and expiry, spend cap, parameter allow-lists. The payload digest must still equal the approved digest | `test_a_grant_revoked_after_approval_stops_the_send`, `test_an_emergency_stop_after_approval_stops_the_send`, `test_a_value_outside_the_grant_allow_list_is_refused_even_when_approved_text_matches` |
| 3 | Idempotency key for every consequential action | **Enforced on the paths that exist** | An approval is consumed in `approval_executions` before the tool runs, so it runs at most once even under a crash or a concurrent call. Every workflow task attempt carries a key; a retry with the same key replays the stored result | `test_an_approval_runs_at_most_once`, `test_a_retried_request_with_the_same_key_replays_instead_of_sending_again` |
| 4 | Do not detect injection by searching for a string | **Structural controls enforced; one gap** | The marker list only raises a request to operator review. What limits a tool call is structure: unknown action types fail closed, a tool must declare the action, and a grant's allow-list fixes parameter values such as `channel`. Text in a payload is never read as an instruction | `test_instruction_like_text_in_a_low_risk_action_forces_review`, `test_scraped_text_cannot_add_a_recipient_channel_or_action` |
| 5 | Authenticate the approver server-side; an approval id is not authority | **Enforced** | The API builds the principal from the bearer token (`apps/api/security.py`). The desk accepts decisions only from a human with the operator role and audits every refused attempt. Presenting an approval id runs nothing unless that approval is in the `approved` state for that exact payload | `test_knowing_the_approval_id_does_not_authorize_anyone`, `tests/test_api.py` |
| 6 | No secrets in serialized state | **Enforced in the trail; one gap** | Credential-shaped strings are redacted from audit payloads and tool outputs and rejected from memory. Tools hold secret references, never values. The plan contract rejects a payload that carries one | `test_a_credential_in_request_text_is_redacted_from_the_record`, `test_plan_cannot_carry_a_credential` |

## Minimum gateway checks

| Check | State | Note |
|---|---|---|
| Schema validation | **Plan: built. Action parameters: not built** | The plan contract rejects unknown and missing fields. Action requests are not validated against a per-action schema, so an unexpected parameter is not refused at the gate |
| Authorization | **Built** | Row 5 above |
| Consent and suppression | **Not built** | The kernel has no contact, consent or suppression model. Nothing checks opt-out status before a send |
| Budget ledger with reservation | **Not built** | A grant carries a per-request spend cap. There is no ledger that reserves against a remaining approved budget across requests |
| Idempotency | **Built for approvals and workflow tasks** | Reconciling with a destination system before a retry is not built, because no live destination exists |
| Content policy | **Partly built** | Research output must cite a source or carry an `unverified` flag. Nothing checks outbound copy for unsubstantiated claims or deceptive urgency |
| Injection isolation | **Partly built** | Row 4 above. Scraped content is not yet passed as an opaque, field-validated object |
| Immutable audit log | **Built** | Hash-chained, append-only at the database level, with the policy version, digest, approver, decision, result and time on every record |

## Before any live connector

These are the gaps above, in the order they matter. None of them can cause harm today because every external tool returns a dry-run receipt. Each has to exist before a reviewed adapter for email, a CRM or an ad platform is registered.

1. Consent and suppression check immediately before every send.
2. Recipient-domain and parameter schemas per action, with unknown fields refused.
3. A budget ledger that reserves spend and refuses a request that would exceed what was approved.
4. Destination reconciliation before a retry, keyed by the idempotency key.
5. A content check for outbound copy against the plan's claim boundary.
6. Scanning action parameters for credentials at the gate, not only redacting them in the trail.
7. Operator sign-in that identifies a person (OIDC is on the roadmap); today the operator is whoever holds the operator token.

## Checks

```bash
cd clearglass-agent-office
python office.py plan-check plans/revenue/clearglassinc-plan-first.json   # exit 2: valid, not ready
python -m pytest tests/test_plan_first.py tests/test_revenue_gateway.py -q
```
