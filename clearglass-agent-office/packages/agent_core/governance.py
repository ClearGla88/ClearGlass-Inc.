"""Steps 6-9 of the action pipeline: approval binding, execution, verification, audit.

``GovernedExecutor.perform`` is the only code path that runs a tool. Every call
produces a full nine-step trace, a RiskAssessment record, and audit events. The
approval check is a digest comparison, so an operator approves one exact
payload and nothing else.

Execution integrity:

- An ``action.intent`` event is sealed into the ledger *before* the tool runs.
  If it cannot be written, nothing runs. An intent with no later outcome event
  marks an execution that was interrupted (the security review reports it).
- An approval is consumed (its single ``approval_executions`` row) before the
  tool runs, so it cannot be used twice, even concurrently.
- If the ``action.executed`` event cannot be written after the tool ran, an
  incident record is opened outside the ledger and the operator is notified.
- An ``idempotency_key`` makes a retried request replay the stored result
  instead of acting twice; reusing a key with a different payload is refused.
- Shadow-rule divergences are recorded; they never change the outcome.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from agent_core.approvals import ApprovalError
from agent_core.models import Agent, Approval, Report, RiskAssessment, ShadowDivergence
from audit_ledger.canonical import digest, redact
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
    replayed: bool = False
    incident_id: str | None = None

    def trace(self) -> list[dict[str, Any]]:
        return [{"step": s.step, "name": s.name, "state": s.state, "detail": s.detail} for s in self.steps]


class GovernedExecutor:
    def __init__(self, office: Office) -> None:
        self.office = office

    @staticmethod
    def idempotency_digest(request: ActionRequest) -> str:
        return digest(
            {
                "agent_id": request.agent_id,
                "action_type": request.action_type,
                "params": request.params,
                "mission_id": request.mission_id,
                "task_id": request.task_id,
                "sandbox": request.sandbox,
            }
        )

    def perform(self, request: ActionRequest) -> PerformResult:
        o = self.office
        agent = o.store.get(Agent, request.agent_id)
        decision = o.evaluate(request, agent=agent)
        steps = list(decision.steps)
        subject = request.task_id or decision.digest[:16]

        idem_digest = self.idempotency_digest(request) if request.idempotency_key else None
        if request.idempotency_key:
            prior = o.store.idempotency_get(request.idempotency_key)
            if prior and prior["request_digest"] != idem_digest and prior["status"] != "failed":
                why = "idempotency key was already used for a different request"
                o.log(
                    request.agent_id,
                    "agent",
                    "idempotency.conflict",
                    subject,
                    {"key_digest": digest(request.idempotency_key)},
                    decision.tier,
                )
                self._tail(steps, 7, "skipped", f"not executed: {why}")
                return PerformResult("denied", decision, steps, error=why)
            if prior and prior["status"] == "in_progress":
                why = "a request with this idempotency key is still in progress"
                self._tail(steps, 7, "skipped", f"not executed: {why}")
                return PerformResult("denied", decision, steps, error=why)
            if prior and prior["status"] == "completed":
                o.log(
                    request.agent_id,
                    "agent",
                    "action.replayed",
                    subject,
                    {"action_type": request.action_type, "digest": decision.digest},
                    decision.tier,
                )
                self._tail(steps, 7, "pass", "replayed the stored result; the tool did not run again")
                return PerformResult("completed", decision, steps, output=prior["result"], replayed=True)

        if decision.shadow_diverged:
            now = o.clock.iso()
            o.store.put(
                ShadowDivergence(
                    id=o.ids("shd"),
                    rule_ids=list(decision.shadow_rules),
                    action_type=request.action_type,
                    agent_id=request.agent_id,
                    enforced_outcome=decision.outcome,
                    shadow_outcome=str(decision.shadow_outcome),
                    digest=decision.digest,
                    shadow_version=str(o.policy.shadow_version),
                    task_id=request.task_id,
                    created_at=now,
                ),
                now,
            )
            o.log(
                request.agent_id,
                "agent",
                "policy.shadow_divergence",
                subject,
                {
                    "rules": decision.shadow_rules,
                    "enforced": decision.outcome,
                    "shadow": decision.shadow_outcome,
                    "action_type": request.action_type,
                },
                decision.tier,
            )
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
        if request.idempotency_key and not o.store.idempotency_claim(
            request.idempotency_key, str(idem_digest), o.clock.iso()
        ):
            why = "a request with this idempotency key is already in progress or done"
            self._tail(steps, 7, "skipped", f"not executed: {why}")
            return PerformResult("denied", decision, steps, error=why)
        try:
            o.log(
                agent.id,
                "agent",
                "action.intent",
                subject,
                {
                    "action_type": request.action_type,
                    "tool_id": decision.tool_id,
                    "digest": decision.digest,
                    "approval_id": request.approval_id,
                },
                decision.tier,
            )
        except Exception as exc:  # noqa: BLE001 - no intent record, no execution
            why = f"audit ledger unavailable before execution ({type(exc).__name__}); nothing ran"
            self._finish_idempotency(request, "failed", None)
            self._tail(steps, 7, "skipped", why)
            return PerformResult("failed", decision, steps, error=why)
        if approval is not None:
            try:
                o.desk.consume(approval, decision.digest, request.task_id)
            except ApprovalError as exc:
                self._finish_idempotency(request, "failed", None)
                o.log(agent.id, "agent", "approval.invalid", approval.id, {"reason": str(exc)}, decision.tier)
                self._tail(steps, 7, "skipped", f"not executed: {exc}")
                return PerformResult("denied", decision, steps, approval=approval, error=str(exc))
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
            "digest": decision.digest,
        }
        try:
            raw_output = o.tools.execute(decision.tool_id, request.action_type, ctx)
        except Exception as exc:  # noqa: BLE001 - every tool failure is recorded, never swallowed
            error = f"{type(exc).__name__}: {exc}"
            steps.append(StepResult(7, STEP_NAMES[6], False, error))
            self._tail(steps, 8, "skipped", "not reached")
            self._finish_idempotency(request, "failed", None)
            if approval is not None:
                o.desk.record_outcome(approval, {"result": "failed", "error": error, "task_id": request.task_id})
            o.log(
                agent.id,
                "agent",
                "action.failed",
                subject,
                {"action_type": request.action_type, "error": error, "digest": decision.digest},
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
            self._finish_idempotency(request, "failed", None)
            if approval is not None:
                o.desk.record_outcome(approval, {"result": "verification_failed", "detail": detail})
            o.log(
                agent.id,
                "agent",
                "verification.failed",
                subject,
                {"action_type": request.action_type, "detail": detail, "digest": decision.digest},
                decision.tier,
            )
            return PerformResult(
                "failed", decision, steps, output=output, approval=approval, error=f"verification failed: {detail}"
            )

        if approval is not None:
            o.desk.record_outcome(
                approval, {"receipt": output.get("receipt"), "executed_at": o.clock.iso(), "task_id": request.task_id}
            )
        self._finish_idempotency(request, "completed", output)

        # 9. Audit ----------------------------------------------------------------
        try:
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
        except Exception as exc:  # noqa: BLE001 - the action ran; losing its audit record is an incident
            incident = self._audit_incident(request, decision, agent.id, exc)
            steps.append(StepResult(9, STEP_NAMES[8], False, f"audit write failed; incident {incident} opened"))
            return PerformResult(
                "completed",
                decision,
                steps,
                output=output,
                approval=approval,
                incident_id=incident,
                error=f"executed, but the outcome could not be audited; incident {incident} opened",
            )
        steps.append(StepResult(9, STEP_NAMES[8], True, f"sealed as audit #{event['seq']} {event['hash'][:12]}"))
        return PerformResult("completed", decision, steps, output=output, approval=approval)

    def _finish_idempotency(self, request: ActionRequest, status: str, output: dict[str, Any] | None) -> None:
        if request.idempotency_key:
            self.office.store.idempotency_finish(request.idempotency_key, status, output, self.office.clock.iso())

    def _audit_incident(self, request: ActionRequest, decision: GateDecision, agent_id: str, exc: Exception) -> str:
        """Record outside the ledger (which just failed) that an executed action has no outcome event."""
        o = self.office
        now = o.clock.iso()
        incident = Report(
            id=o.ids("inc"),
            kind="incident",
            title=f"Executed action not audited: {request.action_type}",
            period=o.clock.now().date().isoformat(),
            generated_by="system.office",
            sections={
                "what_happened": "A tool ran, then writing its action.executed event to the audit ledger failed.",
                "when": now,
                "agent": agent_id,
                "action_type": request.action_type,
                "digest": decision.digest,
                "task_id": request.task_id,
                "error": f"{type(exc).__name__}: {exc}",
                "evidence": "The action.intent event for this digest is in the ledger with no outcome event.",
                "required_human_decision": "Check the ledger and storage, then record the outcome manually.",
            },
            metrics={"severity": "critical"},
            generated_at=now,
        )
        o.store.put(incident, now)
        o.post_message(
            sender="system.office",
            recipient="operator",
            kind="notification",
            subject="INCIDENT: executed action not audited",
            body=f"{request.action_type}, incident {incident.id}",
            thread_id="incidents",
            refs=[incident.id],
        )
        return incident.id

    @staticmethod
    def _tail(steps: list[StepResult], start: int, state: str, detail: str) -> None:
        """Fill steps ``start``..8 with ``state``; step 9 is always the audit seal."""
        for n in range(start, 9):
            steps.append(StepResult(n, STEP_NAMES[n - 1], state == "pass", detail, state))
        steps.append(StepResult(9, STEP_NAMES[8], True, "decision sealed into the audit chain"))
