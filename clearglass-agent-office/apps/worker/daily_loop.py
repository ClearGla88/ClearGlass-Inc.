"""ClearGlass Daily Operations Loop.

Every morning:
  1. Load company goals and active missions (create today's demo missions once).
  2. Collect status from each department.
  3. Chief of Staff produces the executive briefing (through the policy gate).
  4. Blockers, risks, and opportunities are part of that briefing.
  5. Chief of Staff assigns today's priority tasks to their agents.
  6. Agents complete approved internal work (missions run as task graphs).
  7. High-risk actions stop in the Approval Desk; Risk & Compliance annotates each one.
  8. Chief of Staff produces the end-of-day operations report.

Each step is an audited, policy-checked action. Running the loop twice on the
same database creates the demo missions only once.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_core.models import Mission, Report, Task
from agent_core.office import Office
from agent_core.reports import department_status, priority_queue
from policy_engine.engine import ActionRequest

CHIEF = "exec.chief-of-staff"
RISK = "exec.risk-compliance"


def _step(log: list[dict[str, Any]], n: int, name: str, **detail: Any) -> None:
    log.append({"step": n, "name": name, **detail})


def load_demo_missions(office: Office, path: Path, operator_id: str) -> list[Mission]:
    spec = json.loads(path.read_text(encoding="utf-8"))
    existing = {m.key for m in office.missions()}
    created = []
    for m in spec.get("missions", []):
        if m["key"] in existing:
            continue
        created.append(office.create_mission(m, created_by=operator_id))
        steps = " -> ".join(f"{t['key']} ({t['assignee']}: {t['action']['type']})" for t in m["tasks"])
        office.memory.add_approved(
            operator_id,
            "company",
            f"Workflow template: {m['title']}",
            f"{m['objective']}\nSteps: {steps}",
            str(path.name),
            "internal",
            ["workflow"],
        )
    return created


def run_daily_loop(office: Office, missions_path: Path | None = None) -> dict[str, Any]:
    operator_id = office.company().operator["id"]
    period = office.clock.now().date().isoformat()
    steps: list[dict[str, Any]] = []
    if office.halted:
        office.log("system.office", "system", "daily_loop.skipped", period, {"reason": "emergency stop engaged"})
        return {"period": period, "skipped": True, "reason": "emergency stop engaged", "steps": steps}
    office.log("system.office", "system", "daily_loop.started", period, {})

    # Agents start the day idle (paused and retired agents stay as they are).
    for agent in office.agents():
        if agent.status in ("completed", "failed"):
            office.set_agent_status(agent.id, "idle")

    # 1. Goals and missions
    created = load_demo_missions(office, missions_path, operator_id) if missions_path else []
    active = [m for m in office.missions() if m.status == "active"]
    _step(
        steps,
        1,
        "load_goals_and_missions",
        objectives=len(office.company().objectives),
        active_missions=len(active),
        created=[m.id for m in created],
    )

    # 2. Department status
    depts = department_status(office)
    _step(steps, 2, "collect_department_status", departments=len(depts))

    # 3-4. Executive briefing with blockers, risks, opportunities
    briefing = office.perform(
        ActionRequest(agent_id=CHIEF, action_type="briefing.compile", params={"period": period, "kind": "briefing"})
    )
    briefing_id = (briefing.output or {}).get("report_id")
    _step(steps, 3, "executive_briefing", status=briefing.status, report_id=briefing_id)
    if briefing.output:
        b = briefing.output["artifact"]
        _step(
            steps,
            4,
            "identify_blockers_risks_opportunities",
            risks=len(b["risks"]),
            opportunities=len(b["opportunities"]),
        )
        office.post_message(
            sender=CHIEF,
            recipient="all",
            kind="meeting_summary",
            subject=f"Morning stand-up {period}",
            body=f"{len(active)} active missions, {len(b['priorities'])} priority tasks, "
            f"{len(b['risks'])} open risks. Briefing {briefing_id}.",
            thread_id=f"standup-{period}",
            refs=[briefing_id] if briefing_id else [],
        )

    # 5. Assign today's priority tasks
    assigned = 0
    for row in priority_queue(office):
        if not row["ready"]:
            continue
        office.perform(
            ActionRequest(
                agent_id=CHIEF,
                action_type="message.internal",
                params={
                    "to": row["assignee"],
                    "kind": "assignment",
                    "subject": f"Today: {row['title']}",
                    "body": f"Priority score {row['score']} ({', '.join(row['why'])}).",
                    "thread_id": f"standup-{period}",
                },
            )
        )
        assigned += 1
    _step(steps, 5, "assign_priority_tasks", assigned=assigned)

    # 6. Run missions, highest priority first
    runs = {}
    for mission in sorted(active, key=lambda m: (m.priority, m.deadline or "9999", m.id)):
        runs[mission.id] = office.run_mission(mission.id)
    _step(steps, 6, "execute_approved_internal_work", missions=runs)

    # 7. Approval Desk: Risk & Compliance annotates every pending request
    pending = office.desk.list("pending")
    for approval in pending:
        notes = (
            f"Tier {approval.risk_tier}. Digest {approval.action_digest[:12]}. "
            f"{'; '.join(approval.reasons)}. Recommend the operator read the exact payload before deciding."
        )
        office.perform(
            ActionRequest(
                agent_id=RISK,
                action_type="message.internal",
                params={
                    "to": "operator",
                    "kind": "review",
                    "subject": f"Risk note on {approval.id}",
                    "body": notes,
                    "thread_id": approval.mission_id or approval.id,
                },
            )
        )
    _step(steps, 7, "approval_desk", pending=[a.id for a in pending])

    # 8. End-of-day report
    eod = office.perform(
        ActionRequest(agent_id=CHIEF, action_type="report.compile", params={"period": period, "kind": "eod"})
    )
    eod_id = (eod.output or {}).get("report_id")
    _step(steps, 8, "end_of_day_report", status=eod.status, report_id=eod_id)
    office.post_message(
        sender=CHIEF,
        recipient="operator",
        kind="meeting_summary",
        subject=f"Stand-down {period}",
        body=f"Report {eod_id}. {len(pending)} approval(s) waiting for you.",
        thread_id=f"standup-{period}",
        refs=[eod_id] if eod_id else [],
    )

    tasks = office.store.list(Task)
    chain = office.audit.verify()
    office.log(
        "system.office",
        "system",
        "daily_loop.finished",
        period,
        {"briefing_id": briefing_id, "eod_id": eod_id, "audit_ok": chain.ok},
    )
    involved = sorted({t.assignee for t in tasks} | {CHIEF, RISK})
    return {
        "period": period,
        "skipped": False,
        "steps": steps,
        "briefing_id": briefing_id,
        "eod_id": eod_id,
        "agents_involved": involved,
        "departments_involved": sorted({office.agent(a).department for a in involved if office.agent(a)}),
        "tasks": {s: sum(1 for t in tasks if t.status == s) for s in sorted({t.status for t in tasks})},
        "approvals_pending": [a.id for a in office.desk.list("pending")],
        "audit": chain.to_dict(),
        "reports": [r.id for r in office.store.list(Report)],
    }
