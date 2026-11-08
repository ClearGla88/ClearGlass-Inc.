"""The governance gate: steps 1-6 of the nine-step action pipeline.

``PolicyEngine.evaluate`` is pure. It reads the request, the agent, the tool
registry, and the office state, and returns a ``GateDecision``; it never
executes anything and never writes. That makes it safe to call from control
tests, the ``/policy/evaluate`` dry-run endpoint, and simulations.

Pipeline (steps 7-9 live in ``agent_core.governance``):

1. Identity check        - agent registered, active, office not halted
2. Permission check      - agent's grant for the action's domain >= required level
3. Risk classification   - catalog tier + escalation modifiers + injection scan
4. Policy evaluation     - hard blocks, department rules, sandbox, critical plans, sources
5. Tool-capability check - a granted tool declares the action and its ceiling covers the tier
6. Human approval        - required for high/critical or suspected injection
7. Execution             - tool handler (internal or dry-run connector)
8. Verification          - output checked against the action's verify rule
9. Audit                 - every step above is sealed into the hash chain

Every step is evaluated even after a failure, so the trace shown to the
operator is complete.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from agent_core.models import LEVEL_ORDER, TIER_ORDER, Agent, Tool, bump_tier, max_tier
from audit_ledger.canonical import digest
from policy_engine.policy import Policy

STEP_NAMES = (
    "identity",
    "permission",
    "risk_classification",
    "policy_evaluation",
    "tool_capability",
    "human_approval",
    "execution",
    "verification",
    "audit",
)


@dataclass
class ActionRequest:
    agent_id: str
    action_type: str
    params: dict[str, Any] = field(default_factory=dict)
    tool_id: str | None = None
    task_id: str | None = None
    mission_id: str | None = None
    sandbox: bool = False
    approval_id: str | None = None

    def binding(self, tool_id: str | None) -> dict[str, Any]:
        """The exact payload an approval is bound to."""
        return {
            "agent_id": self.agent_id,
            "action_type": self.action_type,
            "params": self.params,
            "tool_id": tool_id,
        }


@dataclass
class StepResult:
    step: int
    name: str
    passed: bool
    detail: str
    state: str = ""  # pass | fail | pending | skipped

    def __post_init__(self) -> None:
        if not self.state:
            self.state = "pass" if self.passed else "fail"


@dataclass
class GateDecision:
    outcome: str  # allow | approval_required | deny
    action_type: str
    agent_id: str
    tier: str
    score: int
    tool_id: str | None
    digest: str
    policy_version: str
    steps: list[StepResult] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    factors: list[str] = field(default_factory=list)
    injection_suspected: bool = False
    external: bool = False

    @property
    def allowed(self) -> bool:
        return self.outcome == "allow"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OfficeState:
    halted: bool = False
    halted_reason: str | None = None
    approved_sources: tuple[str, ...] = ()


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, (list, tuple)):
        return [s for v in value for s in _strings(v)]
    return []


def scan_injection(value: Any, markers: tuple[str, ...]) -> list[str]:
    """Return the markers found in any string inside ``value`` (case-insensitive)."""
    found: set[str] = set()
    for text in _strings(value):
        low = " ".join(text.lower().split())
        found.update(m for m in markers if m in low)
    return sorted(found)


class PolicyEngine:
    def __init__(self, policy: Policy) -> None:
        self.policy = policy

    def evaluate(
        self,
        request: ActionRequest,
        *,
        agent: Agent | None,
        tools: dict[str, Tool],
        state: OfficeState,
    ) -> GateDecision:
        p = self.policy
        spec = p.spec(request.action_type)
        steps: list[StepResult] = []
        reasons: list[str] = []
        factors: list[str] = []

        def record(step: int, passed: bool, detail: str) -> None:
            steps.append(StepResult(step, STEP_NAMES[step - 1], passed, detail))
            if not passed:
                reasons.append(f"{STEP_NAMES[step - 1]}: {detail}")

        # 1. Identity -----------------------------------------------------------
        if state.halted:
            record(1, False, f"emergency stop engaged ({state.halted_reason or 'no reason given'})")
        elif agent is None:
            record(1, False, f"unknown agent '{request.agent_id}'")
        elif agent.status in ("paused", "retired"):
            record(1, False, f"agent is {agent.status}")
        else:
            record(1, True, f"{agent.callsign} {agent.name} is registered and active")

        # 2. Permission ---------------------------------------------------------
        if request.action_type in p.hard_blocked:
            record(2, False, f"hard-blocked action: {p.hard_blocked[request.action_type]}")
        elif spec is None:
            record(2, False, "unknown action type (fails closed)")
        elif agent is None:
            record(2, False, "no agent to check")
        else:
            held = agent.permissions.get(spec.domain, "none")
            if LEVEL_ORDER.get(held, 0) >= LEVEL_ORDER[spec.level]:
                record(2, True, f"holds '{held}' on '{spec.domain}' (needs '{spec.level}')")
            else:
                record(2, False, f"holds '{held}' on '{spec.domain}', needs '{spec.level}'")

        # 3. Risk classification --------------------------------------------------
        injection = scan_injection(request.params, p.injection_markers)
        if spec is None:
            tier = str(p.unknown_action.get("tier", "critical"))
            factors.append("unknown action: fail-closed tier")
            record(3, False, f"unclassifiable; assigned '{tier}'")
        else:
            tier = spec.tier
            acting = LEVEL_ORDER[spec.level] >= LEVEL_ORDER["write"]
            mods = p.escalation_modifiers
            env_mod = mods.get("production_environment", {})
            if acting and env_mod and request.params.get(env_mod.get("param", "environment")) == env_mod.get("equals"):
                tier = max_tier(tier, env_mod.get("min_tier", "critical"))
                factors.append("targets production")
            rec_mod = mods.get("external_recipients", {})
            if acting and rec_mod and request.params.get(rec_mod.get("param", "recipients")):
                tier = max_tier(tier, rec_mod.get("min_tier", "high"))
                factors.append("has external recipients")
            bulk_mod = mods.get("bulk_records", {})
            count = request.params.get(bulk_mod.get("param", "record_count"), 0)
            if bulk_mod and isinstance(count, int) and count > int(bulk_mod.get("greater_than", 1000)):
                tier = bump_tier(tier, int(bulk_mod.get("bump", 1)))
                factors.append(f"bulk operation ({count} records)")
            if spec.external:
                factors.append("external effect")
            if injection:
                # Injection forces human review (step 6). It raises the tier only if the policy says so.
                inj_tier = mods.get("untrusted_injection", {}).get("min_tier")
                if inj_tier:
                    tier = max_tier(tier, inj_tier)
                factors.append(f"instruction-like text in inputs: {', '.join(injection)}")
            record(3, True, f"tier '{tier}'" + (f" ({'; '.join(factors)})" if factors else ""))
        score = min(100, p.tier_score(tier) + (10 if injection else 0) + (3 if spec and spec.external else 0))

        # 4. Policy evaluation ----------------------------------------------------
        policy_problems: list[str] = []
        if request.action_type in p.hard_blocked:
            policy_problems.append(p.hard_blocked[request.action_type])
        if spec is None:
            policy_problems.append(str(p.unknown_action.get("reason", "unknown action")))
        if agent is not None and spec is not None:
            rules = p.department_rules.get(agent.department, {})
            allowed = rules.get("allowed_actions")
            if allowed is not None and request.action_type not in allowed:
                policy_problems.append(f"department '{agent.department}': {rules.get('reason', 'action not allowed')}")
            flag = (rules.get("required_param_flags") or {}).get(request.action_type)
            if flag and not request.params.get(flag):
                policy_problems.append(f"department '{agent.department}' requires param '{flag}'")
        if spec is not None:
            if spec.sandbox_only and not request.sandbox:
                policy_problems.append("sandbox-only action requested outside the sandbox")
            if request.sandbox and spec.external:
                policy_problems.append("the sandbox cannot reach external systems")
            if spec.lawful_sources_only:
                source = request.params.get("source")
                if source not in state.approved_sources:
                    policy_problems.append(f"source '{source}' is not on the approved-sources list")
            missing = [k for k in p.required_plans(tier) if not str(request.params.get(k) or "").strip()]
            if missing:
                policy_problems.append(f"{tier} action missing {', '.join(missing)}")
        record(4, not policy_problems, "; ".join(policy_problems) or "no rule violated")

        # 5. Tool capability ----------------------------------------------------
        tool_id: str | None = None
        if spec is None or agent is None:
            record(5, False, "no capability to resolve")
        else:
            candidates = [request.tool_id] if request.tool_id else agent.tools
            match = [
                t for t in candidates if t in agent.tools and t in tools and request.action_type in tools[t].actions
            ]
            if not match:
                record(5, False, f"no granted tool declares '{request.action_type}'")
            else:
                tool = tools[match[0]]
                tool_id = tool.id
                if TIER_ORDER[tool.risk_ceiling] < TIER_ORDER[tier]:
                    record(5, False, f"tool '{tool.id}' ceiling '{tool.risk_ceiling}' is below tier '{tier}'")
                elif tool.sandbox_only and not request.sandbox:
                    record(5, False, f"tool '{tool.id}' is sandbox-only")
                else:
                    record(5, True, f"tool '{tool.id}' ({tool.connector}) declares the action")

        # 6. Human approval requirement ----------------------------------------
        needs_approval = p.tier_requires_approval(tier) or bool(injection)
        failed = any(not s.passed for s in steps)
        if failed:
            outcome = "deny"
            steps.append(StepResult(6, STEP_NAMES[5], False, "not reached: an earlier step failed", "skipped"))
        elif needs_approval:
            outcome = "approval_required"
            why = (
                f"tier '{tier}' requires operator approval"
                if p.tier_requires_approval(tier)
                else "suspected instruction injection requires operator review"
            )
            steps.append(StepResult(6, STEP_NAMES[5], True, why))
            reasons.append(why)
        else:
            outcome = "allow"
            steps.append(StepResult(6, STEP_NAMES[5], True, f"tier '{tier}' auto-executes"))

        return GateDecision(
            outcome=outcome,
            action_type=request.action_type,
            agent_id=request.agent_id,
            tier=tier,
            score=score,
            tool_id=tool_id,
            digest=digest(request.binding(tool_id)),
            policy_version=p.version,
            steps=steps,
            reasons=reasons,
            factors=factors,
            injection_suspected=bool(injection),
            external=bool(spec and spec.external),
        )
