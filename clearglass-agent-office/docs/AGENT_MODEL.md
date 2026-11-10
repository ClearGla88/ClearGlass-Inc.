# Agent schema and permission model

## Agent record

Defined in `packages/agent_core/models.py::Agent`, configured in `config/org.json`, validated by
`packages/agent_core/config.py` at startup and on every hire or edit.

| Field | Meaning |
|---|---|
| `id`, `callsign`, `name` | Identity. `id` is `<dept>.<role>`; callsigns are `CG-<DEPT>-<NN>` |
| `department`, `room`, `reports_to` | Placement and reporting line. Every line must reach `operator` with no cycle |
| `objective`, `success_criteria` | What the agent is for and how it is judged |
| `skills` | Descriptive; used in the directory |
| `tools` | Granted tool ids. An agent can only act through a granted tool that declares the action |
| `permissions` | `{domain: level}` with levels `none < read < propose < write < execute` |
| `memory_scopes`, `clearance` | fnmatch scopes (`company`, `dept:eng`, `mission:*`) and a clearance ceiling |
| `boundaries` | Base + department + agent prohibitions, shown to the operator and to model prompts |
| `status` | `idle`, `working`, `waiting_for_approval`, `blocked`, `completed`, `failed`, `paused`, `retired` |
| `metrics` | `tasks_completed`, `tasks_failed`, `approvals_requested`, `policy_denials` |
| `version` | Bumped on every operator edit; before/after recorded in the audit ledger |

Every agent also receives the base grants: `memory: write`, `messaging: write`, and the memory and messaging tools.

## Permission model

An action is allowed to *run* only if all of these hold (steps 1, 2, 4, 5 of the pipeline):

1. The agent exists and is not paused or retired, the office is not halted, and the mission the request names
   (if any) exists and is `active`.
2. `permissions[action.domain] >= action.level` from the policy catalog, and the grant is not revoked, not
   expired, and the request is inside the grant's limits (below).
3. No hard block, department rule, sandbox or simulation rule, source rule, missing test evidence, or missing
   critical plan applies.
4. A tool in `agent.tools` declares the action and its `risk_ceiling` covers the action's tier.

And it then *executes without a human* only if its tier is low or medium and no injection marker was found (step 6).

`approve` is not a permission level. The config validator rejects it, the PostgreSQL schema's CHECK rejects it, and
the Approval Desk refuses any decision whose principal is not a human with an approver role.

### Grant limits

Each `{domain: level}` entry is also a `Permission` record that can carry limits. Limits only narrow a grant;
they never widen it. Set them in `config/org.json` (`grant_constraints`) or with `POST /agents/{id}/grants`.

| Limit | Meaning | The request is denied when |
|---|---|---|
| `constraints.spend_limit_cents` | Cap on `amount_cents` for actions in the domain | `amount_cents` is not a non-negative integer, or is above the cap |
| `constraints.payload_allowlist` | `{parameter: [allowed values]}` | the parameter is missing or empty, or any value (every item, for a list) is not on the list |
| `expires_at` | The grant ends at this time | the clock has reached it |
| `revoked_at`, `revoked_by` | Operator revocation, with a reason in the ledger (`grant.revoked`) | always, until the operator issues the grant again (`grant.issued`) |

Shipped limits: Social Media may publish only to `channel` linkedin or x; the Sales Strategist may send outreach
only on `channel` email. An agent edit that does not touch a domain keeps that domain's limits and expiry. A
propose-level grant never files an approval for a higher-level action: the request is denied at step 2.

### Domains and the actions in them

