"""The Approval Desk.

Rules, all enforced here and covered by tests/test_approvals.py:

- Only a human principal whose role is in ``policy.approval.approver_roles`` can
  decide. An agent principal is refused and the attempt is audited.
- Every decision needs a reason of at least ``min_reason_chars`` characters.
- Decisions are appended to the ``approval_decisions`` table, which the database
  refuses to update or delete. The approval document only carries derived state.
- An approval is bound to the SHA-256 digest of the exact action payload. The
  executor will only run a payload whose digest equals ``approved_digest``.
- "modify" approves an edited payload: edits may change only existing parameter
  keys, the edited action is re-evaluated by the policy engine, and the new
  digest is what gets bound.
- Approvals expire after ``ttl_hours``. Expired, rejected, cancelled, and
  executed approvals can never be executed.

Integrity is enforced by the database as well as this class (agent_core/store.py):

- The original request is written once to ``approval_requests`` (append-only).
  Every decision and every execution re-checks the approval document against it,
  so an edited document is refused.
- A unique index allows one approve/reject/modify decision per approval.
- ``consume`` writes the approval's single row in ``approval_executions`` *before*
  the tool runs. A second use, even a concurrent one, fails at the primary key.
- An identical request (same digest) while one is pending reuses the pending
  approval instead of queueing a duplicate.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from agent_core.models import Agent, Approval, ApprovalStatus
from agent_core.util import parse_iso
from audit_ledger.canonical import digest
from policy_engine.engine import ActionRequest, GateDecision

if TYPE_CHECKING:
    from agent_core.office import Office

DECISIONS = ("approve", "reject", "modify")


class ApprovalError(PermissionError):
    pass


@dataclass(frozen=True)
class Principal:
    id: str
    kind: str  # "human" | "agent" | "system"
    role: str

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "kind": self.kind, "role": self.role}


SYSTEM = Principal("system.office", "system", "system")


class ApprovalDesk:
    def __init__(self, office: Office) -> None:
        self.office = office

    @property
    def policy(self):  # noqa: ANN201 - convenience alias
        return self.office.policy

    # -- queue ----------------------------------------------------------------

    def request(self, decision: GateDecision, request: ActionRequest, agent: Agent) -> Approval:
        o = self.office
        for pending in self.list("pending"):
            # Same payload from the same task (a retry): reuse. Another task gets its own approval,
            # because a decision resumes exactly one task.
            if pending.action_digest == decision.digest and pending.task_id == request.task_id:
                o.log(
                    agent.id,
                    "agent",
                    "approval.reused",
                    pending.id,
                    {"action_type": pending.action_type, "digest": decision.digest, "task_id": request.task_id},
                    decision.tier,
                )
                return pending
        now = o.clock.now()
        params = request.params
        approval = Approval(
            id=o.ids("apr"),
            action_type=request.action_type,
            action=request.binding(decision.tool_id),
            action_digest=decision.digest,
            requested_by=agent.id,
            risk_tier=decision.tier,
            reasons=list(decision.reasons) + [f"factor: {f}" for f in decision.factors],
            task_id=request.task_id,
            mission_id=request.mission_id,
            change_plan=params.get("change_plan"),
            rollback_plan=params.get("rollback_plan"),
            verification_plan=params.get("verification_plan"),
            expires_at=(now + timedelta(hours=self.policy.approval_ttl_hours)).isoformat(timespec="seconds"),
            created_at=now.isoformat(timespec="seconds"),
            updated_at=now.isoformat(timespec="seconds"),
        )
        o.store.record_approval_request(
            approval_id=approval.id,
            action_digest=approval.action_digest,
            action=approval.action,
            requested_by=agent.id,
            risk_tier=approval.risk_tier,
            requested_at=approval.created_at,
        )
        o.store.put(approval, approval.created_at)
        o.log(
            agent.id,
            "agent",
            "approval.requested",
            approval.id,
            {
                "action_type": approval.action_type,
                "digest": approval.action_digest,
                "task_id": approval.task_id,
                "reasons": approval.reasons,
            },
            decision.tier,
        )
        return approval

    def get(self, approval_id: str) -> Approval | None:
        approval = self.office.store.get(Approval, approval_id)
        if approval is None:
            return None
        approval.decisions = self.office.store.decisions_for([approval_id])[approval_id]
        return self._expire_if_due(approval)

    def list(self, status: str | None = None) -> list[Approval]:
        items = self.office.store.list(Approval, newest_first=True)
        history = self.office.store.decisions_for([a.id for a in items])
        out = []
        for a in items:
            a.decisions = history[a.id]
            a = self._expire_if_due(a)
            if status is None or a.status == status:
                out.append(a)
        return out

    # -- decisions ------------------------------------------------------------

    def decide(
        self,
        approval_id: str,
        principal: Principal,
        decision: str,
        reason: str,
        modifications: dict[str, Any] | None = None,
    ) -> Approval:
        o = self.office
        if principal.kind != "human" or principal.role not in self.policy.approver_roles:
            o.log(
                principal.id,
                principal.kind if principal.kind in ("agent", "human") else "system",
                "approval.refused_principal",
                approval_id,
                {"reason": "only a human operator can decide approvals"},
                "critical",
            )
            raise ApprovalError("only a human operator can decide approvals")
        if decision not in DECISIONS:
            raise ApprovalError(f"decision must be one of {DECISIONS}")
        reason = (reason or "").strip()
        if len(reason) < self.policy.min_reason_chars:
            raise ApprovalError(f"a reason of at least {self.policy.min_reason_chars} characters is required")
        approval = self.get(approval_id)
        if approval is None:
            raise ApprovalError("unknown approval")
        if approval.status != ApprovalStatus.PENDING:
            raise ApprovalError(f"approval is {approval.status}; only pending approvals can be decided")
        original = self._original_request(approval)

        resulting_digest: str | None = None
        if decision == "reject":
            approval.status = ApprovalStatus.REJECTED
        else:
            params = dict(original["params"])
            if decision == "modify":
                if not modifications:
                    raise ApprovalError("modify requires at least one parameter change")
                unknown = set(modifications) - set(params)
                if unknown:
                    raise ApprovalError(f"modify can only change existing parameters; unknown: {sorted(unknown)}")
                params.update(modifications)
            req = ActionRequest(
                agent_id=original["agent_id"],
                action_type=original["action_type"],
                params=params,
                tool_id=original.get("tool_id"),
                task_id=approval.task_id,
                mission_id=approval.mission_id,
            )
            gate = o.evaluate(req)
            if gate.outcome == "deny":
                raise ApprovalError("the action no longer passes policy: " + "; ".join(gate.reasons))
            resulting_digest = gate.digest
            approval.status = ApprovalStatus.APPROVED
            approval.approved_digest = gate.digest
            approval.approved_action = req.binding(gate.tool_id)

        now = o.clock.iso()
        try:
            o.store.append_decision(
                approval_id=approval.id,
                decision=decision,
                reason=reason,
                decided_by=principal.id,
                decided_at=now,
                modifications=modifications if decision == "modify" else None,
                resulting_digest=resulting_digest,
            )
        except sqlite3.IntegrityError as exc:
            # The unique index is the backstop for a concurrent second decision.
            raise ApprovalError("approval has already been decided") from exc
        approval.updated_at = now
        approval.decisions = []
        o.store.put(approval, now)
        o.log(
            principal.id,
            "human",
            f"approval.{decision}",
            approval.id,
            {
                "reason": reason,
                "modifications": modifications if decision == "modify" else None,
                "resulting_digest": resulting_digest,
                "action_type": approval.action_type,
            },
            approval.risk_tier,
        )
        return self.get(approval.id)  # type: ignore[return-value]

    def _original_request(self, approval: Approval) -> dict[str, Any]:
        """The immutable request, after checking the approval document still matches it."""
        row = self.office.store.approval_request(approval.id)
        problem = None
        if row is None:
            problem = "no immutable request record"
        elif row["action_digest"] != approval.action_digest or digest(row["action"]) != row["action_digest"]:
            problem = "request record does not match its digest"
        elif digest(approval.action) != row["action_digest"]:
            problem = "approval document differs from the original request"
        if problem:
            self.office.log(
                "system.office", "system", "approval.integrity_failure", approval.id, {"problem": problem}, "critical"
            )
            raise ApprovalError(f"approval integrity check failed: {problem}")
        return row["action"]

    def validate_for_execution(self, approval_id: str, digest_: str) -> tuple[bool, str, Approval | None]:
        approval = self.get(approval_id)
        if approval is None:
            return False, "unknown approval", None
        if self.office.store.execution_of(approval_id) is not None:
            return False, "approval has already been used", approval
        if approval.status != ApprovalStatus.APPROVED:
            return False, f"approval is {approval.status}", approval
        if approval.approved_digest != digest_:
            return False, "payload differs from the approved payload", approval
        try:
            self._original_request(approval)
        except ApprovalError as exc:
            return False, str(exc), approval
        return True, "approved payload matches", approval

    def consume(self, approval: Approval, digest_: str, task_id: str | None) -> None:
        """Use the approval exactly once. Called before the tool runs."""
        try:
            self.office.store.record_execution(
                approval_id=approval.id, executed_digest=digest_, executed_at=self.office.clock.iso(), task_id=task_id
            )
        except sqlite3.IntegrityError as exc:
            raise ApprovalError("approval has already been used") from exc
        approval.status = ApprovalStatus.EXECUTED
        approval.updated_at = self.office.clock.iso()
        approval.decisions = []
        self.office.store.put(approval, approval.updated_at)

    def record_outcome(self, approval: Approval, execution: dict[str, Any]) -> None:
        approval.execution = execution
        approval.updated_at = self.office.clock.iso()
        approval.decisions = []
        self.office.store.put(approval, approval.updated_at)

    def cancel_open(self, principal: Principal, reason: str) -> list[str]:
        """Emergency stop: cancel every approval that could still lead to execution."""
        cancelled = []
        for approval in self.list():
            if approval.status in (ApprovalStatus.PENDING, ApprovalStatus.APPROVED):
                now = self.office.clock.iso()
                self.office.store.append_decision(
                    approval_id=approval.id,
                    decision="cancelled",
                    reason=reason,
                    decided_by=principal.id,
                    decided_at=now,
                    modifications=None,
                    resulting_digest=None,
                )
                approval.status = ApprovalStatus.CANCELLED
                approval.updated_at = now
                approval.decisions = []
                self.office.store.put(approval, now)
                cancelled.append(approval.id)
        return cancelled

    def _expire_if_due(self, approval: Approval) -> Approval:
        if approval.status in (ApprovalStatus.PENDING, ApprovalStatus.APPROVED) and approval.expires_at:
            if parse_iso(approval.expires_at) <= self.office.clock.now():
                approval.status = ApprovalStatus.EXPIRED
                approval.updated_at = self.office.clock.iso()
                history, approval.decisions = approval.decisions, []
                self.office.store.put(approval, approval.updated_at)
                self.office.log("system.office", "system", "approval.expired", approval.id, {}, approval.risk_tier)
                approval.decisions = history
        return approval
