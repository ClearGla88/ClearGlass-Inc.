# Revenue Floor: one governed sales path

From an authorized lead to a verified payment and a delivery handoff, inside the Agent Office. Verified 2026-11-20
against this tree.

CLEARGLASS: See Through Everything

**What it is.** Seven revenue desks run one sales path for one published offer. Agents record, qualify, draft and
reconcile. Every outbound step (an email, a proposal, an invoice) stops at the Approval Desk, bound to its exact payload.
After approval, the operator releases it as a ticket, and a person executes the ticket through the connector's own
interface (the mailbox, PayPal's invoice form). The person then records the provider's reference, which is checked
against the provider's record.

**What it is not.** It does not contact anyone by itself, hold provider credentials, guess at a lead, or report money it
cannot back with a provider record. On 2026-11-20 it has run no live sale: the first one waits on owner decisions
listed under [Blocked](#8-status-report).

## Contents

1. [Discovery: what exists](#1-discovery-what-exists)
2. [The workflow and its approval dependencies](#2-the-workflow-and-its-approval-dependencies)
3. [How it works](#3-how-it-works)
4. [Code map](#4-code-map)
5. [Tests](#5-tests)
6. [The console](#6-the-console)
7. [Operator runbook, deployment, rollback](#7-operator-runbook-deployment-rollback)
8. [Status report](#8-status-report)
9. [Sources](#9-sources)

## 1. Discovery: what exists

Checked 2026-11-19 from the build session: this repository, the claude.ai connector list, and read-only calls to the
connectors in the sales path. No message, invoice, booking or record was created during discovery.

### In this repository

| Asked about | Found |
|---|---|
| Simulator and agent UI | This Agent Office: governed kernel, FastAPI API, Next.js console with an office map. Canonical by owner decision (2026-11-08) |
| Sales database, CRM, pipeline | None. `clearglass-commerce/` is absent from this tree. The office had a "CRM Pipeline" tool for drafts and a fictional prospect list (`demo/prospects.sample.json`) |
| Lead sources | None holding leads. See the connector findings below |
| Auth, workers, deployment | Operator and viewer bearer tokens, fail-closed production mode, SQLite runtime, PostgreSQL schema, Docker files (not built here) |
| Offers, pricing, approved copy | The live site publishes six offers. The Security Quick-Audit (CAD 249.00, one time) is the only fixed-price one with a live Payment Link (`store.html`, `pricing.html`). Its exclusions, capacity, turnaround and terms are published nowhere |
| Fulfillment workflow | None in code. The Quick-Audit is an assessment, so it needs the client's written authorization before work starts |
| Prior revenue designs | `revenue-engine/DESIGN.md` (Stripe checkout, proposed, not approved) and the plan-first revenue plan in `plans/revenue/` (pending). Neither was used or changed |

### Connector capability matrix

Status is from the claude.ai connector list on 2026-11-19. "Can" is from each tool's own schema, read before any call.

| Capability | Existing implementation | Connector / tool | Permission and status | Missing dependency |
|---|---|---|---|---|
| Lead intake: inbound email | `crm.record_lead`, source `inbound_email`, thread id as reference | Gmail `search_threads`, `get_thread` (read) | Connected. The connected account is not the business mailbox: it holds no mail for the address the website publishes | Connect the business mailbox (Microsoft 365, or the Gmail that receives that address) |
| Lead intake: bookings | Source `calendly_booking`, scheduled-event URI as reference | Calendly `meetings-list_events` (read) | Connected; one active 30-minute event type | None. Routing forms need a Calendly Teams plan (the read was refused) |
| Pipeline of record | `Opportunity` records in the office | HubSpot | Not connected | None: the office is the pipeline. A CRM sync is proposed |
| Prospect research | `research.collect`: facts with their sources | None | The agent does not browse | Live-web fetch is proposed, not built |
| Qualification | `leads.qualify`, rubric in `config/revenue.json` | None | Internal | None |
| First email and proposal | `outreach.send`, `proposal.send`, released as tickets | Gmail `send_message`, executed by a person | Connected, wrong mailbox (above) | Business mailbox; counsel review of the consent rules |
| Meetings | Booking link in messages; `meeting_booked` event | Calendly scheduling link (`create_single_use_scheduling_link` also exists) | Connected | Set the booking link in Revenue settings |
| Invoice | `invoice.send` (critical), released as a ticket | PayPal `create_invoice`, `send_invoice`: interactive forms a person completes; `send_invoice` does not return the invoice id | Connected | Approved offer, including the sales-tax decision |
| Payment verification | `payment.reconcile` and record import | PayPal `list_invoices` (10 statuses), `list_transactions` (S, P, V, D; at most 31 days per call) | Connected; both reads worked | None for PayPal |
| Refunds and disputes | Imported as refund and dispute events | PayPal `list_transactions` (V), `list_disputes` | Connected | The connector has no refund tool: refunds happen in PayPal itself |
| Website checkout | Not integrated | Stripe | Needs reconnecting | Reconnect, then add an import path |
| Outlook | Not integrated | Microsoft 365 | Installed, connection incomplete | Finish connecting it in claude.ai |
| "Finance" | Money categories; no revenue recognition | Finance plugin warehouses (BigQuery refused the sign-in method); Crypto.com is market data only | Unavailable | Accounting rules, if revenue recognition is wanted |
| Counsel | Not integrated | General Legal (`start_deal`, `upload_document`) | Connected | Opening a matter is the owner's act |

**Finding.** No connected source held an existing inbound lead or open opportunity. The path therefore starts empty:
the first lead is one the owner records, from a referral, an inquiry at the business mailbox, or a booking. Nothing
was invented to fill it.

## 2. The workflow and its approval dependencies

```
lead (authorized source + consent record)
  -> qualified (rubric)                       Qualification Agent        internal, low
  -> offer matched (approved offer only)      Revenue Director           internal, medium
  -> first email drafted, content-checked     Outreach Agent             internal, low
  -> APPROVAL (high) -> release -> a person sends it -> receipt          [external boundary]
  -> client replies, books, or asks for a quote (recorded with its reference)
  -> proposal written from the approved offer Proposal Agent             internal, low
  -> proposal email drafted                   Outreach Agent             internal, low
  -> APPROVAL (high) -> release -> a person sends it -> receipt          [external boundary]
  -> acceptance (recorded by the operator, with the evidence)            [human act]
  -> APPROVAL (critical: change, rollback and verification plans)
  -> release -> a person creates and sends the PayPal invoice -> receipt [external boundary]
  -> invoice verified against PayPal's record
  -> payment imported from PayPal's record; paid when the total is covered
  -> handoff with the client's written authorization on record          Revenue and Delivery Agent
```

The Revenue Director's `advance` runs one step for one opportunity and stops. `cycle` does that for at most 25 open
opportunities. No agent can start another agent's work, change a grant, or approve anything.

| Dependency | Who | Where |
|---|---|---|
| Offer approval: exclusions, weekly capacity, turnaround, payment due days, sales tax, engagement-terms reference | Owner | Revenue Floor, "Approve with terms" |
| Sender identity: business name, mailing address, sending email, mailbox connector | Owner | Revenue Floor, "Sender identity" |
| Each email, proposal and invoice | Operator | Approval Desk, then "Release ticket" |
| Executing each ticket | A person, in the connector | Gmail or Outlook; PayPal's forms |
| Acceptance, client events, payment records | Operator, with references | Revenue Floor forms |
| Counsel review of consent rules, terms, authorization wording | Owner and counsel | Outside the system |

## 3. How it works

### Why a person executes each external step

1. PayPal's write tools are forms a person completes. No programmatic invoice path exists in the connected tools.
2. A live adapter in this office needs everything in the activation checklist (`docs/THREAT_MODEL.md`): a scoped
   credential in a secret store, a destination allow-list, provider-side idempotency, a rollback procedure, adapter
   tests, a security review, and the owner's sign-off. None exist, and no credential was requested or stored.
3. The connector platforms ask for confirmation on writes. A background job in this office must not route around that.

So every external tool stays dry-run. Releasing an approved action consumes the approval once. It produces the office's
dry-run receipt bound to the approved digest, and a ticket: the exact fields to enter, in order, and what to record.

### The team

| Desk | Agent | Grants | Tools | Can do |
|---|---|---|---|---|
| Revenue Director | `revenue.director` (new) | crm write | `crm.pipeline` | `crm.update_opportunity` (match an approved offer) |
| Opportunity Agent | `revenue.opportunity` (new) | crm write | `crm.intake` (new) | `crm.record_lead` |
| Research Agent | `revenue.lead-research` | unchanged | `research.sources` | `research.collect` |
| Qualification Agent | `revenue.qualification` (new) | analysis propose | `analytics.engine` | `leads.qualify` |
| Outreach Agent | `revenue.sales-strategist` | unchanged; outreach allow-list `channel: email` | `crm.pipeline`, `email.outbox` | `outreach.compose`, `outreach.send`, `proposal.send` |
| Proposal Agent | `revenue.proposal-writer` | unchanged | `docs.workspace` | `proposal.draft` |
| Revenue and Delivery Agent | `revenue.delivery` (new) | crm write, finance execute; allow-list `provider: paypal`, `currency: CAD` | `revenue.ledger` (new), `billing.desk` (new, dry-run) | `invoice.send`, `payment.reconcile`, `fulfillment.handoff` |

No revenue agent can reach `finance.move_money`, `finance.purchase`, or `pricing.change_live`: none holds the tool that
declares them. Tests pin each refusal.

### Checks before every send (request time and again at release)

| Check | Rule |
|---|---|
| Consent (CASL) | First contact needs express consent, or implied consent from an inquiry in the last six months or a purchase in the last two years (s.10(9)(a), s.10(10)(a), (e)), each with evidence and a date. A requested quote (s.6(6)(a)) and an invoice for accepted terms (s.6(6)(b)) are exempt from consent only. Limits sit a few days inside the statutory periods |
| Form (CASL s.6(2)) | Every message carries the business name, mailing address, contact email, and an unsubscribe line |
| Suppression | An address or @domain on the append-only list blocks every send; an opt-out adds it and cancels open approvals |
| Contact frequency | At most 3 messages per contact in 30 days, 48 hours apart unless the client replied (`config/revenue.json`) |
| Claim boundary | Every number comes from the approved offer, the settings, or the message's own dates and references. Every link is the website or booking link. No guarantees, false urgency, or unverifiable social proof |
| Payload schema | Recipients are exactly the opportunity's contact; invoice amount and currency equal the approved offer |
| Binding | The approved payload carries the record version, offer digest and settings digest. Any change makes the ticket stale |
| Credentials | A credential-shaped value in any external action's parameters is denied at the policy gate (step 4) |
| Kernel controls | Emergency stop, agent pause, revenue pause, grants, approval expiry (72 hours), one use per approval |

Free text from a lead (their stated need, a reply) is stored as data and never enters a message. Instruction-like text
in a lead's fields is refused; in the stated need it is quarantined and flagged.

### Money, kept apart

| Category | Counts | Never |
|---|---|---|
| Potential pipeline value | List price, with tax, of open matched opportunities without a proposal | A forecast |
| Proposed | Totals of proposals a person recorded as sent | Accepted |
| Accepted | Totals the operator recorded with the evidence of acceptance | Invoiced |
| Invoiced | Invoices confirmed on PayPal's own record, less cancellations | A payment |
| Payment pending | Confirmed invoices less payments received, per opportunity | Received |
| Pending at the processor | PayPal records with a pending status and no settlement | Received |
| Payments received | PayPal records with a paid or successful status | Revenue or profit |
| Reported, not verified | Invoices marked as paid by hand in PayPal (`MARKED_AS_PAID`) | Received |
| Refunds, disputes, fees, costs | From PayPal records; costs recorded with evidence | Hidden in another figure |
| Revenue recognition | Not available: no accounting rules exist here | Shown as a number |

A payment that does not match the opportunity's invoice is refused as "not a sale". So is money from one of
ClearGlass's own addresses (a transfer). The same provider record imported twice counts once: the database refuses the
duplicate. Rehearsal opportunities, which can only reach test addresses, never count.

## 4. Code map

| Path | What |
|---|---|
| `config/revenue.json` | Offer (published facts only), lead sources, consent bases, contact rules, content policy, rubric, connector inventory |
| `config/policy.json` (2026.11.19-1) | Eight actions: `crm.record_lead`, `crm.update_opportunity`, `leads.qualify`, `outreach.compose`, `proposal.send`, `invoice.send`, `payment.reconcile`, `fulfillment.handoff` |
| `config/tools.json`, `config/org.json` | Three tools, four agents |
| `packages/revenue_ops/rules.py` | Pure rules: stages, schemas, consent, content, qualification, PayPal status tables |
| `packages/revenue_ops/catalog.py` | Fail-closed loader for `config/revenue.json` |
| `packages/revenue_ops/compose.py` | Message templates (no model rewrites) and tickets |
| `packages/revenue_ops/skills.py` | The handlers agents run through the governed executor |
| `packages/revenue_ops/desk.py` | `RevenueDesk` (`Office.revenue`): steps, approvals, release, receipts, verification, money, metrics, desks |
| `packages/agent_core/` | Five record kinds; four append-only SQLite tables; new config agents provisioned into existing databases |
| `packages/policy_engine/engine.py` | Credential scan of external actions' parameters at step 4 |
| `apps/api/main.py`, `apps/api/snapshot.py` | Nineteen operator-gated `/revenue` routes; the snapshot's `revenue` section |
| `apps/web/src/app/revenue/page.tsx` | The Revenue Floor view |
| `infra/db/postgres/004_revenue_operations.sql` | PostgreSQL tables, append-only guards, money and decision constraints |

## 5. Tests

`tests/test_revenue_ops.py` (67 tests) and one PostgreSQL test in `tests/test_postgres_schema.py`.

| Area | Pinned |
|---|---|
| Permissions | Each revenue agent reaches only its own actions; only a human operator decides offers, releases, records receipts, acceptances and payments; a credential in an external action is denied at the gate |
| Approvals | A send waits for approval and releases once; a rejected payload cannot be requested again unchanged; changed settings make a ticket stale; a suppression, a pause or the emergency stop stops a release; an operator's edit is checked again at release |
| Duplicate events | A lead, a receipt reference, a client event, and a provider record each count once; the money and suppression tables refuse edits |
| Failures | Unknown sources, statuses and fields fail closed; lapsed consent, missing consent, the contact cap, and the claim boundary block sends; a mismatched invoice fails verification and counts nothing |
| Payment states | An invoice is not a payment; pending is not received; `MARKED_AS_PAID` is reported, never received; partial payments add up and overpayment is refused; unmatched payments and own-account transfers are not sales; refunds and disputes stay separate; rehearsal money never counts |
| End to end | Lead to delivery with a verified payment and an intact audit chain; every external action is a dry-run receipt |

```bash
cd clearglass-agent-office
python -m pytest tests/test_revenue_ops.py -q
OFFICE_TEST_PG_URL=postgresql://user:pass@localhost:5432/postgres python -m pytest tests/test_postgres_schema.py -q
```

## 6. The console

`/revenue` ("Revenue Floor" in the left rail).

- **Desks**: one card per role. Select one for the record behind it: the current task and business record, source
  evidence, the exact draft or proposed action, approval status, last governed action, last connector execution and
  its time, the external reference, errors and dependencies, the next step, and usage and cost. Usage and cost read
  "not measured" because nothing meters them. States come only from recorded work: idle, queued, working,
  awaiting approval, waiting for customer, waiting for payment, blocked, failed, paused. Nothing animates without it.
- **Pipeline and records**: opportunities by stage; each record's facts, consent, rubric, research, timeline and
  money, with the forms that apply to its stage.
- **External actions**: released tickets show the exact To, Subject and body to send, or the PayPal fields, with the
  receipt and verification forms.
- **Money and measured results**: the categories above, and metrics with their definition, window and denominator.
  A rate without a denominator reads "not available"; return on investment is never computed.
- **Readiness, offers, sender identity, suppressions, costs, connectors**.

Checked 2026-11-20 in Chromium against a live API at 1440 and 390 pixels wide, with no horizontal overflow on this view.
The console's offline snapshot shows the empty state: the candidate offer, the blockers, no opportunities, no money.

## 7. Operator runbook, deployment, rollback

### First-time setup

1. Approve the Quick-Audit with your terms, or reject it: Revenue Floor, "Offer catalog". Whether to charge sales tax
   is your or your accountant's decision.
2. Set the sender identity: business name, mailing address, the address you will send from, its connector, and the
   booking link if you want one in messages.
3. Have counsel review the consent rules (`config/revenue.json`), the engagement terms you referenced, and the wording
   of the client authorization.

### Each opportunity

1. **Record the lead**: source, a reference you can check later, consent basis, evidence and date.
2. **Run next step** until the Approval Desk shows the first email. Each click runs one step.
3. **Decide** it in the Approval Desk. Read the exact email there.
4. **Release ticket** on the Revenue Floor. The state is checked again at this moment.
5. **Send** exactly the ticket's To, Subject and body from your mailbox. In a Claude session: Gmail `send_message`
   with those fields.
6. **Record the receipt**: the message id and the time sent. Then **verify** it with the sent message's id, recipients,
   subject and time, copied from the mailbox.
7. **Record the client's reply**, booking or quote request with its message id or booking URI.
8. **Run next step** for the proposal, then decide, release, send, record and verify it as above.
9. **Record the acceptance** with the message or document where the client accepted.
10. **Run next step** for the invoice, decide it (critical: read the three plans), release it, then in PayPal:
    `create_invoice` with the ticket's fields, `send_invoice`, then `list_invoices` (status SENT) to find the invoice
    with the reference in its note. Record its id, then verify the status, total, currency and recipient.
11. **Import the payment** when PayPal shows it paid: the normalized fields plus the record as the connector returned it.
12. **Hand off** with the reference of the client's written authorization. Deliver the scope and nothing outside it.

If a released ticket was not sent, check the destination first (the sent folder, PayPal's invoice list), then
**Abandon** it with what you found. A new request can follow. If the client opts out, record it: the address is
suppressed and every open approval for it is cancelled.

### Controls

| Control | Where |
|---|---|
| Pause the Revenue Floor | Revenue Floor, with a reason. Facts and receipts can still be recorded |
| Pause one agent | Agent Directory |
| Emergency stop | Top bar: pauses every agent and cancels every open approval |

### Deployment

No new environment variables. On start, the office creates the revenue tables in SQLite and adds the four new agents
to an existing database (audited as `agent.provisioned`); agents already there are never changed. For PostgreSQL, apply
`infra/db/postgres/004_revenue_operations.sql` after `003`. Policy moved to `2026.11.19-1`.

```bash
cd clearglass-agent-office
ruff check . && ruff format --check . && python -m pytest -rs
cd apps/web && npm ci && npm run typecheck && npm run build
python office.py serve                                   # API
OFFICE_API_URL=http://127.0.0.1:8000 npm run start       # console, from apps/web
```

### Rollback

Revert the change. Every database change is additive: the old code ignores the revenue tables and records. Keep the
data unless the owner decides otherwise; money, suppression and decision rows are append-only on purpose. To remove
the PostgreSQL objects, export them first, then drop `external_action_receipts`, `external_actions`, `money_events`,
`suppressions`, `offer_decisions`, `opportunities`, and the function `offer_decision_by_human`.

## 8. Status report

| Item | State |
|---|---|
| Discovery: repository and connector inventory | Done, read-only (section 1) |
| Sales path from lead to handoff, seven desks, money categories, metrics | **Implemented and tested** (67 tests) |
| Consent, suppression, contact frequency, claim boundary, payload schemas, binding checks | **Implemented and tested**, for the revenue actions |
| Credential scan at the policy gate | **Implemented and tested**, for every external action |
| PostgreSQL schema 004 | **Implemented and tested** against PostgreSQL 16 |
| Console view | **Implemented**; typecheck and build pass; checked in Chromium |
| First live send | **Blocked**: offer approval and sender identity (owner) |
| Sending from the business mailbox | **Blocked**: the connected Gmail is not it; Microsoft 365 is not connected (owner) |
| Counsel review of consent rules, terms, authorization wording | **Blocked** [LEGAL REVIEW] (owner and counsel) |
| Verifying website (Stripe) payments | **Blocked**: Stripe needs reconnecting; no import path yet |
| Revenue recognition | **Not available**: no accounting rules |
| Live server-side adapters | **Proposed**, behind the activation checklist; not needed for the relayed path |
| Live-web research, CRM sync, more offers, budget ledger for paid acquisition, OIDC sign-in | **Proposed**, not built |
| Usage and cost metering | **Not built**; shown as not measured |

## 9. Sources

- *Canada's Anti-Spam Legislation*, S.C. 2010, c. 23, ss. 6(1), 6(2), 6(6), 10(9)(a), 10(10)(a) and (e), 11(2),
  11(3). Justice Laws Website, laws-lois.justice.gc.ca/eng/acts/E-1.6/, read 2026-11-19. Not legal advice; see the
  `consent_note` in `config/revenue.json`.
- PayPal, Calendly and Gmail tool schemas as exposed by the claude.ai connectors, read 2026-11-19.
- The Quick-Audit's published facts: `store.html` (`data-sku="quick-audit"`) and `pricing.html` in this repository,
  checked 2026-11-19.
