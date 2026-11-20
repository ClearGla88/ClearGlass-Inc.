"""The ClearGlass Daily Operations Loop.

1. Context load: Avery reads company goals, Sable reads governance telemetry.
2. Every open mission runs through the gate (resuming any decided approvals).
3. A red-team probe: an agent attempts a payment it holds no grant for. The
   gate must refuse it; the loop reports whether it did.
4. Avery writes the executive briefing and the operations report.
5. The ledger is replayed and verified.

Every number in the reports is computed from this office's own records. The
office has no external data source connected, and the reports say so.
"""

from __future__ import annotations

from typing import Any

from .db import new_id, rows_to_dicts
from .models import ActionRequest, iso
from .office import Office

DATA_NOTE = (
    "Every figure here is computed from this office's own records (tasks, approvals, audit ledger). "
    "No external data source is connected, and no production connector is implemented: approved "
    "external actions run as recorded dry runs."
)


def _department_health(counts: dict[str, int]) -> str:
    if counts.get("blocked") or counts.get("failed"):
        return "red"
    if counts.get("waiting_for_approval"):
        return "amber"
    return "green"


def compute_status(office: Office) -> dict[str, Any]:
    conn = office.conn
    departments = []
    for dept in office.departments():
        counts = {r["status"]: r["n"] for r in conn.execute(
            """SELECT t.status, COUNT(*) AS n FROM tasks t JOIN missions m ON m.id = t.mission_id
               WHERE m.department_id = ? GROUP BY t.status""",
            (dept["id"],),
        ).fetchall()}
        agents = conn.execute("SELECT COUNT(*) FROM agents WHERE department_id = ?", (dept["id"],)).fetchone()[0]
        departments.append({"key": dept["key"], "name": dept["name"], "agents": agents, "tasks": counts,
                            "health": _department_health(counts)})
    missions = []
    for m in office.missions.list():
        missions.append({
            "id": m["id"], "code": m["code"], "title": m["title"], "status": m["status"], "mode": m["mode"],
            "tasks_completed": m["task_counts"].get("completed", 0), "tasks_total": m["tasks_total"],
        })
    pending = [
        {"id": a["id"], "risk": a["risk_level"], "agent": a["agent_name"], "summary": a["action_summary"],
         "mission": a["mission_code"], "expires_at": a["expires_at"]}
        for a in office.approvals.list("pending")
    ]
    blockers = rows_to_dicts(conn.execute(
        """SELECT t.title, t.block_reason, m.code AS mission, a.name AS agent FROM tasks t
           JOIN missions m ON m.id = t.mission_id JOIN agents a ON a.id = t.assigned_agent_id
           WHERE t.status IN ('blocked','failed') ORDER BY m.code, t.key"""
    ).fetchall())
    denials = conn.execute("SELECT COUNT(*) FROM audit_events WHERE action = 'governance.deny'").fetchone()[0]
    divergences = conn.execute("SELECT COUNT(*) FROM policy_shadow_divergences").fetchone()[0]
    unapproved_memory = conn.execute("SELECT COUNT(*) FROM memory_records WHERE approved = 0").fetchone()[0]
    open_incidents = conn.execute("SELECT COUNT(*) FROM incidents WHERE resolved_at IS NULL").fetchone()[0]
    verify = office.ledger.verify()

    risks = []
    for a in pending:
        if a["risk"] == "critical":
            risks.append(f"Critical approval pending: {a['summary']} ({a['mission']}).")
    for b in blockers:
        risks.append(f"{b['mission']} blocked: {b['title']} ({b['block_reason']}).")
    if open_incidents:
        risks.append(f"{open_incidents} open incident(s).")
    if not verify.ok:
        risks.append(f"Audit ledger failed verification at seq {verify.first_bad_seq}: {verify.reason}.")

    actions = [f"Decide {a['risk']} approval: {a['summary']}." for a in pending]
    if unapproved_memory:
        actions.append(f"Review {unapproved_memory} proposed memory record(s) in the Knowledge Vault.")
    if divergences:
        actions.append(f"Review the shadow-policy divergence report ({divergences} divergence(s)) before promoting.")
    for b in blockers:
        actions.append(f"Unblock or cancel {b['mission']}: {b['title']}.")

    return {
        "company": office.company().get("name"),
        "generated_at": iso(office.clock()),
        "departments": departments,
        "missions": missions,
        "pending_approvals": pending,
        "blockers": blockers,
        "top_risks": risks,
        "recommended_actions": actions,
        "governance": {
            "audit_events": verify.events,
            "ledger_verified": verify.ok,
            "ledger_head": verify.head_hash,
            "denials": denials,
            "shadow_divergences": divergences,
            "unapproved_memory_records": unapproved_memory,
            "open_incidents": open_incidents,
            "emergency_halted": office.emergency.is_halted(),
        },
        "data_note": DATA_NOTE,
    }


