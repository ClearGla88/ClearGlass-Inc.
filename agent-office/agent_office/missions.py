"""Missions as task DAGs, and the runner that drives them through the gate.

A mission is a directed acyclic graph of tasks. Each task names one agent, one
tool and one action. The runner schedules in waves: every task whose
dependencies are complete is submitted to the gate. A task the gate parks for
approval waits; the mission resumes when the approval is decided. State lives
in the database after every transition, so a stopped or crashed run resumes by
calling :meth:`MissionRunner.run` again (that is the checkpoint).

Payload references let a task use an earlier task's result:
``{"$task": "t3"}`` becomes that task's id, and ``{"$output": "t2.document_id"}``
becomes a field of its output.
"""

from __future__ import annotations

import sqlite3
from collections import deque
from typing import Any

from .approvals import ApprovalService
from .audit import AuditLedger
from .db import dumps, new_id, row_to_dict, rows_to_dicts, transaction
from .gate import GovernanceGate
from .identity import IdentityService
from .models import (
    ActionRequest,
    AgentStatus,
    ApprovalStatus,
    Clock,
    GateOutcome,
    GovernanceError,
    MissionStatus,
    NotFound,
    TaskStatus,
    iso,
    utcnow,
)

OPERATOR_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"active", "cancelled"},
    "active": {"paused", "cancelled"},
    "waiting_for_approval": {"paused", "cancelled"},
    "blocked": {"paused", "cancelled"},
    "paused": {"active", "cancelled"},
}
TERMINAL = {"completed", "failed", "cancelled"}


def validate_dag(tasks: list[dict[str, Any]]) -> list[list[str]]:
    """Return the tasks grouped into topological waves, or raise on a bad graph."""
    keys = [t["key"] for t in tasks]
    if len(keys) != len(set(keys)):
        raise GovernanceError("dag_invalid", "task keys must be unique", status_code=422)
    known = set(keys)
    indegree = {k: 0 for k in keys}
    children: dict[str, list[str]] = {k: [] for k in keys}
    for t in tasks:
        for dep in t.get("depends_on", []):
            if dep not in known:
                raise GovernanceError("dag_invalid", f"task {t['key']} depends on unknown task {dep}", status_code=422)
            if dep == t["key"]:
                raise GovernanceError("dag_invalid", f"task {t['key']} depends on itself", status_code=422)
            indegree[t["key"]] += 1
            children[dep].append(t["key"])
    waves: list[list[str]] = []
    frontier = deque(sorted(k for k, d in indegree.items() if d == 0))
    seen = 0
    while frontier:
        wave = list(frontier)
        frontier.clear()
        waves.append(wave)
        seen += len(wave)
        nxt: list[str] = []
        for k in wave:
            for c in children[k]:
                indegree[c] -= 1
                if indegree[c] == 0:
                    nxt.append(c)
        frontier.extend(sorted(nxt))
    if seen != len(keys):
        raise GovernanceError("dag_invalid", "task graph has a cycle", status_code=422)
    return waves


