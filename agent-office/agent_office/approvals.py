"""Approval Desk service.

An approval is bound to one exact request through ``request_hash``. It is
decided once, by a named decider with a written reason, and it can authorise
exactly one execution. High and critical approvals can only be decided by a
human; an agent may never decide its own request.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import Any

from .audit import AuditLedger
from .db import dumps, new_id, row_to_dict, rows_to_dicts, transaction
from .models import (
    APPROVAL_REQUIRED_RISKS,
    EXECUTABLE_APPROVAL_STATUSES,
    ActionRequest,
    ApprovalStatus,
    Clock,
    GovernanceError,
    NotFound,
    RiskLevel,
    iso,
    utcnow,
)

DEFAULT_TTL = {
    RiskLevel.LOW: timedelta(days=7),
    RiskLevel.MEDIUM: timedelta(days=3),
    RiskLevel.HIGH: timedelta(hours=48),
    RiskLevel.CRITICAL: timedelta(hours=24),
}
MIN_REASON_LENGTH = 8


class ApprovalService:
    def __init__(self, conn: sqlite3.Connection, ledger: AuditLedger, clock: Clock = utcnow):
        self.conn = conn
        self.ledger = ledger
        self.clock = clock

    def get(self, approval_id: str) -> dict[str, Any]:
        self._expire_stale()
        row = row_to_dict(
            self.conn.execute(
                """SELECT ap.*, a.name AS agent_name, m.code AS mission_code, m.title AS mission_title
                   FROM approvals ap
                   JOIN agents a ON a.id = ap.agent_id
                   LEFT JOIN missions m ON m.id = ap.mission_id
                   WHERE ap.id = ?""",
                (approval_id,),
            ).fetchone()
        )
        if row is None:
            raise NotFound("approval", approval_id)
        return row

    def list(self, status: str | None = None) -> list[dict[str, Any]]:
        self._expire_stale()
        sql = """SELECT ap.*, a.name AS agent_name, m.code AS mission_code, m.title AS mission_title
                 FROM approvals ap JOIN agents a ON a.id = ap.agent_id
                 LEFT JOIN missions m ON m.id = ap.mission_id"""
        params: list[Any] = []
        if status:
            sql += " WHERE ap.status = ?"
            params.append(status)
        sql += """ ORDER BY CASE ap.risk_level WHEN 'critical' THEN 0 WHEN 'high' THEN 1
                   WHEN 'medium' THEN 2 ELSE 3 END, ap.requested_at"""
        return rows_to_dicts(self.conn.execute(sql, params).fetchall())

    def create_or_reuse(
        self,
        request: ActionRequest,
        *,
        risk: RiskLevel,
        action_summary: str,
        policy_rationale: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        """File an approval for ``request``. A pending one for the same request is reused."""
        request_hash = request.request_hash()
        existing = self.conn.execute(
            "SELECT id FROM approvals WHERE request_hash = ? AND status = 'pending'", (request_hash,)
        ).fetchone()
        if existing:
            return self.get(existing["id"])
        approval_id = new_id()
        now = self.clock()
        with transaction(self.conn):
            self.conn.execute(
                """INSERT INTO approvals (id, mission_id, task_id, agent_id, tool_key, action,
                       action_summary, risk_level, request_payload, request_hash, policy_rationale,
                       status, requested_at, expires_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,'pending',?,?)""",
                (
                    approval_id,
                    request.mission_id,
                    request.task_id,
                    request.agent_id,
                    request.tool_key,
                    request.action,
                    action_summary,
                    risk.value,
                    dumps(request.payload),
                    request_hash,
                    policy_rationale,
                    iso(now),
                    iso(now + DEFAULT_TTL[risk]),
                ),
            )
            self.ledger.append(
                actor_type="agent",
                actor_id=request.agent_id,
                action="approval.requested",
                resource_type="approval",
                resource_id=approval_id,
                outcome="pending",
                correlation_id=correlation_id,
                payload=request.payload,
                risk_level=risk.value,
                approval_id=approval_id,
                metadata={"tool_key": request.tool_key, "action": request.action, "summary": action_summary},
            )
        return self.get(approval_id)

    def decide(
        self,
        approval_id: str,
        *,
        decision: str,
        decider_id: str,
        decider_type: str,
        reason: str,
        modified_payload: dict[str, Any] | None = None,
        decider_agent_can_approve: bool = False,
    ) -> dict[str, Any]:
        approval = self.get(approval_id)
        reason = (reason or "").strip()
        if len(reason) < MIN_REASON_LENGTH:
            raise GovernanceError(
                "reason_required", f"a decision needs a written reason of at least {MIN_REASON_LENGTH} characters",
                status_code=422,
            )
        if decision not in ("approve", "reject", "modify"):
            raise GovernanceError("invalid_decision", "decision must be approve, reject or modify", status_code=422)
        if ApprovalStatus(approval["status"]) != ApprovalStatus.PENDING:
            raise GovernanceError("approval_not_pending", f"approval is {approval['status']}")
        risk = RiskLevel(approval["risk_level"])
        if decider_type != "human":
            if risk in APPROVAL_REQUIRED_RISKS:
                raise GovernanceError("human_required", f"{risk.value} approvals require a human", status_code=403)
            if decider_id == approval["agent_id"]:
                raise GovernanceError("self_approval", "an agent cannot decide its own request", status_code=403)
            if not decider_agent_can_approve:
                raise GovernanceError("permission_denied", "agent lacks an approve grant", status_code=403)
        if decision == "modify":
            if not isinstance(modified_payload, dict):
                raise GovernanceError("modified_payload_required", "modify needs a payload", status_code=422)
            status = ApprovalStatus.MODIFIED
        else:
            status = ApprovalStatus.APPROVED if decision == "approve" else ApprovalStatus.REJECTED
        with transaction(self.conn):
            self.conn.execute(
                """UPDATE approvals SET status = ?, decided_by = ?, decider_type = ?, decided_at = ?,
                       decision_reason = ?, modified_payload = ?
                   WHERE id = ? AND status = 'pending'""",
                (
                    status.value,
                    decider_id,
                    decider_type,
                    iso(self.clock()),
                    reason,
                    dumps(modified_payload) if modified_payload is not None else None,
                    approval_id,
                ),
            )
            self.ledger.append(
                actor_type=decider_type,
                actor_id=decider_id,
                action="approval.decided",
                resource_type="approval",
                resource_id=approval_id,
                outcome=status.value,
                correlation_id=new_id(),
                payload=modified_payload if modified_payload is not None else {},
                risk_level=risk.value,
                approval_id=approval_id,
                metadata={"reason": reason, "decision": decision},
            )
        return self.get(approval_id)

    def executable(self, approval_id: str, request: ActionRequest) -> dict[str, Any]:
        """Return the approval if it authorises ``request`` right now, else raise."""
        approval = self.get(approval_id)
        if approval["request_hash"] != request.request_hash():
            raise GovernanceError("approval_request_mismatch", "approval is bound to a different request", status_code=403)
        status = ApprovalStatus(approval["status"])
        if status not in EXECUTABLE_APPROVAL_STATUSES:
            raise GovernanceError("approval_not_granted", f"approval is {status.value}", status_code=403)
        if approval["consumed_at"]:
            raise GovernanceError("approval_consumed", "approval already authorised an execution", status_code=403)
        if RiskLevel(approval["risk_level"]) in APPROVAL_REQUIRED_RISKS and approval["decider_type"] != "human":
            raise GovernanceError("human_required", "approval was not decided by a human", status_code=403)
        return approval

    def consume(self, approval_id: str, correlation_id: str) -> None:
        """Mark single use. A second consumption is refused by the database trigger."""
        try:
            with transaction(self.conn):
                updated = self.conn.execute(
                    "UPDATE approvals SET consumed_at = ? WHERE id = ? AND consumed_at IS NULL",
                    (iso(self.clock()), approval_id),
                ).rowcount
                if updated != 1:
                    raise GovernanceError("approval_consumed", "approval already authorised an execution")
        except sqlite3.IntegrityError as exc:
            raise GovernanceError("approval_consumed", "approval already authorised an execution") from exc

    def cancel_pending(self, *, actor_id: str, reason: str, correlation_id: str) -> int:
        pending = self.conn.execute("SELECT id FROM approvals WHERE status = 'pending'").fetchall()
        with transaction(self.conn):
            for row in pending:
                self.conn.execute(
                    """UPDATE approvals SET status = 'cancelled', decided_by = ?, decider_type = 'system',
                           decided_at = ?, decision_reason = ? WHERE id = ? AND status = 'pending'""",
                    (actor_id, iso(self.clock()), reason, row["id"]),
                )
                self.ledger.append(
                    actor_type="system",
                    actor_id=actor_id,
                    action="approval.cancelled",
                    resource_type="approval",
                    resource_id=row["id"],
                    outcome="cancelled",
                    correlation_id=correlation_id,
                    approval_id=row["id"],
                    metadata={"reason": reason},
                )
        return len(pending)

    def history(self, approval_id: str) -> list[dict[str, Any]]:
        self.get(approval_id)
        return list(reversed(self.ledger.events(approval_id=approval_id, limit=1000)))

    def _expire_stale(self) -> None:
        now = iso(self.clock())
        stale = self.conn.execute(
            "SELECT id, risk_level FROM approvals WHERE status = 'pending' AND expires_at IS NOT NULL AND expires_at <= ?",
            (now,),
        ).fetchall()
        for row in stale:
            with transaction(self.conn):
                changed = self.conn.execute(
                    """UPDATE approvals SET status = 'expired', decider_type = 'system', decided_at = ?
                       WHERE id = ? AND status = 'pending'""",
                    (now, row["id"]),
                ).rowcount
                if changed:
                    self.ledger.append(
                        actor_type="system",
                        actor_id="approval-expiry",
                        action="approval.expired",
                        resource_type="approval",
                        resource_id=row["id"],
                        outcome="expired",
                        correlation_id=new_id(),
                        risk_level=row["risk_level"],
                        approval_id=row["id"],
                    )

    @staticmethod
    def effective_payload(approval: dict[str, Any], original: dict[str, Any]) -> dict[str, Any]:
        if ApprovalStatus(approval["status"]) == ApprovalStatus.MODIFIED and isinstance(
            approval.get("modified_payload"), dict
        ):
            return approval["modified_payload"]
        return original

    @staticmethod
    def seconds_left(approval: dict[str, Any], now: datetime) -> int | None:
        if not approval.get("expires_at"):
            return None
        return int((datetime.fromisoformat(approval["expires_at"]) - now).total_seconds())
