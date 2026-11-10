"""The governance gate: steps 1-6 of the nine-step action pipeline.

``PolicyEngine.evaluate`` is pure. It reads the request, the agent, the tool
registry, and the office state, and returns a ``GateDecision``; it never
executes anything and never writes. That makes it safe to call from control
tests, the ``/policy/evaluate`` dry-run endpoint, and simulations.

Pipeline (steps 7-9 live in ``agent_core.governance``):

1. Identity check        - agent registered and active, office not halted, mission active
2. Permission check      - grant level >= required, not revoked or expired, constraints met
3. Risk classification   - catalog tier + escalation modifiers (only raise) + injection scan
4. Policy evaluation     - hard blocks, department rules, sandbox and simulation rules,
                           critical plans, approved sources, deploy test evidence
5. Tool-capability check - a granted tool declares the action and its ceiling covers the tier
6. Human approval        - required for high/critical or suspected injection
7. Execution             - tool handler (internal or dry-run connector)
8. Verification          - output checked against the action's verify rule
9. Audit                 - every step above is sealed into the hash chain

Every step is evaluated even after a failure, so the trace shown to the
operator is complete. Shadow rules (config/policy.shadow.json) are evaluated
last and reported as ``shadow_outcome``; they never change ``outcome``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

from agent_core.models import LEVEL_ORDER, TIER_ORDER, Agent, Tool, bump_tier, max_tier
from agent_core.util import parse_iso
from audit_ledger.canonical import digest
from policy_engine.policy import Policy, ShadowRule

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
    idempotency_key: str | None = None

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
    shadow_outcome: str | None = None
    shadow_rules: list[str] = field(default_factory=list)

    @property
    def allowed(self) -> bool:
        return self.outcome == "allow"

    @property
    def shadow_diverged(self) -> bool:
        return self.shadow_outcome is not None and self.shadow_outcome != self.outcome

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GrantView:
    """The parts of a permission grant the gate enforces."""

    level: str
    constraints: Mapping[str, Any] = field(default_factory=dict)
    expires_at: str | None = None
    revoked_at: str | None = None


@dataclass(frozen=True)
class MissionView:
    id: str
    status: str  # active | paused | cancelled | completed
    mode: str = "production"  # production | simulation


@dataclass(frozen=True)
class OfficeState:
    halted: bool = False
    halted_reason: str | None = None
    approved_sources: tuple[str, ...] = ()
    now: str = ""
    mission: MissionView | None = None
    # Completed sandbox test runs in the request's mission: task id -> {"passed": bool, ...}
    test_runs: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)


OUTCOME_ORDER = {"allow": 0, "approval_required": 1, "deny": 2}
PRODUCTION_PARAMS = ("environment", "target_environment")


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


def _is_amount(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def grant_violation(grant: GrantView, params: Mapping[str, Any]) -> str:
    """Check a grant's constraints against the request parameters. Empty string means compliant."""
    limit = grant.constraints.get("spend_limit_cents")
    if limit is not None:
        amount = params.get("amount_cents", 0)
        if not _is_amount(amount):
            return "amount_cents must be a non-negative integer"
        if amount > int(limit):
            return f"amount_cents {amount} exceeds the grant's spend limit of {int(limit)}"
    for name, allowed in (grant.constraints.get("payload_allowlist") or {}).items():
        if name not in params:
            return f"'{name}' is required by the grant's allow-list"
        value = params[name]
        values = value if isinstance(value, (list, tuple)) else [value]
        if not values:
            return f"'{name}' is empty"
        outside = [v for v in values if v not in allowed]
        if outside:
            return f"'{name}' value(s) {outside} are not on the grant's allow-list"
    return ""