class MissionService:
    def __init__(self, conn: sqlite3.Connection, ledger: AuditLedger, company_id: str, clock: Clock = utcnow):
        self.conn = conn
        self.ledger = ledger
        self.company_id = company_id
        self.clock = clock

    def create(
        self,
        *,
        code: str,
        title: str,
        objective: str,
        department_key: str,
        tasks: list[dict[str, Any]],
        created_by: str,
        deliverables: list[str] | None = None,
        mode: str = "production",
        priority: int = 3,
        actor_type: str = "human",
    ) -> dict[str, Any]:
        validate_dag(tasks)
        dept = self.conn.execute(
            "SELECT id FROM departments WHERE company_id = ? AND key = ?", (self.company_id, department_key)
        ).fetchone()
        if dept is None:
            raise NotFound("department", department_key)
        agent_ids: dict[str, str] = {}
        for t in tasks:
            row = self.conn.execute("SELECT id FROM agents WHERE name = ?", (t["agent"],)).fetchone()
            if row is None:
                raise NotFound("agent", t["agent"])
            agent_ids[t["key"]] = row["id"]
        mission_id = new_id()
        now = iso(self.clock())
        with transaction(self.conn):
            self.conn.execute(
                """INSERT INTO missions (id, company_id, department_id, code, title, objective, deliverables,
                       mode, status, priority, created_by, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,'draft',?,?,?,?)""",
                (mission_id, self.company_id, dept["id"], code, title, objective, dumps(deliverables or []),
                 mode, priority, created_by, now, now),
            )
            for t in tasks:
                self.conn.execute(
                    """INSERT INTO tasks (id, mission_id, key, assigned_agent_id, title, depends_on, tool_key,
                           action, payload, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (new_id(), mission_id, t["key"], agent_ids[t["key"]], t["title"],
                     dumps(t.get("depends_on", [])), t["tool"], t["action"], dumps(t.get("payload", {})), now),
                )
            self.ledger.append(
                actor_type=actor_type, actor_id=created_by, action="mission.create", resource_type="mission",
                resource_id=mission_id, outcome="success", correlation_id=new_id(),
                payload={"code": code, "tasks": [t["key"] for t in tasks]}, metadata={"mode": mode},
            )
        return self.get(mission_id)

    def get(self, mission_id: str) -> dict[str, Any]:
        mission = row_to_dict(
            self.conn.execute(
                """SELECT m.*, d.key AS department_key, d.name AS department_name FROM missions m
                   LEFT JOIN departments d ON d.id = m.department_id WHERE m.id = ?""",
                (mission_id,),
            ).fetchone()
        )
        if mission is None:
            raise NotFound("mission", mission_id)
        return mission

    def by_code(self, code: str) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT id FROM missions WHERE company_id = ? AND code = ?", (self.company_id, code)
        ).fetchone()
        if row is None:
            raise NotFound("mission", code)
        return self.get(row["id"])

    def list(self) -> list[dict[str, Any]]:
        missions = rows_to_dicts(
            self.conn.execute(
                """SELECT m.*, d.key AS department_key, d.name AS department_name FROM missions m
                   LEFT JOIN departments d ON d.id = m.department_id ORDER BY m.priority, m.code"""
            ).fetchall()
        )
        for m in missions:
            counts = {r["status"]: r["n"] for r in self.conn.execute(
                "SELECT status, COUNT(*) AS n FROM tasks WHERE mission_id = ? GROUP BY status", (m["id"],)
            ).fetchall()}
            m["task_counts"] = counts
            m["tasks_total"] = sum(counts.values())
        return missions

    def tasks(self, mission_id: str) -> list[dict[str, Any]]:
        return rows_to_dicts(
            self.conn.execute(
                """SELECT t.*, a.name AS agent_name FROM tasks t
                   LEFT JOIN agents a ON a.id = t.assigned_agent_id
                   WHERE t.mission_id = ? ORDER BY t.created_at, t.key""",
                (mission_id,),
            ).fetchall()
        )

    def detail(self, mission_id: str) -> dict[str, Any]:
        mission = self.get(mission_id)
        tasks = self.tasks(mission_id)
        waves = validate_dag([{"key": t["key"], "depends_on": t["depends_on"]} for t in tasks])
        return {**mission, "tasks": tasks, "waves": waves}

    def set_status(self, mission_id: str, status: MissionStatus, *, actor_type: str, actor_id: str,
                   operator: bool = False, reason: str = "") -> dict[str, Any]:
        mission = self.get(mission_id)
        current = mission["status"]
        if current == status.value:
            return mission
        if operator and status.value not in OPERATOR_TRANSITIONS.get(current, set()):
            raise GovernanceError("invalid_transition", f"cannot move a {current} mission to {status.value}")
        if not operator and current in TERMINAL | {"paused"}:
            return mission
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE missions SET status = ?, updated_at = ? WHERE id = ?",
                (status.value, iso(self.clock()), mission_id),
            )
            if status == MissionStatus.CANCELLED:
                self.conn.execute(
                    """UPDATE tasks SET status = 'cancelled' WHERE mission_id = ?
                       AND status IN ('pending','waiting_for_approval','blocked','in_progress')""",
                    (mission_id,),
                )
                for ap in self.conn.execute(
                    "SELECT id FROM approvals WHERE mission_id = ? AND status = 'pending'", (mission_id,)
                ).fetchall():
                    self.conn.execute(
                        """UPDATE approvals SET status = 'cancelled', decider_type = 'system', decided_by = ?,
                               decided_at = ?, decision_reason = 'mission cancelled' WHERE id = ?""",
                        (actor_id, iso(self.clock()), ap["id"]),
                    )
            self.ledger.append(
                actor_type=actor_type, actor_id=actor_id, action="mission.transition", resource_type="mission",
                resource_id=mission_id, outcome="success", correlation_id=new_id(),
                metadata={"from": current, "to": status.value, "reason": reason},
            )
        return self.get(mission_id)


class MissionRunner:
    def __init__(
        self,
        *,
        conn: sqlite3.Connection,
        gate: GovernanceGate,
        missions: MissionService,
        approvals: ApprovalService,
        identity: IdentityService,
        clock: Clock = utcnow,
    ):
        self.conn = conn
        self.gate = gate
        self.missions = missions
        self.approvals = approvals
        self.identity = identity
        self.clock = clock

    def run(self, mission_id: str, *, triggered_by: str = "scheduler", max_waves: int = 25) -> dict[str, Any]:
        mission = self.missions.get(mission_id)
        if mission["status"] in TERMINAL or mission["status"] == "paused":
            return self._summary(mission_id)
        if mission["status"] == "draft":
            self.missions.set_status(mission_id, MissionStatus.ACTIVE, actor_type="system", actor_id=triggered_by)
        outcomes: list[dict[str, Any]] = []
        for _ in range(max_waves):
            if self.gate.emergency.is_halted():
                break
            progressed = self._revisit_waiting(mission_id, outcomes)
            progressed = self._run_ready(mission_id, outcomes) or progressed
            if not progressed:
                break
        self._refresh_status(mission_id)
        summary = self._summary(mission_id)
        summary["outcomes"] = outcomes
        return summary

    # ---------------------------------------------------------------- internals

    def _tasks(self, mission_id: str) -> list[dict[str, Any]]:
        return self.missions.tasks(mission_id)

    def _resolve(self, value: Any, by_key: dict[str, dict[str, Any]]) -> Any:
        if isinstance(value, dict):
            if set(value) == {"$task"}:
                ref = by_key.get(value["$task"])
                return ref["id"] if ref else None
            if set(value) == {"$output"}:
                key, _, field = str(value["$output"]).partition(".")
                ref = by_key.get(key)
                output = (ref or {}).get("actual_output") or {}
                return output.get(field) if isinstance(output, dict) else None
            return {k: self._resolve(v, by_key) for k, v in value.items()}
        if isinstance(value, list):
            return [self._resolve(v, by_key) for v in value]
        return value

    def _request(self, task: dict[str, Any], by_key: dict[str, dict[str, Any]],
                 approval_id: str | None = None) -> ActionRequest:
        return ActionRequest(
            agent_id=task["assigned_agent_id"],
            tool_key=task["tool_key"],
            action=task["action"],
            payload=self._resolve(task["payload"], by_key),
            mission_id=task["mission_id"],
            task_id=task["id"],
            correlation_id=new_id(),
            approval_id=approval_id,
        )

    def _run_ready(self, mission_id: str, outcomes: list[dict[str, Any]]) -> bool:
        tasks = self._tasks(mission_id)
        by_key = {t["key"]: t for t in tasks}
        done = {t["key"] for t in tasks if t["status"] == TaskStatus.COMPLETED}
        ready = [t for t in tasks if t["status"] == TaskStatus.PENDING and set(t["depends_on"]) <= done]
        for task in ready:
            if self.gate.emergency.is_halted():
                return bool(outcomes)
            self.identity.update_work_status(task["assigned_agent_id"], AgentStatus.WORKING)
            self.conn.execute(
                "UPDATE tasks SET status = 'in_progress', started_at = ? WHERE id = ?",
                (iso(self.clock()), task["id"]),
            )
            outcome = self.gate.submit(self._request(task, by_key))
            self._apply(task, outcome)
            outcomes.append({"task": task["key"], "title": task["title"], **outcome.to_dict()})
        return bool(ready)

    def _revisit_waiting(self, mission_id: str, outcomes: list[dict[str, Any]]) -> bool:
        progressed = False
        tasks = self._tasks(mission_id)
        by_key = {t["key"]: t for t in tasks}
        for task in tasks:
            if task["status"] != TaskStatus.WAITING_FOR_APPROVAL or not task["approval_id"]:
                continue
            approval = self.approvals.get(task["approval_id"])
            status = ApprovalStatus(approval["status"])
            if status in (ApprovalStatus.APPROVED, ApprovalStatus.MODIFIED) and not approval["consumed_at"]:
                outcome = self.gate.submit(self._request(task, by_key, approval_id=approval["id"]))
                self._apply(task, outcome)
                outcomes.append({"task": task["key"], "title": task["title"], **outcome.to_dict()})
                progressed = True
            elif status == ApprovalStatus.REJECTED:
                self._block(task, f"approval rejected: {approval['decision_reason']}")
                progressed = True
            elif status in (ApprovalStatus.EXPIRED, ApprovalStatus.CANCELLED):
                # Preserve the work; ask again on the next wave.
                self.conn.execute(
                    "UPDATE tasks SET status = 'pending', approval_id = NULL WHERE id = ?", (task["id"],)
                )
                progressed = True
        return progressed

    def _apply(self, task: dict[str, Any], outcome: GateOutcome) -> None:
        risk = outcome.risk_level.value if outcome.risk_level else None
        if outcome.status == "executed":
            self.conn.execute(
                """UPDATE tasks SET status = 'completed', actual_output = ?, risk_level = ?, completed_at = ?,
                       block_reason = NULL WHERE id = ?""",
                (dumps(outcome.result or {}), risk, iso(self.clock()), task["id"]),
            )
        elif outcome.status == "waiting_for_approval":
            self.conn.execute(
                "UPDATE tasks SET status = 'waiting_for_approval', approval_id = ?, risk_level = ? WHERE id = ?",
                (outcome.approval_id, risk, task["id"]),
            )
            self._message(task, "escalation", f"Approval requested ({risk}): {task['title']}",
                          {"approval_id": outcome.approval_id, "code": outcome.code})
        elif outcome.status == "denied":
            self._block(task, f"{outcome.code}: {outcome.message}", risk)
        else:
            self.conn.execute(
                "UPDATE tasks SET status = 'failed', block_reason = ?, risk_level = ? WHERE id = ?",
                (f"{outcome.code}: {outcome.message}", risk, task["id"]),
            )
            self._message(task, "escalation", f"Task failed: {task['title']}", {"code": outcome.code})

    def _block(self, task: dict[str, Any], reason: str, risk: str | None = None) -> None:
        self.conn.execute(
            "UPDATE tasks SET status = 'blocked', block_reason = ?, risk_level = COALESCE(?, risk_level) WHERE id = ?",
            (reason, risk, task["id"]),
        )
        self._message(task, "escalation", f"Blocked: {task['title']} ({reason})", {"reason": reason})

    def _message(self, task: dict[str, Any], kind: str, body: str, metadata: dict[str, Any]) -> None:
        agent = self.identity.get(task["assigned_agent_id"])
        self.conn.execute(
            """INSERT INTO messages (id, mission_id, task_id, sender_agent_id, recipient_agent_id, kind, body,
                   metadata, created_at) VALUES (?,?,?,?,?,?,?,?,?)""",
            (new_id(), task["mission_id"], task["id"], agent["id"], agent["reporting_to"], kind, body,
             dumps(metadata), iso(self.clock())),
        )

    def _refresh_status(self, mission_id: str) -> None:
        tasks = self._tasks(mission_id)
        statuses = {t["status"] for t in tasks}
        if tasks and statuses == {"completed"}:
            target = MissionStatus.COMPLETED
        elif "waiting_for_approval" in statuses:
            target = MissionStatus.WAITING_FOR_APPROVAL
        elif statuses & {"blocked", "failed"}:
            target = MissionStatus.BLOCKED
        else:
            target = MissionStatus.ACTIVE
        self.missions.set_status(mission_id, target, actor_type="system", actor_id="mission-runner")
        for agent_id in {t["assigned_agent_id"] for t in tasks}:
            mine = {t["status"] for t in tasks if t["assigned_agent_id"] == agent_id}
            if "waiting_for_approval" in mine:
                status = AgentStatus.WAITING_FOR_APPROVAL
            elif mine & {"blocked", "failed"}:
                status = AgentStatus.BLOCKED
            else:
                status = AgentStatus.IDLE
            self.identity.update_work_status(agent_id, status)

    def _summary(self, mission_id: str) -> dict[str, Any]:
        mission = self.missions.get(mission_id)
        tasks = self._tasks(mission_id)
        counts: dict[str, int] = {}
        for t in tasks:
            counts[t["status"]] = counts.get(t["status"], 0) + 1
        return {"mission_id": mission_id, "code": mission["code"], "status": mission["status"], "task_counts": counts}
