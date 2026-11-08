# Product vision and positioning

## One line

ClearGlass Agent Office is the operating headquarters of an AI-native company: agents do the work, and a human stays
in control of money, contracts, production, publishing, and sensitive data.

## The problem

A one-person or small firm can now get real work out of AI agents: drafts, research, code, analysis. The work stalls
at the same three points every time:

1. **Coordination.** Agents in separate chats do not hand work to each other, so the founder becomes the message bus.
2. **Trust.** An agent that can send email or deploy can also send the wrong email or deploy the wrong build. Most
   setups answer with "don't give it access", which caps the value, or "hope", which caps nothing.
3. **Proof.** When something goes wrong, there is no record of who decided what, on which inputs, under which rule.

## What the Agent Office does

- **Runs the company as departments.** 35 agents in 7 departments (Executive Suite, Engineering Lab, Cyber Operations
  Center, Growth & Marketing Studio, Revenue Floor, Intelligence Library, Simulation War Room), each with an identity,
  a reporting line, an objective, granted tools, permission levels, memory scopes, and written boundaries.
- **Runs work as missions.** A mission is a dependency graph of tasks. Independent tasks share a wave; outputs flow
  downstream; handoffs, escalations, and decisions are recorded on the Collaboration Floor.
- **Gates every action.** Nine steps: identity, permission, risk classification, policy evaluation, tool capability,
  human approval, execution, verification, audit. Low and medium tiers run; high and critical tiers stop at the
  Approval Desk; hard-blocked actions (editing the audit log, self-approval, surveillance, intrusion) never run.
- **Binds approvals to payloads.** The operator approves the SHA-256 digest of the exact action. Change one character
  and the approval no longer matches. "Modify" approves an edited payload, which is re-checked by policy first.
- **Proves what happened.** Every decision is sealed into a hash chain the database refuses to edit.
- **Stops on command.** One emergency stop pauses every agent, cancels every open approval, keeps all state, and opens
  an incident record.
- **Tests decisions first.** The Simulation Chamber runs seeded what-if models over stated assumptions, labelled as
  models, never as forecasts.

## Who it is for

1. **ClearGlass itself, first.** The office runs ClearGlass's own operations: engineering, content, pipeline research,
   and security review, every working day. Running it in-house is the proof of concept and the case study.
2. **Ontario owner-operated firms that want AI help without handing over the keys.** Clinics, law and accounting
   practices, and manufacturers, where a wrong outbound message or data export has regulatory weight. The office is
   the reference design ClearGlass's advisory practice implements and audits for them.

## Positioning

| | Chat assistants | Agent frameworks | ClearGlass Agent Office |
|---|---|---|---|
| Unit of work | A conversation | A script or graph | A mission inside a company structure |
| Who can act externally | The user, by copy-paste | Whatever the code allows | Only approved payloads, through registered connectors |
| Approval | None | Optional, per integration | Policy-as-code, every action, by tier |
| Evidence | Chat history | Logs, if configured | Hash-chained ledger, append-only at the database |
| Stop button | Close the tab | Kill the process | Emergency stop with incident record |

**Category:** governed agent operations. **Promise:** powerful enough to run the business, disciplined enough to be
trusted with it.

## What it is not

- Not a chatbot and not an autonomous company. A human approves anything that leaves the building.
- Not a surveillance tool. Monitoring individuals, intrusion, and harassment are hard-blocked in policy.
- Not a forecaster. Simulations restate the operator's assumptions as distributions.

## Honest limits today

- External connectors are dry-run: approved actions produce receipts, not deliveries. A reviewed live adapter per
  connector is required first (roadmap weeks 3 and 4).
- Agents use deterministic skills unless the Claude provider is enabled, and then Claude only rewrites drafts. A
  tool-using model loop that plans its own steps is roadmap work, and it will run inside the same gate.
- The runtime stores data in SQLite. The PostgreSQL schema is complete and tested; the adapter is week 2.
