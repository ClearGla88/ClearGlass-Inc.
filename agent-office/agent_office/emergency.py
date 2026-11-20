"""Global emergency stop.

``stop`` pauses every agent, cancels every pending approval, halts the gate and
opens a critical incident, in one transaction. It is idempotent. ``resume``
needs two different human operators: the first call records a request, the
second (from someone else) restores each agent to the status it had before the
stop, unless that agent was changed in the meantime.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from .audit import AuditLedger
from .db import dumps, new_id, row_to_dict, transaction
from .models import Clock, GovernanceError, iso, utcnow


def record_incident(
    conn: sqlite3.Connection,
    clock: Clock,
    *,
    severity: str,
    title: str,
    triggered_by: str,
    reason: str,
    metadata: dict[str, Any] | None = None,
) -> str:
    incident_id = new_id()
    conn.execute(
        """INSERT INTO incidents (id, severity, title, triggered_by, reason, metadata, created_at)
           VALUES (?,?,?,?,?,?,?)""",
        (incident_id, severity, title, triggered_by, reason, dumps(metadata or {}), iso(clock())),
    )
    return incident_id


class EmergencyService:
    def __init__(self, conn: sqlite3.Connection, ledger: AuditLedger, approvals: Any, clock: Clock = utcnow):
        self.conn = conn
        self.ledger = ledger
        self.approvals = approvals
        self.clock = clock

    def _state(self) -> dict[str, Any]:
        state = row_to_dict(self.conn.execute("SELECT * FROM emergency_state WHERE id = 1").fetchone())
        assert state is not None
        return state

    def is_halted(self) -> bool:
        return bool(self._state()["halted"])

    def status(self) -> dict[str, Any]:
        state = self._state()
        incident = None
        if state["incident_id"]:
            incident = row_to_dict(
                self.conn.execute("SELECT * FROM incidents WHERE id = ?", (state["incident_id"],)).fetchone()
            )
        return {
            "halted": bool(state["halted"]),
            "incident": incident,
            "resume_requested_by": state["resume_requested_by"],
            "resume_requested_at": state["resume_requested_at"],
        }

    def stop(self, *, operator_id: str, reason: str) -> dict[str, Any]:
        reason = (reason or "").strip()
        if len(reason) < 8:
            raise GovernanceError("reason_required", "an emergency stop needs a reason", status_code=422)
        corr = new_id()
        with transaction(self.conn):
            state = self._state()
            if state["halted"]:
                self.ledger.append(
                    actor_type="human", actor_id=operator_id, action="emergency.stop.repeat",
                    resource_type="company", outcome="noop", correlation_id=corr,
                    metadata={"incident_id": state["incident_id"], "reason": reason},
                )
                return self.status()
            prior = {
                r["id"]: r["status"]
                for r in self.conn.execute("SELECT id, status FROM agents WHERE status <> 'retired'").fetchall()
            }
            self.conn.execute(
                "UPDATE agents SET status = 'paused', updated_at = ? WHERE status <> 'retired'",
                (iso(self.clock()),),
            )
            cancelled = self.approvals.cancel_pending(
                actor_id="emergency-stop", reason=f"emergency stop: {reason}", correlation_id=corr
            )
            incident_id = record_incident(
                self.conn, self.clock, severity="critical", title="Global emergency stop",
                triggered_by=operator_id, reason=reason,
                metadata={"prior_agent_status": prior, "approvals_cancelled": cancelled},
            )
            self.conn.execute(
                """UPDATE emergency_state SET halted = 1, incident_id = ?, resume_requested_by = NULL,
                       resume_requested_at = NULL, resume_reason = NULL WHERE id = 1""",
                (incident_id,),
            )
            self.ledger.append(
                actor_type="human", actor_id=operator_id, action="emergency.stop", resource_type="company",
                outcome="success", correlation_id=corr, payload={"reason": reason}, risk_level="critical",
                metadata={"incident_id": incident_id, "agents_paused": len(prior), "approvals_cancelled": cancelled},
            )
        return self.status()

    def resume(self, *, operator_id: str, reason: str) -> dict[str, Any]:
        reason = (reason or "").strip()
        if len(reason) < 8:
            raise GovernanceError("reason_required", "resuming needs a reason", status_code=422)
        corr = new_id()
        with transaction(self.conn):
            state = self._state()
            if not state["halted"]:
                raise GovernanceError("not_halted", "no emergency stop is in force")
            first = state["resume_requested_by"]
            if first is None:
                self.conn.execute(
                    """UPDATE emergency_state SET resume_requested_by = ?, resume_requested_at = ?,
                           resume_reason = ? WHERE id = 1""",
                    (operator_id, iso(self.clock()), reason),
                )
                self.ledger.append(
                    actor_type="human", actor_id=operator_id, action="emergency.resume.requested",
                    resource_type="company", outcome="pending", correlation_id=corr,
                    metadata={"incident_id": state["incident_id"], "reason": reason},
                )
                return {**self.status(), "awaiting_second_operator": True}
            if first == operator_id:
                raise GovernanceError(
                    "second_operator_required", "a different operator must confirm the resume", status_code=403
                )
            incident = row_to_dict(
                self.conn.execute("SELECT * FROM incidents WHERE id = ?", (state["incident_id"],)).fetchone()
            ) or {}
            prior = (incident.get("metadata") or {}).get("prior_agent_status", {})
            restored = 0
            for agent_id, status in prior.items():
                restored += self.conn.execute(
                    "UPDATE agents SET status = ?, updated_at = ? WHERE id = ? AND status = 'paused'",
                    (status, iso(self.clock()), agent_id),
                ).rowcount
            self.conn.execute(
                "UPDATE incidents SET resolved_at = ?, resolved_by = ? WHERE id = ?",
                (iso(self.clock()), dumps([first, operator_id]), state["incident_id"]),
            )
            self.conn.execute(
                """UPDATE emergency_state SET halted = 0, resume_requested_by = NULL,
                       resume_requested_at = NULL, resume_reason = NULL WHERE id = 1"""
            )
            self.ledger.append(
                actor_type="human", actor_id=operator_id, action="emergency.resume", resource_type="company",
                outcome="success", correlation_id=corr, risk_level="critical",
                metadata={"incident_id": state["incident_id"], "operators": [first, operator_id],
                          "agents_restored": restored, "reason": reason},
            )
        return {**self.status(), "awaiting_second_operator": False}
