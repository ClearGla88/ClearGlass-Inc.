"""Executive briefing, end-of-day report, weekly report, and KPIs.

Every number here is computed from stored records and the audit ledger. When
there is nothing to measure yet, the value is ``None`` and the UI says "no
data"; nothing is estimated or filled in.
"""

from __future__ import annotations

from collections import Counter
from datetime import timedelta
from statistics import median
from typing import TYPE_CHECKING, Any

from agent_core.models import (
    TERMINAL_TASK_STATUSES,
    Message,
    Mission,
    Report,
    RiskAssessment,
    Task,
)
from agent_core.util import parse_iso

if TYPE_CHECKING:
    from agent_core.office import Office


def _ratio(num: int, den: int) -> float | None:
    return round(num / den, 3) if den else None


def _latest_output(tasks: list[Task], action_type: str) -> dict[str, Any] | None:
    done = [t for t in tasks if t.action.get("type") == action_type and t.status == "completed" and t.output]
    done.sort(key=lambda t: t.completed_at or "")
    return done[-1].output if done else None


def compute_kpis(office: Office) -> dict[str, Any]:
    tasks = office.store.list(Task)
    by_status = Counter(t.status for t in tasks)
    agents = office.agents()
    completed = sum(a.metrics.get("tasks_completed", 0) for a in agents)
    failed = sum(a.metrics.get("tasks_failed", 0) for a in agents)
    approvals = office.desk.list()
    a_status = Counter(a.status for a in approvals)
    latencies = []
    for a in approvals:
        decided = [d for d in a.decisions if d["decision"] in ("approve", "reject", "modify")]
        if decided:
            delta = parse_iso(decided[0]["decided_at"]) - parse_iso(a.created_at)
            latencies.append(delta.total_seconds() / 60)
    risk = Counter(r.outcome for r in office.store.list(RiskAssessment))

    scored = _latest_output(tasks, "leads.score")
    collected = _latest_output(tasks, "leads.research")
    executed = office.audit.events(event_type="action.executed", limit=1000)
    unapproved_external = [e for e in executed if e["payload"].get("external") and not e["payload"].get("approval_id")]
    published = [e for e in executed if e["payload"].get("action_type") == "content.publish"]
    deploys = [
        e
        for e in executed
        if str(e["payload"].get("action_type", "")).startswith("deploy.")
        and e["payload"].get("action_type") != "deploy.plan"
    ]
    deploy_failures = [
        t
        for t in tasks
        if str(t.action.get("type", "")).startswith("deploy.")
        and t.action.get("type") != "deploy.plan"
        and t.status == "failed"
    ]

    sec = office.latest_report("security_review")
    sec_summary = (sec.metrics if sec else None) or None
    chain = office.audit.verify()
    return {
        "agents": {
            "total": len(agents),
            "active": sum(1 for a in agents if a.status not in ("paused", "retired")),
            "by_status": dict(Counter(a.status for a in agents)),
            "success_rate": _ratio(completed, completed + failed),
        },
        "tasks": {
            "total": len(tasks),
            "by_status": dict(by_status),
            "completion_rate": _ratio(by_status.get("completed", 0), len(tasks)),
        },
        "approvals": {
            "by_status": dict(a_status),
            "pending": a_status.get("pending", 0),
            "median_decision_minutes": round(median(latencies), 1) if latencies else None,
        },
        "policy": {"evaluations": sum(risk.values()), "by_outcome": dict(risk)},
        "pipeline": {
            "qualified_leads": len(scored["artifact"]["shortlist"]) if scored else None,
            "prospects_scored": len(scored["artifact"]["scored"]) if scored else None,
            "quarantined_inputs": len(collected["artifact"]["quarantined"]) if collected else None,
            "is_sample_data": bool(collected and collected["artifact"].get("is_sample")),
        },
        "content": {"published": len(published)},
        "deployments": {
            "executed": len(deploys),
            "failed": len(deploy_failures),
            "success_rate": _ratio(len(deploys), len(deploys) + len(deploy_failures)),
        },
        "risk": {
            "external_actions_without_approval": len(unapproved_external),
            "security_findings": sec_summary.get("by_severity") if sec_summary else None,
            "control_tests_passed": sec_summary.get("control_tests_passed") if sec_summary else None,
            "control_tests": sec_summary.get("control_tests") if sec_summary else None,
            "audit_chain_ok": chain.ok,
            "audit_events": chain.count,
        },
    }


def objective_progress(office: Office, kpis: dict[str, Any]) -> list[dict[str, Any]]:
    eods = office.store.list(Report, lambda r: r.kind == "eod")
    measures = {
        "qualified leads in pipeline": kpis["pipeline"]["qualified_leads"],
        "approved posts published": kpis["content"]["published"],
        "daily loop runs with a verified audit chain": sum(1 for r in eods if r.sections.get("audit", {}).get("ok")),
        "external actions executed without approval": kpis["risk"]["external_actions_without_approval"],
    }
    out = []
    for obj in office.company().objectives:
        value = measures.get(obj.get("metric"))
        out.append({**obj, "current": value, "measured": value is not None})
    return out