def render_briefing(status: dict[str, Any]) -> str:
    lines = [f"# Executive briefing: {status['company']}", "", f"Generated {status['generated_at']} by Avery.", ""]
    lines += ["## Department status", "", "| Department | Agents | Health | Tasks |", "|---|---|---|---|"]
    for d in status["departments"]:
        tasks = ", ".join(f"{k} {v}" for k, v in sorted(d["tasks"].items())) or "none"
        lines.append(f"| {d['name']} | {d['agents']} | {d['health']} | {tasks} |")
    lines += ["", "## Missions", "", "| Mission | Status | Progress |", "|---|---|---|"]
    for m in status["missions"]:
        lines.append(f"| {m['code']} {m['title']} | {m['status']} | {m['tasks_completed']}/{m['tasks_total']} |")
    lines += ["", "## Pending approvals", ""]
    lines += [f"- [{a['risk']}] {a['summary']} ({a['mission']})" for a in status["pending_approvals"]] or ["- None."]
    lines += ["", "## Top risks", ""]
    lines += [f"- {r}" for r in status["top_risks"]] or ["- None recorded."]
    lines += ["", "## Recommended actions", ""]
    lines += [f"- {a}" for a in status["recommended_actions"]] or ["- None."]
    g = status["governance"]
    lines += [
        "", "## Governance", "",
        f"- Audit events: {g['audit_events']} (chain verified: {'yes' if g['ledger_verified'] else 'NO'})",
        f"- Gate denials to date: {g['denials']}",
        f"- Shadow-policy divergences: {g['shadow_divergences']}",
        f"- Open incidents: {g['open_incidents']}",
        "", f"_{status['data_note']}_", "",
    ]
    return "\n".join(lines)


def render_operations_report(report: dict[str, Any]) -> str:
    lines = ["# Operations report", "", f"Generated {report['generated_at']} by Avery.", "",
             "## This run", ""]
    for key in ("tasks_executed", "approvals_requested", "denied", "failed"):
        lines.append(f"- {key.replace('_', ' ').capitalize()}: {report['run'][key]}")
    lines += ["", "## Red-team probe", "",
              f"- {report['red_team']['description']}",
              f"- Gate result: {report['red_team']['status']} ({report['red_team']['code']})",
              f"- Passed: {'yes' if report['red_team']['passed'] else 'NO'}", ""]
    lines += ["## Agent utilisation (tasks completed / assigned)", ""]
    lines += [f"- {u['agent']}: {u['completed']}/{u['assigned']}" for u in report["utilisation"]]
    lines += ["", "## Ledger", "",
              f"- Events this run: {report['ledger']['events_this_run']}",
              f"- Total events: {report['ledger']['total']} (verified: {'yes' if report['ledger']['verified'] else 'NO'})",
              "", f"_{DATA_NOTE}_", ""]
    return "\n".join(lines)


def _write_report(office: Office, report_type: str, content: dict[str, Any], markdown: str) -> dict[str, Any]:
    outcome = office.gate.submit(ActionRequest(
        agent_id=office.agent_id("Avery"), tool_key="report.write", action="write",
        payload={"report_type": report_type, "content": content, "markdown": markdown},
        correlation_id=new_id(),
    ))
    return outcome.to_dict()


def run_daily_ops(office: Office, *, triggered_by: str = "scheduler") -> dict[str, Any]:
    start_seq = office.ledger.head_seq()
    avery, sable = office.agent_id("Avery"), office.agent_id("Sable")

    context = [
        office.gate.submit(ActionRequest(agent_id=avery, tool_key="vault.search", action="read",
                                         payload={"query": "Company goals"})).to_dict(),
        office.gate.submit(ActionRequest(agent_id=sable, tool_key="telemetry.read", action="read",
                                         payload={"window": "24h"})).to_dict(),
    ]

    mission_results = []
    tally = {"tasks_executed": 0, "approvals_requested": 0, "denied": 0, "failed": 0}
    for m in office.missions.list():
        if m["status"] in ("completed", "cancelled", "failed", "paused"):
            continue
        result = office.runner.run(m["id"], triggered_by=triggered_by)
        for o in result.get("outcomes", []):
            key = {"executed": "tasks_executed", "waiting_for_approval": "approvals_requested",
                   "denied": "denied"}.get(o["status"], "failed")
            tally[key] += 1
        mission_results.append(result)

    probe = office.gate.submit(ActionRequest(
        agent_id=office.agent_id("Iris"), tool_key="payments.transfer", action="execute",
        payload={"summary": "Red-team probe: transfer funds to an unverified account",
                 "amount_cents": 250000, "destination": "unverified"},
        correlation_id=new_id(),
    ))
    red_team = {
        "description": "Iris (Growth) attempts a $2,500 payment transfer with no grant for it.",
        "status": probe.status, "code": probe.code, "passed": probe.status == "denied",
    }

    status = compute_status(office)
    briefing_write = _write_report(office, "executive_briefing", status, render_briefing(status))

    utilisation = [
        {"agent": r["name"], "assigned": r["assigned"], "completed": r["completed"] or 0}
        for r in office.conn.execute(
            """SELECT a.name, COUNT(t.id) AS assigned, SUM(t.status = 'completed') AS completed
               FROM agents a LEFT JOIN tasks t ON t.assigned_agent_id = a.id
               GROUP BY a.id ORDER BY a.name"""
        ).fetchall()
    ]
    verify = office.ledger.verify()
    ops = {
        "generated_at": iso(office.clock()),
        "run": tally,
        "red_team": red_team,
        "utilisation": utilisation,
        "missions": mission_results,
        "ledger": {"events_this_run": office.ledger.head_seq() - start_seq, "total": verify.events,
                   "verified": verify.ok},
    }
    ops_write = _write_report(office, "operations_report", ops, render_operations_report(ops))
    final = office.ledger.verify()
    return {
        "context": context,
        "missions": mission_results,
        "red_team": red_team,
        "briefing": status,
        "briefing_markdown": render_briefing(status),
        "operations_report": ops,
        "operations_markdown": render_operations_report(ops),
        "reports_written": [briefing_write["status"], ops_write["status"]],
        "ledger": final.to_dict(),
    }
