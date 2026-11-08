# UI/UX specification

Console: `apps/web` (Next.js 16, React 19, Tailwind CSS 4, Motion). Design tokens: `packages/ui/tokens.json`.

## Principles

1. **The operator's attention is the scarce resource.** Pending approvals, alerts, and the emergency stop are visible
   from every view.
2. **Show the evidence, not a summary of it.** Approvals show the exact payload and its digest; tasks show their
   nine-step trace; KPIs show "no data" instead of a guessed number.
3. **Glass, not chrome.** Translucent panels over a dark blueprint grid; colour carries status and risk only.

## Visual language

| Element | Rule |
|---|---|
| Background | `--cg-bg` with two soft radial glows (cyan, indigo) and a 44px blueprint grid |
| Panels | `.glass`: translucent gradient, 1px line, 16px backdrop blur, gradient edge highlight |
| Type | System sans for content; monospace for labels, ids, digests, callsigns; uppercase micro-labels at 0.14em tracking |
| Status colour | working cyan (pulsing), waiting amber, blocked/failed rose, completed green, idle slate, paused violet |
| Risk colour | low green, medium blue, high amber, critical rose |
| Motion | Panels rise in with a short stagger; working agents pulse; all of it is off under `prefers-reduced-motion` |

Contrast: body text `#e6edf5` and dimmed text `#9fb0c3` on `#04070c` both exceed WCAG AA for normal text.

## Global shell

- Left rail (top bar on small screens): brand, nine views, pending-approval count, brand line, policy version.
- Top bar: data source (`live api` / `offline snapshot`), auth mode (`dev · no sign-in` / `operator signed in` /
  `locked`), audit chain state and event count, snapshot time, **Emergency stop** (reason required).
- Banners: emergency stop engaged (rose), offline snapshot or API unreachable (amber).
- Keyboard: skip link, visible focus ring, `aria-current` on the active view, labelled form controls.

## Views

| View | Route | Content | Actions |
|---|---|---|---|
| Headquarters | `/` | KPI strip; glass-tower office map (12 rooms on 6 floors, agents as status dots by callsign); objectives with measured progress; alerts; mission progress bars | Rooms link to their department or facility |
| Agent Directory | `/agents` | Card per agent: callsign, department, status, objective, workload, success rate, reachable risk tier, reporting line, permissions, tools, memory scope, clearance, boundaries, success criteria; department filter with responsibilities and boundaries | Hire (validated JSON spec), edit objective, pause/resume, clone, retire |
| Mission Control | `/missions` | Mission header (department, priority, deadline, owner), deliverables, constraints, approval rules; tasks laid out by wave; each task expands to its governance trace | New mission (JSON with dependency graph), advance, run daily loop |
| Collaboration Floor | `/floor` | Threads of handoffs, assignments, escalations, reviews, reports, decisions, meeting summaries; filter by kind; decision records | none (read-only record) |
| Approval Desk | `/approvals` | Pending: requester, tool, task, why it stopped, exact text, full payload with digest, plans (critical), Risk & Compliance note, pipeline trace; history with every decision and receipt | Approve, Modify (edit parameters), Reject; reason (12+ characters) required for all |
| Knowledge Vault | `/vault` | Curation queue; goals, brand, customer context, policies, technical docs, prompts, workflows; past decisions; task memory | Approve or reject proposals with a reason |
| Simulation Chamber | `/simulations` | Scenario picker (pricing, campaign, incident, rollout) with editable assumptions; results as p10-p90 bands with median marker; recommendation, conditions, disclaimer | Run simulation (seeded), export a Markdown report |
| Briefing Room | `/briefing` | KPI strip; morning briefing (priorities with scores and reasons, department table, risks, recommended actions); end-of-day report (completed, waiting, medium-tier review, policy outcomes, audit, carry-over); security review with all control tests | Run today's loop |
| Audit Ledger | `/audit` | Latest events with sequence, time, actor, event, subject, tier, hash; chain status | none |

## States

- **Offline snapshot:** every view renders the committed demo snapshot; every action button is disabled with the
  reason in its tooltip.
- **Locked** (`OFFICE_ENV=production` without sign-in configured): read-only, actions refused by the proxy (503).
- **Signed out** (sign-in configured): only the operator sign-in form renders.
- **Halted:** rose banner; actions still render, but the API refuses everything except reject and release.
- **Empty:** dashed panels with a plain sentence ("Nothing is waiting for you.").
- **Errors:** inline `role="alert"` text under the control that failed, with the API's message.

## Responsive behavior

At widths under 1024px the rail becomes a horizontally scrolling view bar; the HQ map stacks rooms in one column;
wide tables scroll inside their panel. Checked at 390px wide in Chromium: no horizontal page scroll.