def _period(office: Office) -> str:
    return office.clock.now().date().isoformat()


def priority_queue(office: Office) -> list[dict[str, Any]]:
    today = office.clock.now().date()
    missions = {m.id: m for m in office.store.list(Mission)}
    tasks = office.store.list(Task)
    by_id = {t.id: t for t in tasks}
    rows = []
    for t in tasks:
        if t.status in TERMINAL_TASK_STATUSES:
            continue
        m = missions.get(t.mission_id)
        if m is None or m.status != "active":
            continue
        why, score = [], (6 - m.priority) * 20
        why.append(f"mission priority P{m.priority}")
        if m.deadline:
            days = (parse_iso(m.deadline).date() - today).days
            if days <= 1:
                score += 30
                why.append("due within a day")
            elif days <= 3:
                score += 15
                why.append(f"due in {days} days")
        ready = all(by_id[d].status == "completed" for d in t.depends_on if d in by_id)
        if ready and t.status == "pending":
            score += 10
            why.append("inputs ready")
        score += 5 * len(m.goal_ids)
        if m.goal_ids:
            why.append(f"serves {', '.join(m.goal_ids)}")
        rows.append(
            {
                "task_id": t.id,
                "title": t.title,
                "assignee": t.assignee,
                "mission": m.title,
                "status": t.status,
                "ready": ready,
                "score": score,
                "why": why,
            }
        )
    rows.sort(key=lambda r: (-r["score"], r["task_id"]))
    return rows


def department_status(office: Office) -> list[dict[str, Any]]:
    agents = office.agents()
    tasks = office.store.list(Task)
    out = []
    for d in office.departments():
        members = [a for a in agents if a.department == d.id]
        ids = {a.id for a in members}
        mine = [t for t in tasks if t.assignee in ids]
        out.append(
            {
                "id": d.id,
                "name": d.name,
                "head": d.head,
                "agents": len(members),
                "by_status": dict(Counter(a.status for a in members)),
                "open_tasks": sum(1 for t in mine if t.status not in TERMINAL_TASK_STATUSES),
                "completed_tasks": sum(1 for t in mine if t.status == "completed"),
                "waiting_approval": sum(1 for t in mine if t.status == "waiting_approval"),
                "blocked": sum(1 for t in mine if t.status in ("blocked", "failed")),
            }
        )
    return out


def mission_status(office: Office) -> list[dict[str, Any]]:
    tasks = office.store.list(Task)
    out = []
    for m in office.store.list(Mission):
        mine = [t for t in tasks if t.mission_id == m.id]
        done = sum(1 for t in mine if t.status == "completed")
        out.append(
            {
                "id": m.id,
                "title": m.title,
                "department": m.department,
                "owner": m.owner,
                "priority": m.priority,
                "deadline": m.deadline,
                "status": m.status,
                "progress": {"completed": done, "total": len(mine)},
                "waiting_approval": [t.title for t in mine if t.status == "waiting_approval"],
                "blocked": [t.title for t in mine if t.status in ("blocked", "failed")],
            }
        )
    return out


def risks_and_opportunities(office: Office, kpis: dict[str, Any]) -> tuple[list[dict], list[dict], list[str]]:
    risks: list[dict[str, Any]] = []
    opps: list[dict[str, Any]] = []
    actions: list[str] = []
    halt = office.halt_state()
    if halt.get("halted"):
        risks.append(
            {
                "severity": "critical",
                "title": "Emergency stop engaged",
                "detail": halt.get("reason", ""),
                "source": "office_state",
            }
        )
        actions.append("Review the incident record, then release the emergency stop with a reason.")
    if not kpis["risk"]["audit_chain_ok"]:
        risks.append(
            {
                "severity": "critical",
                "title": "Audit chain failed verification",
                "detail": "See /audit/verify",
                "source": "audit ledger",
            }
        )
    for a in office.desk.list("pending"):
        risks.append(
            {
                "severity": a.risk_tier,
                "title": f"Awaiting operator: {a.action_type}",
                "detail": f"{a.id} requested by {a.requested_by}",
                "source": f"approval:{a.id}",
            }
        )
        actions.append(f"Decide approval {a.id} ({a.action_type}) in the Approval Desk.")
    today = office.clock.now().date()
    for t in office.store.list(Task, lambda t: t.status in ("failed", "blocked")):
        risks.append(
            {
                "severity": "high" if t.status == "failed" else "medium",
                "title": f"Task {t.status}: {t.title}",
                "detail": t.error or "",
                "source": f"task:{t.id}",
            }
        )
    for m in office.store.list(Mission, lambda m: m.status == "active" and bool(m.deadline)):
        if parse_iso(m.deadline).date() < today:  # type: ignore[arg-type]
            risks.append(
                {
                    "severity": "medium",
                    "title": f"Mission past deadline: {m.title}",
                    "detail": f"due {m.deadline}",
                    "source": f"mission:{m.id}",
                }
            )
    if kpis["pipeline"]["quarantined_inputs"]:
        risks.append(
            {
                "severity": "medium",
                "title": "Untrusted input quarantined",
                "detail": f"{kpis['pipeline']['quarantined_inputs']} prospect record(s) held instruction-like text",
                "source": "leads.research",
            }
        )
    sec = office.latest_report("security_review")
    if sec:
        for f in sec.sections.get("findings", []):
            if f["severity"] in ("critical", "high"):
                risks.append(
                    {"severity": f["severity"], "title": f["title"], "detail": f["detail"], "source": f["source"]}
                )
    qualified = kpis["pipeline"]["qualified_leads"]
    if qualified:
        opps.append(
            {
                "title": f"{qualified} qualified prospects ready for outreach drafting",
                "owner": "revenue.sales-strategist",
                "source": "leads.score",
            }
        )
        actions.append("Assign the Sales Strategist to draft outreach for the shortlist (sending stays gated).")
    scheduled = [
        t
        for t in office.store.list(
            Task, lambda t: t.action.get("type") == "content.schedule" and t.status == "completed"
        )
    ]
    if scheduled:
        opps.append(
            {
                "title": "Content calendar is filled; approving the first post moves obj-authority",
                "owner": "growth.social-media",
                "source": "content.schedule",
            }
        )
    return risks, opps, actions


