"""The nine-stage governance gate.

Agents never call tools directly. Every tool use is an :class:`ActionRequest`
submitted here, and it passes these stages in order:

0. Emergency halt  - a global stop refuses everything.
1. Identity        - the agent exists and is in an active status.
2. Permission      - an unexpired, unrevoked grant covers the tool and action,
                     and the payload satisfies the grant's constraints.
3. Risk            - deterministic classification; critical needs a capable agent.
4. Policy          - Cedar, fail closed; may answer allow, deny or require_approval.
5. Capability      - the tool is enabled and declares the operation.
6. Approval        - high/critical risk, a policy requirement, or a propose-only
                     grant files a human approval and stops here.
7. Execution       - the approval is consumed (single use), an intent event is
                     written *before* the adapter runs, then the adapter runs
                     with credentials from the secret broker.
8. Verification    - the adapter checks its own post-condition.
9. Audit           - the outcome is written to the hash-chained ledger.

Denials are returned as outcomes, never raised, so a caller's transaction
rollback can never erase the denial's audit event.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from . import risk as risk_mod
from .approvals import ApprovalService
from .audit import AuditFailure, AuditLedger
from .db import dumps, new_id, row_to_dict
from .emergency import EmergencyService, record_incident
from .identity import IdentityService, PermissionService
from .models import (
    APPROVAL_REQUIRED_RISKS,
    TOOL_OPERATIONS,
    ActionRequest,
    Clock,
    GateOutcome,
    GovernanceError,
    RiskLevel,
    sha256_hex,
    utcnow,
)
from .policy import DENY, REQUIRE_APPROVAL, GateContext, PolicyEngine
from .tools import ExecutionContext, SecretBroker, ToolRegistry

MIN_ROLLBACK_PLAN_CHARS = 20


class GovernanceGate:
    def __init__(
        self,
        *,
        conn: sqlite3.Connection,
        company_id: str,
        ledger: AuditLedger,
        identity: IdentityService,
        permissions: PermissionService,
        policy: PolicyEngine,
        registry: ToolRegistry,
        approvals: ApprovalService,
        emergency: EmergencyService,
        secrets: SecretBroker,
        clock: Clock = utcnow,
    ):
        self.conn = conn
        self.company_id = company_id
        self.ledger = ledger
        self.identity = identity
        self.permissions = permissions
        self.policy = policy
        self.registry = registry
        self.approvals = approvals
        self.emergency = emergency
        self.secrets = secrets
        self.clock = clock

    # ------------------------------------------------------------------ public

    def submit(self, request: ActionRequest) -> GateOutcome:
        corr = request.correlation_id or new_id()

        # 0. Emergency halt
        if self.emergency.is_halted():
            return self._deny(request, corr, "emergency_stop", "a global emergency stop is in force", stage=0)

        # 1. Identity
        agent = self.identity.resolve_active_agent(request.agent_id)
        if agent is None:
            return self._deny(request, corr, "identity_unresolved", "agent missing, paused, suspended or retired", stage=1)
        mission = self._mission(request.mission_id)
        if request.mission_id and mission is None:
            return self._deny(request, corr, "mission_unknown", "mission does not exist", stage=1)
        if mission and mission["status"] in ("paused", "cancelled", "completed", "failed"):
            return self._deny(request, corr, "mission_not_active", f"mission is {mission['status']}", stage=1)
        mission_mode = mission["mode"] if mission else "production"

        tool = self.registry.tool_row(self.conn, request.tool_key)
        spec = self.registry.spec(request.tool_key)
        if tool is None or spec is None:
            return self._deny(request, corr, "tool_unknown", f"no registered tool {request.tool_key}", stage=2)

        approval: dict[str, Any] | None = None
        payload = request.payload
        if request.approval_id:
            try:
                approval = self.approvals.executable(request.approval_id, request)
            except GovernanceError as exc:
                return self._deny(request, corr, exc.code, exc.message, stage=6)
            payload = ApprovalService.effective_payload(approval, request.payload)

        # 2. Permission
        exec_grant = self.permissions.active_grant(agent["id"], request.tool_key, request.action)
        propose_grant = (
            self.permissions.active_grant(agent["id"], request.tool_key, "propose")
            if request.action == "execute"
            else None
        )
        grant = exec_grant or propose_grant
        if grant is None:
            return self._deny(request, corr, "permission_denied", "no active grant covers this tool and action", stage=2)
        violation = self._constraint_violation(grant.get("constraints") or {}, payload)
        if violation:
            return self._deny(request, corr, "grant_constraint_violated", violation, stage=2)

        # 3. Risk
        assessment = risk_mod.classify(tool, request.action, payload)
        level = assessment.level
        if level == RiskLevel.CRITICAL and not agent["can_request_critical"]:
            return self._deny(
                request, corr, "critical_not_allowed_for_agent", "agent may not request critical actions",
                stage=3, risk=level,
            )

        # 4. Policy
        approved_by_human = approval is not None and approval.get("decider_type") == "human"
        ctx = self._policy_context(level, payload, mission_mode, approved_by_human, request.mission_id)
        decision = self.policy.decide(agent, tool, request.action, ctx)
        if decision.diverged:
            self._record_divergence(corr, request, decision.effect, decision.shadow_effect or "", decision.shadow_policy_ids)
        if decision.effect == DENY:
            reason = "; ".join(decision.errors) if decision.errors else "refused by policy"
            return self._deny(
                request, corr, "policy_denied", reason, stage=4, risk=level, policy_ids=decision.policy_ids,
            )

        # 5. Tool capability
        operations = (tool.get("capability_surface") or {}).get("operations", {})
        if not tool["enabled"] or request.action not in operations or request.action not in TOOL_OPERATIONS:
            return self._deny(
                request, corr, "tool_capability_mismatch", "tool is disabled or does not declare this operation",
                stage=5, risk=level,
            )

        # 6. Human approval
        needs_approval = (
            decision.effect == REQUIRE_APPROVAL or level in APPROVAL_REQUIRED_RISKS or exec_grant is None
        )
        if needs_approval and approval is None:
            rationale = "; ".join(
                assessment.reasons
                + ([f"policy: {', '.join(decision.policy_ids)}"] if decision.policy_ids else [])
                + (["agent holds a propose-only grant"] if exec_grant is None else [])
            )
            try:
                filed = self.approvals.create_or_reuse(
                    request,
                    risk=level,
                    action_summary=self._summary(agent, spec.name, payload),
                    policy_rationale=rationale,
                    correlation_id=corr,
                )
            except AuditFailure as exc:
                return self._audit_failure(request, corr, exc, level)
            return GateOutcome(
                status="waiting_for_approval",
                correlation_id=corr,
                code="approval_required",
                message=rationale,
                risk_level=level,
                approval_id=filed["id"],
                policy_ids=decision.policy_ids,
            )

        # 7. Execution
        if approval is not None:
            try:
                self.approvals.consume(approval["id"], corr)
            except GovernanceError as exc:
                return self._deny(request, corr, exc.code, exc.message, stage=7, risk=level)
        approval_id = approval["id"] if approval else None
        try:
            self.ledger.append(
                actor_type="agent",
                actor_id=agent["id"],
                action="tool.execution.intent",
                resource_type="tool",
                resource_id=request.task_id,
                outcome="pending",
                correlation_id=corr,
                payload=payload,
                risk_level=level.value,
                policy_decision=decision.effect,
                policy_ids=decision.policy_ids,
                approval_id=approval_id,
                metadata={"tool_key": request.tool_key, "action": request.action, "mission_id": request.mission_id},
            )
        except AuditFailure as exc:
            return self._audit_failure(request, corr, exc, level)

        exec_ctx = ExecutionContext(
            conn=self.conn,
            company_id=self.company_id,
            agent=agent,
            correlation_id=corr,
            clock=self.clock,
            mission_id=request.mission_id,
            task_id=request.task_id,
            mission_mode=mission_mode,
            credential=self.secrets.resolve(spec.secret_ref, mission_mode=mission_mode),
        )
        adapter = self.registry.adapter(request.tool_key)
        try:
            result = adapter.invoke(request.action, payload, exec_ctx)
        except Exception as exc:
            self._safe_append(
                agent["id"], "tool.execution", "failure", corr, request, level, approval_id,
                {"tool_key": request.tool_key, "error": f"{type(exc).__name__}: {exc}"},
            )
            return GateOutcome(
                status="failed", correlation_id=corr, code="execution_error",
                message=f"{type(exc).__name__}: {exc}", risk_level=level, approval_id=approval_id,
            )

        # 8. Verification
        try:
            verified = bool(adapter.verify(request.action, payload, result, exec_ctx))
        except Exception:
            verified = False

        # 9. Audit
        try:
            self.ledger.append(
                actor_type="agent",
                actor_id=agent["id"],
                action="tool.execution",
                resource_type="tool",
                resource_id=request.task_id,
                outcome="success" if verified else "unverified",
                correlation_id=corr,
                payload=payload,
                risk_level=level.value,
                policy_decision=decision.effect,
                policy_ids=decision.policy_ids,
                approval_id=approval_id,
                metadata={
                    "tool_key": request.tool_key,
                    "action": request.action,
                    "result_digest": sha256_hex(result),
                    "dry_run": bool(result.get("dry_run")),
                },
            )
        except AuditFailure as exc:
            record_incident(
                self.conn, self.clock, severity="critical", title="Executed action not audited",
                triggered_by=agent["id"], reason=str(exc),
                metadata={"correlation_id": corr, "tool_key": request.tool_key},
            )
            return GateOutcome(
                status="executed", correlation_id=corr, code="audit_incident",
                message="executed, but the outcome could not be audited; incident opened",
                risk_level=level, approval_id=approval_id, result=result, verified=verified,
            )
        return GateOutcome(
            status="executed",
            correlation_id=corr,
            risk_level=level,
            approval_id=approval_id,
            result=result,
            verified=verified,
            policy_ids=decision.policy_ids,
        )

    # ----------------------------------------------------------------- helpers

    def _mission(self, mission_id: str | None) -> dict[str, Any] | None:
        if not mission_id:
            return None
        return row_to_dict(self.conn.execute("SELECT * FROM missions WHERE id = ?", (mission_id,)).fetchone())

    @staticmethod
    def _constraint_violation(constraints: dict[str, Any], payload: dict[str, Any]) -> str:
        limit = constraints.get("spend_limit_cents")
        if limit is not None:
            try:
                amount = int(payload.get("amount_cents", 0) or 0)
            except (TypeError, ValueError):
                return "amount_cents is not an integer"
            if amount > int(limit):
                return f"amount exceeds the grant's spend limit of {int(limit)} cents"
        for field, allowed in (constraints.get("payload_allowlist") or {}).items():
            if payload.get(field) not in allowed:
                return f"{field} is not in the grant's allowlist"
        return ""

    def _has_test_evidence(self, evidence: Any, mission_id: str | None) -> bool:
        """Evidence must be a completed, passing sandbox check in the same mission."""
        if not isinstance(evidence, str) or not mission_id:
            return False
        task = row_to_dict(
            self.conn.execute(
                "SELECT * FROM tasks WHERE id = ? AND mission_id = ?", (evidence, mission_id)
            ).fetchone()
        )
        if not task or task["status"] != "completed" or task["tool_key"] != "sandbox.checks":
            return False
        output = task.get("actual_output") or {}
        return isinstance(output, dict) and output.get("passed") is True

    def _policy_context(
        self,
        level: RiskLevel,
        payload: dict[str, Any],
        mission_mode: str,
        approved_by_human: bool,
        mission_id: str | None,
    ) -> GateContext:
        amount = int(payload.get("amount_cents", 0) or 0)
        rollback = payload.get("rollback_plan")
        return GateContext(
            risk=level.value,
            approved_by_human=approved_by_human,
            mission_mode=mission_mode,
            external=payload.get("external") is True,
            has_rollback_plan=isinstance(rollback, str) and len(rollback.strip()) >= MIN_ROLLBACK_PLAN_CHARS,
            has_test_evidence=self._has_test_evidence(payload.get("test_evidence"), mission_id),
            amount_cents=amount,
            # The payload is bound to the approval by hash, so the approved
            # amount is the amount in the payload the human approved.
            approved_amount_cents=amount if approved_by_human else 0,
            data_classification=str(payload.get("data_classification", "internal")),
        )

    @staticmethod
    def _summary(agent: dict[str, Any], tool_name: str, payload: dict[str, Any]) -> str:
        what = payload.get("summary")
        if isinstance(what, str) and what.strip():
            return f"{agent['name']} requests: {what.strip()[:240]} ({tool_name})"
        return f"{agent['name']} requests to use {tool_name}"

    def _record_divergence(
        self, corr: str, request: ActionRequest, enforced: str, shadow: str, shadow_ids: list[str]
    ) -> None:
        self.conn.execute(
            """INSERT INTO policy_shadow_divergences (correlation_id, agent_id, tool_key, action,
                   enforced_effect, shadow_effect, shadow_policy_ids, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (corr, request.agent_id, request.tool_key, request.action, enforced, shadow,
             dumps(shadow_ids), self.clock().isoformat()),
        )

    def _deny(
        self,
        request: ActionRequest,
        corr: str,
        code: str,
        message: str,
        *,
        stage: int,
        risk: RiskLevel | None = None,
        policy_ids: list[str] | None = None,
    ) -> GateOutcome:
        try:
            self.ledger.append(
                actor_type="agent",
                actor_id=request.agent_id,
                action="governance.deny",
                resource_type="tool",
                resource_id=request.task_id,
                outcome="blocked",
                correlation_id=corr,
                payload=request.payload,
                risk_level=risk.value if risk else None,
                policy_decision="deny",
                policy_ids=policy_ids or [],
                approval_id=request.approval_id,
                metadata={"code": code, "stage": stage, "message": message, "tool_key": request.tool_key,
                          "action": request.action, "mission_id": request.mission_id},
            )
        except AuditFailure as exc:
            record_incident(
                self.conn, self.clock, severity="critical", title="Denial not audited",
                triggered_by=request.agent_id, reason=str(exc), metadata={"correlation_id": corr, "code": code},
            )
        return GateOutcome(
            status="denied", correlation_id=corr, code=code, message=message, risk_level=risk,
            policy_ids=policy_ids or [],
        )

    def _audit_failure(self, request: ActionRequest, corr: str, exc: Exception, level: RiskLevel) -> GateOutcome:
        record_incident(
            self.conn, self.clock, severity="critical", title="Audit ledger unavailable; action refused",
            triggered_by=request.agent_id, reason=str(exc),
            metadata={"correlation_id": corr, "tool_key": request.tool_key},
        )
        return GateOutcome(
            status="failed", correlation_id=corr, code="audit_failure",
            message="the ledger could not record the intent, so nothing was executed", risk_level=level,
        )

    def _safe_append(
        self,
        actor_id: str,
        action: str,
        outcome: str,
        corr: str,
        request: ActionRequest,
        level: RiskLevel,
        approval_id: str | None,
        metadata: dict[str, Any],
    ) -> None:
        try:
            self.ledger.append(
                actor_type="agent", actor_id=actor_id, action=action, resource_type="tool",
                resource_id=request.task_id, outcome=outcome, correlation_id=corr,
                payload=request.payload, risk_level=level.value, approval_id=approval_id, metadata=metadata,
            )
        except AuditFailure as exc:
            record_incident(
                self.conn, self.clock, severity="critical", title="Execution failure not audited",
                triggered_by=actor_id, reason=str(exc), metadata={"correlation_id": corr},
            )
