"""Steps 6-9 of the action pipeline: approval binding, execution, verification, audit.

``GovernedExecutor.perform`` is the only code path that runs a tool. Every call
produces a full nine-step trace, a RiskAssessment record, and audit events. The
approval check is a digest comparison, so an operator approves one exact
payload and nothing else.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from agent_core.models import Agent, Approval, RiskAssessment
from audit_ledger.canonical import redact
from policy_engine.engine import STEP_NAMES, ActionRequest, GateDecision, StepResult
from policy_engine.verify import verify_output

if TYPE_CHECKING:
    from agent_core.office import Office


@dataclass
class PerformResult:
    status: str  # completed | waiting_approval | denied | failed
    decision: GateDecision
    steps: list[StepResult] = field(default_factory=list)
    output: dict[str, Any] | None = None
    approval: Approval | None = None
    error: str | None = None

    def trace(self) -> list[dict[str, Any]]:
        return [{"step": s.step, "name": s.name, "state": s.state, "detail": s.detail} for s in self.steps]


class GovernedExecutor:
    def __init__(self, office: Office) -> None:
        self.office = office

    def perform(self, request: ActionRequest) -> PerformResult:
        o = self.office
        agent = o.store.get(Agent, request.agent_id)
        decision = o.evaluate(request, agent=agent)
        steps = list(decision.steps)
        subject = request.task_id or decision.digest[:16]
        o.store.put(
            RiskAssessment(
                id=o.ids("risk"),
                subject_type="task" if request.task_id else "request",
                subject_id=subject,
                action_type=request.action_type,
                tier=decision.tier,
                score=decision.score,
                outcome=decision.outcome,
                factors=decision.factors + decision.reasons,
                injection_suspected=decision.injection_suspected,
                policy_version=decision.policy_version,
                created_at=o.clock.iso(),
            ),
            o.clock.iso(),
        )
        o.log(
            request.agent_id,
            "agent",
            "policy.evaluated",
            subject,
            {
                "action_type": request.action_type,
                "outcome": decision.outcome,
                "score": decision.score,
                "digest": decision.digest,
                "tool_id": decision.tool_id,
                "steps": [{"step": s.step, "passed": s.passed, "detail": s.detail} for s in decision.steps],
            },
            decision.tier,
        )

        if decision.outcome == "deny":
            if agent is not None:
                o.bump_metric(agent.id, "policy_denials")
            self._tail(steps, 7, "skipped", "not executed: denied by policy")
            return PerformResult("denied", decision, steps, error="; ".join(decision.reasons))

        approval: Approval | None = None
        approved_digest: str | None = None
        if decision.outcome == "approval_required":
            if request.approval_id:
                ok, why, approval = o.desk.validate_for_execution(request.approval_id, decision.digest)
                steps[5] = StepResult(6, STEP_NAMES[5], ok, f"approval {request.approval_id}: {why}")
                if not ok:
                    o.log(
                        request.agent_id,
                        "agent",
                        "approval.invalid",
                        request.approval_id,
                        {"reason": why, "digest": decision.digest},
                        decision.tier,
                    )
                    self._tail(steps, 7, "skipped", "not executed: approval invalid")
                    return PerformResult("denied", decision, steps, approval=approval, error=why)
                approved_digest = decision.digest
            else:
                assert agent is not None  # identity step passed
                approval = o.desk.request(decision, request, agent)
                o.bump_metric(agent.id, "approvals_requested")
                steps[5] = StepResult(
                    6, STEP_NAMES[5], False, f"queued as {approval.id}: {'; '.join(decision.reasons)}", "pending"
                )
                self._tail(steps, 7, "pending", "held: waiting for operator approval")
                return PerformResult("waiting_approval", decision, steps, approval=approval)

        # 7. Execution ------------------------------------------------------------
        assert agent is not None and decision.tool_id is not None
        ctx = {
            "office": o,
            "agent": agent,
            "params": request.params,
            "task_id": request.task_id,
            "mission_id": request.mission_id,
            "now": o.clock.iso(),
            "sandbox": request.sandbox,
            "approval_id": request.approval_id,
            "approved_digest": approved_digest,
            "tier": decision.tier,
        }
        try:
            raw_output = o.tools.execute(decision.tool_id, request.action_type, ctx)
        except Exception as exc:  # noqa: BLE001 - every tool failure is recorded, never swallowed
            error = f"{type(exc).__name__}: {exc}"
            steps.append(StepResult(7, STEP_NAMES[6], False, error))
            self._tail(steps, 8, "skipped", "not reached")
            o.log(
                agent.id,
                "agent",
                "action.failed",
                subject,
                {"action_type": request.action_type, "error": error},
                decision.tier,
            )
            return PerformResult("failed", decision, steps, error=error)
        output, hits = redact(raw_output)
        if hits:
            output["_redacted_rules"] = hits
        mode = (output.get("receipt") or {}).get("mode", "internal")
        steps.append(StepResult(7, STEP_NAMES[6], True, f"{decision.tool_id} ran ({mode})"))

        # 8. Verification -----------------------------------------------------------
        spec = o.policy.spec(request.action_type)
        ok, detail = verify_output(spec.verify if spec else "unknown", output, approved_digest=approved_digest)
        if ok and o.policy.tiers[decision.tier].get("post_verification"):
            plan = request.params.get("verification_plan", "")
            detail += f"; post-action verification recorded against plan: {plan[:120]}"
        steps.append(StepResult(8, STEP_NAMES[7], ok, detail))
        if not ok:
            self._tail(steps, 9, "pass", "failure sealed into the audit chain")
            o.log(
                agent.id,
                "agent",
                "verification.failed",
                subject,
                {"action_type": request.action_type, "detail": detail},
                decision.tier,
            )
            return PerformResult(
                "failed", decision, steps, output=output, approval=approval, error=f"verification failed: {detail}"
            )

        if approval is not None:
            o.desk.mark_executed(
                approval, {"receipt": output.get("receipt"), "executed_at": o.clock.iso(), "task_id": request.task_id}
            )

        # 9. Audit ----------------------------------------------------------------
        event = o.log(
            agent.id,
            "agent",
            "action.executed",
            subject,
            {
                "action_type": request.action_type,
                "tool_id": decision.tool_id,
                "mode": mode,
                "external": decision.external,
                "approval_id": request.approval_id,
                "digest": decision.digest,
                "summary": output.get("summary"),
            },
            decision.tier,
        )
        steps.append(StepResult(9, STEP_NAMES[8], True, f"sealed as audit #{event['seq']} {event['hash'][:12]}"))
        return PerformResult("completed", decision, steps, output=output, approval=approval)

    @staticmethod
    def _tail(steps: list[StepResult], start: int, state: str, detail: str) -> None:
        """Fill steps ``start``..8 with ``state``; step 9 is always the audit seal."""
        for n in range(start, 9):
            steps.append(StepResult(n, STEP_NAMES[n - 1], state == "pass", detail, state))
        steps.append(StepResult(9, STEP_NAMES[8], True, "decision sealed into the audit chain"))