def compile_briefing(office: Office) -> dict[str, Any]:
    kpis = compute_kpis(office)
    risks, opps, actions = risks_and_opportunities(office, kpis)
    return {
        "period": _period(office),
        "objectives": objective_progress(office, kpis),
        "departments": department_status(office),
        "missions": mission_status(office),
        "priorities": priority_queue(office)[:12],
        "risks": risks,
        "opportunities": opps,
        "recommended_actions": actions or ["No action needed from the operator right now."],
        "kpis": kpis,
    }


def _on(period: str, ts: str | None) -> bool:
    return bool(ts) and ts[:10] == period  # type: ignore[index]


def compile_eod(office: Office) -> dict[str, Any]:
    period = _period(office)
    kpis = compute_kpis(office)
    tasks = office.store.list(Task)
    approvals = office.desk.list()
    executed = office.audit.events(event_type="action.executed", limit=1000)
    chain = office.audit.verify()
    messages = office.store.list(Message, lambda m: _on(period, m.created_at))
    risk = Counter(r.outcome for r in office.store.list(RiskAssessment, lambda r: _on(period, r.created_at)))
    return {
        "period": period,
        "completed": [
            {"title": t.title, "agent": t.assignee, "summary": (t.output or {}).get("summary")}
            for t in tasks
            if t.status == "completed" and _on(period, t.completed_at)
        ],
        "waiting_approval": [
            {"title": t.title, "agent": t.assignee, "approval_id": t.approval_id}
            for t in tasks
            if t.status == "waiting_approval"
        ],
        "failed_or_blocked": [
            {"title": t.title, "agent": t.assignee, "status": t.status, "error": t.error}
            for t in tasks
            if t.status in ("failed", "blocked")
        ],
        "approvals": {
            "created_today": sum(1 for a in approvals if _on(period, a.created_at)),
            "decided_today": sum(1 for a in approvals for d in a.decisions if _on(period, d["decided_at"])),
            "pending": [
                {"id": a.id, "action_type": a.action_type, "tier": a.risk_tier, "requested_by": a.requested_by}
                for a in approvals
                if a.status == "pending"
            ],
        },
        "policy_outcomes_today": dict(risk),
        "medium_tier_for_review": [
            {
                "seq": e["seq"],
                "actor": e["actor"],
                "action_type": e["payload"].get("action_type"),
                "summary": e["payload"].get("summary"),
            }
            for e in executed
            if e["risk_tier"] == "medium" and _on(period, e["ts"])
        ],
        "messages_today": dict(Counter(m.kind for m in messages)),
        "audit": chain.to_dict(),
        "carry_over": [r for r in priority_queue(office)],
        "kpis": kpis,
    }


def compile_weekly(office: Office) -> dict[str, Any]:
    period = _period(office)
    since = (office.clock.now() - timedelta(days=7)).date().isoformat()
    eods = office.store.list(Report, lambda r: r.kind == "eod" and r.period >= since)
    return {
        "period": f"{since}..{period}",
        "days_reported": len(eods),
        "daily": [
            {
                "period": r.period,
                "completed": len(r.sections.get("completed", [])),
                "pending_approvals": len(r.sections.get("approvals", {}).get("pending", [])),
                "audit_ok": r.sections.get("audit", {}).get("ok"),
            }
            for r in eods
        ],
        "kpis": compute_kpis(office),
    }
