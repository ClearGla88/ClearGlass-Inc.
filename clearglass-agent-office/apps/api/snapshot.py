"""One read model for the console: everything the eight views render.

Secrets never appear here: tools carry their secret *reference*, and the vault
section reports only whether each reference is configured.
"""

from __future__ import annotations

from typing import Any

from agent_core.models import Decision, Mission, Permission, Report, RiskAssessment, Task, Workflow
from agent_core.office import Office
from agent_core.reports import compute_kpis, objective_progress
from simulation.sandbox import SCENARIOS


def _latest(office: Office, kind: str) -> dict[str, Any] | None:
    r = office.latest_report(kind)
    return r.to_dict() if r else None


def build_snapshot(office: Office, *, audit_limit: int = 150, message_limit: int = 250) -> dict[str, Any]:
    kpis = compute_kpis(office)
    agents = office.agents()
    tasks = office.store.list(Task)
    workflows = {w.id: w for w in office.store.list(Workflow)}
    missions = []
    for m in office.store.list(Mission):
        mine = [t for t in tasks if t.mission_id == m.id]
        wf = workflows.get(m.workflow_id)
        missions.append(
            {
                **m.to_dict(),
                "waves": wf.waves if wf else [],
                "workflow_status": wf.status if wf else None,
                "tasks": [t.to_dict() for t in mine],
            }
        )
    reports = sorted(office.store.list(Report), key=lambda r: r.generated_at, reverse=True)
    policy = office.policy
    halt = office.halt_state()
    chain = office.audit.verify()
    alerts = []
    if halt.get("halted"):
        alerts.append({"severity": "critical", "title": "Emergency stop engaged", "detail": halt.get("reason")})
    for a in office.desk.list("pending"):
        alerts.append({"severity": a.risk_tier, "title": f"Approval needed: {a.action_type}", "detail": a.id})
    for t in tasks:
        if t.status in ("failed", "blocked"):
            alerts.append(
                {
                    "severity": "high" if t.status == "failed" else "medium",
                    "title": f"Task {t.status}: {t.title}",
                    "detail": t.error,
                }
            )
    if not chain.ok:
        alerts.append({"severity": "critical", "title": "Audit chain broken", "detail": chain.reason})

    return {
        "generated_at": office.clock.iso(),
        "source": "live",
        "company": office.company().to_dict(),
        "objectives": objective_progress(office, kpis),
        "rooms": office.config.rooms,
        "departments": [d.to_dict() for d in office.departments()],
        "agents": [a.to_dict() for a in agents],
        "grants": [g.to_dict() for g in office.store.list(Permission) if g.constraints or g.expires_at or g.revoked_at],
        "shadow": office.shadow_report(limit=25),
        "missions": missions,
        "approvals": [a.to_dict() for a in office.desk.list()],
        "messages": [m.to_dict() for m in office.messages(limit=message_limit)],
        "decisions": [d.to_dict() for d in office.store.list(Decision, newest_first=True)],
        "memory": [r.to_dict() for r in office.memory.all()],
        "simulations": [s.to_dict() for s in office.simulations()],
        "scenarios": {
            k: {
                "description": s.description,
                "objective": s.objective,
                "direction": s.direction,
                "metrics": list(s.metrics),
                "example": s.example,
            }
            for k, s in SCENARIOS.items()
        },
        "reports": {
            "briefing": _latest(office, "briefing"),
            "eod": _latest(office, "eod"),
            "weekly": _latest(office, "weekly"),
            "security_review": _latest(office, "security_review"),
            "incident": _latest(office, "incident"),
            "index": [
                {"id": r.id, "kind": r.kind, "title": r.title, "period": r.period, "generated_at": r.generated_at}
                for r in reports
            ],
        },
        "risk_assessments": [r.to_dict() for r in office.store.list(RiskAssessment, newest_first=True)[:200]],
        "kpis": kpis,
        "alerts": alerts,
        "audit": {"verify": chain.to_dict(), "events": office.audit.events(limit=audit_limit)},
        "policy": {
            "version": policy.version,
            "tiers": policy.tiers,
            "actions": {
                k: {"domain": v.domain, "level": v.level, "tier": v.tier, "external": v.external}
                for k, v in policy.actions.items()
            },
            "hard_blocked": policy.hard_blocked,
            "approval": policy.approval,
        },
        "tools": [t.to_dict() for t in office.tool_list()],
        "vault": office.vault.describe(office.tool_list()),
        "emergency": halt,
    }
