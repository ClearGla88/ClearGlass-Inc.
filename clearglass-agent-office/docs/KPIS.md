# KPIs

Every KPI below is computed by `packages/agent_core/reports.py::compute_kpis` from stored records and the audit
ledger. When there is nothing to measure, the value is `null` and the console shows "no data". Nothing is estimated.

| Area | KPI | Definition | Target (operator-set) | Source |
|---|---|---|---|---|
| Agent performance | Agent success rate | completed / (completed + failed) tasks, across agents | >= 95% | `agents.metrics` |
| Agent performance | Policy denials per agent | Denied requests per agent per week | Trending to 0 for a stable agent | `agents.metrics.policy_denials` |
| Agent performance | Approvals requested per agent | Held actions per agent | Context-dependent; spikes need review | `agents.metrics.approvals_requested` |
| Task completion | Completion rate | completed / all tasks | >= 85% per week | `tasks.status` |
| Task completion | Blocked or failed tasks | Count at end of day | 0 carried more than one day | end-of-day report |
| Task completion | Operator decision time | Median minutes from approval request to first decision | < 240 | `approval_decisions` |
| Revenue pipeline | Qualified leads | Size of the latest scored shortlist | 20 by 2026-12-31 (`obj-pipeline`) | `leads.score` output |
| Revenue pipeline | Quarantined inputs | Prospect records holding instruction-like text | Reported, never acted on | `leads.research` output |
| Revenue pipeline | Approved posts published | Executed `content.publish` actions | 24 by 2026-12-31 (`obj-authority`) | audit ledger |
| Deployment reliability | Deploy success rate | executed deploys / (executed + failed) | >= 99% once deploys start | audit ledger, tasks |
| Deployment reliability | Deploys with a rollback plan | critical deploy approvals carrying all three plans | 100% (enforced by policy and schema) | `approvals` |
| Risk reduction | External actions without approval | Executed external actions with no approval id | 0, always (`obj-zero-unapproved`) | audit ledger |
| Risk reduction | Control tests passing | Negative control tests in the latest security review | 18/18 | security review report |
| Risk reduction | Open critical and high findings | From the latest security review | 0 | security review report |
| Risk reduction | Audit chain integrity | `verify()` over the full ledger | Always verified | `/audit/verify`, `/ready` |
| Platform | Daily loop runs with a verified chain | End-of-day reports whose audit check passed | 30 by 2026-12-31 (`obj-platform`) | `reports` |

Targets marked operator-set live in `config/company.json` and are the operator's to change. The demo snapshot's
pipeline numbers come from a fictional sample list and are labelled as sample data in the console.