| Domain | Actions (level needed, tier) |
|---|---|
| research | `research.collect` (read, low), `research.summarize` (propose, low), `osint.public_research` (read, low; approved source + authorized scope), `leads.research` (read, low; approved source) |
| analysis | `analysis.run` (read, low), `leads.score` (propose, low), `pricing.model` (propose, low) |
| docs | `docs.draft` (propose, low), `docs.update` (write, medium), `proposal.draft` (propose, low) |
| reports | `briefing.compile`, `report.compile` (propose, low) |
| code / tests | `code.draft_patch`, `code.review`, `tests.plan` (propose, low); `code.commit_branch` (write, medium); `tests.run_sandbox` (execute, medium) |
| deploy | `deploy.plan` (propose, low); `deploy.staging` (execute, high); `deploy.production` (execute, critical; needs `test_evidence` naming a passed `tests.run_sandbox` task in the same mission) |
| content / social | `content.draft` (propose, low); `content.schedule` (write, medium); `content.publish` (execute, high) |
| outreach / email | `outreach.draft` (propose, low); `outreach.send`, `email.send` (execute, high) |
| data | `data.update_internal` (write, medium); `data.export` (execute, high); `data.delete` (execute, critical) |
| finance / contracts | `finance.purchase`, `finance.move_money`, `pricing.change_live`, `contract.sign` (execute, critical). The loader refuses a policy with a finance action below critical |
| security / secrets | `security.audit_config` (read, low); `security.incident_draft` (propose, low); `security.modify_config`, `secrets.access` (execute, critical) |
| workflow, memory, messaging, simulation | `workflow.create` (write, medium); `memory.write_task` (write, low); `memory.propose_long_term` (propose, low); `message.internal` (write, low); `simulation.run` (execute, low, sandbox only) |

Hard-blocked for every principal: `audit.modify`, `audit.delete`, `approval.self_approve`, `policy.self_modify`,
`surveillance.individual`, `intrusion.exploit`, `credentials.exfiltrate`, `harassment.contact`.

Department rules: the Simulation War Room may only run sandbox actions; Cyber Operations research requires an
`authorized_scope` parameter.

## Departments and agents

| Department | Agents (callsign) | Highest tier any member can reach |
|---|---|---|
| Executive Suite | Chief of Staff (EX-01), Strategy (EX-02), Operations (EX-03), Risk & Compliance (EX-04) | medium (Operations and Chief of Staff: workflows, internal updates; a bulk update escalates to high) |
| Engineering Lab | Software Architect (EN-01), Frontend (EN-02), Backend (EN-03), DevOps (EN-04), QA (EN-05), Code Review (EN-06) | critical (DevOps: production deploy, always approval-gated) |
| Cyber Operations Center | Threat Analyst (CY-01), Security Auditor (CY-02), Incident Response (CY-03), OSINT Research (CY-04), Compliance Monitor (CY-05) | low |
| Growth & Marketing Studio | Brand Strategist (GM-01), Content Writer (GM-02), SEO (GM-03), Social Media (GM-04), Video Concept (GM-05), Campaign Analyst (GM-06) | high (Social Media: publish) |
| Revenue Floor | Lead Research (RV-01), Sales Strategist (RV-02), Proposal Writer (RV-03), Customer Success (RV-04), Pricing Analyst (RV-05) | high (outreach and email sends) |
| Intelligence Library | Research (IL-01), Market Analyst (IL-02), Competitive Intelligence (IL-03), Knowledge Curator (IL-04) | medium (Knowledge Curator: document updates) |
| Simulation War Room | Scenario Designer (SW-01), Red Team (SW-02), Blue Team (SW-03), Business War-Gamer (SW-04), Outcome Analyst (SW-05) | low (sandbox only) |

Full grants per agent: `config/org.json`. The console's Agent Directory computes each agent's reachable tier from
its grants and tools.

## Memory model

| Layer | Written by | Read by | Lifetime |
|---|---|---|---|
| Short-term task memory | Any agent working the mission | Agents whose scopes match `mission:<id>` | 24 hours, then `expired` |
| Long-term company memory | Agents *propose*; the operator approves or rejects with a reason | Agents whose scopes and clearance match, approved records only | Until superseded |

Writes containing credential-shaped strings are rejected. The office starts with operator-approved records seeded
from reviewed config (objectives, brand guidelines, ICP, approved sources, policy summary, the drafting prompt).

## Audit trail per agent

Every evaluation (`policy.evaluated`), hold (`approval.requested`), start of execution (`action.intent`), execution
(`action.executed`), replay (`action.replayed`), grant change (`grant.issued`, `grant.revoked`), failure, and
operator change to an agent (`agent.hired`, `agent.updated`, `agent.pause`, ...) is a ledger event.
`GET /agents/{id}` returns the agent's recent events.