def _shadow_matches(rule: ShadowRule, request: ActionRequest, spec: Any, agent: Agent | None, tier: str) -> bool:
    w = rule.when
    if "action_types" in w and request.action_type not in w["action_types"]:
        return False
    if "domains" in w and (spec is None or spec.domain not in w["domains"]):
        return False
    if "departments" in w and (agent is None or agent.department not in w["departments"]):
        return False
    if "min_tier" in w and TIER_ORDER[tier] < TIER_ORDER[w["min_tier"]]:
        return False
    if "external" in w and bool(spec and spec.external) != bool(w["external"]):
        return False
    for name, value in (w.get("param_equals") or {}).items():
        if request.params.get(name) != value:
            return False
    for name, value in (w.get("param_greater_than") or {}).items():
        actual = request.params.get(name)
        if not (isinstance(actual, int) and not isinstance(actual, bool) and actual > value):
            return False
    return True


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
        grants: Mapping[str, GrantView] | None = None,
    ) -> GateDecision:
        p = self.policy
        spec = p.spec(request.action_type)
        grants = grants or {}
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
        elif request.mission_id and state.mission is None:
            record(1, False, f"unknown mission '{request.mission_id}'")
        elif state.mission is not None and state.mission.status != "active":
            record(1, False, f"mission {state.mission.id} is {state.mission.status}")
        else:
            mission = f" on mission {state.mission.id} ({state.mission.mode})" if state.mission else ""
            record(1, True, f"{agent.callsign} {agent.name} is registered and active{mission}")

        # 2. Permission ---------------------------------------------------------
        if request.action_type in p.hard_blocked:
            record(2, False, f"hard-blocked action: {p.hard_blocked[request.action_type]}")
        elif spec is None:
            record(2, False, "unknown action type (fails closed)")
        elif agent is None:
            record(2, False, "no agent to check")
        else:
            held = agent.permissions.get(spec.domain, "none")
            grant = grants.get(spec.domain)
            expired = bool(
                grant and grant.expires_at and state.now and parse_iso(grant.expires_at) <= parse_iso(state.now)
            )
            if grant and grant.revoked_at:
                record(2, False, f"grant on '{spec.domain}' was revoked at {grant.revoked_at}")
            elif expired:
                record(2, False, f"grant on '{spec.domain}' expired at {grant.expires_at}")  # type: ignore[union-attr]
            elif LEVEL_ORDER.get(held, 0) < LEVEL_ORDER[spec.level]:
                record(2, False, f"holds '{held}' on '{spec.domain}', needs '{spec.level}'")
            else:
                violation = grant_violation(grant, request.params) if grant else ""
                if violation:
                    record(2, False, f"grant constraint on '{spec.domain}': {violation}")
                else:
                    limits = " within grant limits" if grant and grant.constraints else ""
                    record(2, True, f"holds '{held}' on '{spec.domain}' (needs '{spec.level}'){limits}")

        # 3. Risk classification --------------------------------------------------
        injection = scan_injection(request.params, p.injection_markers)
        bad_amount = "amount_cents" in request.params and not _is_amount(request.params["amount_cents"])
        if spec is None:
            tier = str(p.unknown_action.get("tier", "critical"))
            factors.append("unknown action: fail-closed tier")
            record(3, False, f"unclassifiable; assigned '{tier}'")
        else:
            tier = spec.tier
            acting = LEVEL_ORDER[spec.level] >= LEVEL_ORDER["write"]
            for mod in p.modifiers:
                if mod.applies_to == "acting" and not acting:
                    continue
                if not mod.matches(request.params):
                    continue
                tier = max_tier(tier, mod.min_tier) if mod.min_tier else bump_tier(tier, mod.bump)
                factors.append(mod.factor)
            if bad_amount:
                tier = "critical"
                factors.append("amount_cents is not a non-negative integer")
            if spec.external:
                factors.append("external effect")
            if injection:
                # Injection forces human review (step 6); it never lowers or replaces the tier.
                factors.append(f"instruction-like text in inputs: {', '.join(injection)}")
            record(3, True, f"tier '{tier}'" + (f" ({'; '.join(factors)})" if factors else ""))
        score = min(100, p.tier_score(tier) + (10 if injection else 0) + (3 if spec and spec.external else 0))

        # 4. Policy evaluation ----------------------------------------------------
        policy_problems: list[str] = []
        if request.action_type in p.hard_blocked:
            policy_problems.append(p.hard_blocked[request.action_type])
        if spec is None:
            policy_problems.append(str(p.unknown_action.get("reason", "unknown action")))
        if bad_amount:
            policy_problems.append("amount_cents must be a non-negative integer")
        if agent is not None and spec is not None:
            rules = p.department_rules.get(agent.department, {})
            allowed = rules.get("allowed_actions")
            if allowed is not None and request.action_type not in allowed:
                policy_problems.append(f"department '{agent.department}': {rules.get('reason', 'action not allowed')}")
            flag = (rules.get("required_param_flags") or {}).get(request.action_type)
            if flag and not request.params.get(flag):
                policy_problems.append(f"department '{agent.department}' requires param '{flag}'")
        if spec is not None:
            acting = LEVEL_ORDER[spec.level] >= LEVEL_ORDER["write"]
            if spec.sandbox_only and not request.sandbox:
                policy_problems.append("sandbox-only action requested outside the sandbox")
            if request.sandbox and spec.external:
                policy_problems.append("the sandbox cannot reach external systems")
            if state.mission is not None and state.mission.mode == "simulation" and acting:
                targets_prod = any(request.params.get(k) == "production" for k in PRODUCTION_PARAMS)
                if spec.external or targets_prod:
                    policy_problems.append("a simulation mission cannot take external or production actions")
            if spec.lawful_sources_only:
                source = request.params.get("source")
                if source not in state.approved_sources:
                    policy_problems.append(f"source '{source}' is not on the approved-sources list")
            if spec.requires_test_evidence:
                evidence = request.params.get("test_evidence")
                run = state.test_runs.get(evidence) if isinstance(evidence, str) else None
                if not request.mission_id:
                    policy_problems.append("needs a mission with a passing sandbox test run")
                elif run is None:
                    policy_problems.append(f"test_evidence {evidence!r} is not a sandbox test run in this mission")
                elif not run.get("passed"):
                    policy_problems.append(f"sandbox test run {evidence} did not pass")
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

        # Shadow rules: evaluated and reported, never enforced.
        shadow_outcome: str | None = None
        matched: list[str] = []
        if p.shadow_rules:
            shadow_outcome = outcome
            for rule in p.shadow_rules:
                if _shadow_matches(rule, request, spec, agent, tier):
                    matched.append(rule.id)
                    if OUTCOME_ORDER[rule.effect] > OUTCOME_ORDER[shadow_outcome]:
                        shadow_outcome = rule.effect

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
            shadow_outcome=shadow_outcome,
            shadow_rules=matched,
        )
