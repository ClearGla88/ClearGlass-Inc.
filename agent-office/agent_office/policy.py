"""Policy-as-code evaluation with AWS Cedar (gate stage 4).

Cedar answers allow or deny. The gate needs a third answer, "allowed only with
a human approval", so a denied request without an approval is evaluated once
more as if a human had approved it as submitted. If that hypothetical passes,
the decision is ``require_approval``; otherwise it is ``deny``.

Fail-closed rules:

* every policy file must type-check against ``schema.cedarschema`` or the
  engine refuses to load;
* every request is validated against the schema; any evaluation error denies;
* any exception from the Cedar engine denies (the circuit breaker never opens
  to "allow").

Shadow mode: policies under ``policies/shadow/`` are evaluated on every request
together with the enforced set. Their effect is recorded, never applied.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from importlib import metadata
from pathlib import Path
from typing import Any

import cedarpy

POLICY_DIR = Path(__file__).with_name("policies")
SCHEMA_FILE = POLICY_DIR / "schema.cedarschema"

ALLOW = "allow"
DENY = "deny"
REQUIRE_APPROVAL = "require_approval"


class PolicyLoadError(RuntimeError):
    pass


@dataclass(frozen=True)
class GateContext:
    risk: str
    approved_by_human: bool
    mission_mode: str = "production"
    external: bool = False
    has_rollback_plan: bool = False
    has_test_evidence: bool = False
    amount_cents: int = 0
    approved_amount_cents: int = 0
    data_classification: str = "internal"

    def as_cedar(self) -> dict[str, Any]:
        return {
            "risk": self.risk,
            "approved_by_human": self.approved_by_human,
            "mission_mode": self.mission_mode,
            "external": self.external,
            "has_rollback_plan": self.has_rollback_plan,
            "has_test_evidence": self.has_test_evidence,
            "amount_cents": int(self.amount_cents),
            "approved_amount_cents": int(self.approved_amount_cents),
            "data_classification": self.data_classification,
        }


@dataclass(frozen=True)
class PolicyDecision:
    effect: str
    policy_ids: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    shadow_effect: str | None = None
    shadow_policy_ids: list[str] = field(default_factory=list)

    @property
    def diverged(self) -> bool:
        return self.shadow_effect is not None and self.shadow_effect != self.effect


class CedarPolicySet:
    def __init__(self, name: str, text: str, schema: str):
        result = cedarpy.validate_policies(text, schema)
        if not result.validation_passed:
            errors = "; ".join(str(e) for e in result.errors)
            raise PolicyLoadError(f"policy set {name!r} failed schema validation: {errors}")
        self.name = name
        self.text = text
        self.schema = schema
        static = json.loads(cedarpy.policies_to_json_str(text)).get("staticPolicies", {})
        self.ids: dict[str, str] = {
            internal: (spec.get("annotations") or {}).get("id", internal)
            for internal, spec in static.items()
        }
        missing = [internal for internal, pid in self.ids.items() if pid == internal]
        if missing:
            raise PolicyLoadError(f"policy set {name!r} has policies without @id: {missing}")

    def evaluate(self, request: dict[str, Any], entities: list[dict[str, Any]]) -> tuple[bool, list[str], list[str]]:
        result = cedarpy.is_authorized(request, self.text, entities, schema=self.schema)
        reasons = [self.ids.get(r, r) for r in result.diagnostics.reasons]
        errors = [str(e) for e in result.diagnostics.errors]
        return bool(result.allowed), sorted(reasons), errors

    def policy_ids(self) -> list[str]:
        return sorted(self.ids.values())


def _cedarpy_version() -> str:
    try:
        return metadata.version("cedarpy")
    except metadata.PackageNotFoundError:
        return "unknown"


def _read_dir(path: Path) -> str:
    files = sorted(path.glob("*.cedar"))
    return "\n".join(f"// --- {f.name}\n" + f.read_text(encoding="utf-8") for f in files)


class PolicyEngine:
    def __init__(self, enforced: CedarPolicySet, shadow: CedarPolicySet | None = None):
        self.enforced = enforced
        self.shadow = shadow

    @classmethod
    def load(cls, policy_dir: Path = POLICY_DIR) -> PolicyEngine:
        schema = (policy_dir / "schema.cedarschema").read_text(encoding="utf-8")
        enforced_text = _read_dir(policy_dir)
        if not enforced_text.strip():
            raise PolicyLoadError("no enforced policies found")
        enforced = CedarPolicySet("enforced", enforced_text, schema)
        shadow = None
        shadow_dir = policy_dir / "shadow"
        if shadow_dir.is_dir() and any(shadow_dir.glob("*.cedar")):
            shadow = CedarPolicySet("shadow", enforced_text + "\n" + _read_dir(shadow_dir), schema)
        return cls(enforced, shadow)

    @staticmethod
    def _entities(agent: dict[str, Any], tool: dict[str, Any], agent_active: bool) -> list[dict[str, Any]]:
        return [
            {
                "uid": {"__entity": {"type": "Agent", "id": agent["id"]}},
                "attrs": {
                    "department": agent.get("department_key", ""),
                    "status": "active" if agent_active else "inactive",
                    "can_request_critical": bool(agent.get("can_request_critical")),
                },
                "parents": [],
            },
            {
                "uid": {"__entity": {"type": "Tool", "id": tool["key"]}},
                "attrs": {
                    "key": tool["key"],
                    "category": tool["category"],
                    "environment": tool["environment"],
                },
                "parents": [],
            },
        ]

    @staticmethod
    def _request(agent_id: str, tool_key: str, action: str, ctx: GateContext) -> dict[str, Any]:
        return {
            "principal": f'Agent::"{agent_id}"',
            "action": f'Action::"{action}"',
            "resource": f'Tool::"{tool_key}"',
            "context": ctx.as_cedar(),
        }

    def _effect(
        self,
        policy_set: CedarPolicySet,
        agent: dict[str, Any],
        tool: dict[str, Any],
        action: str,
        ctx: GateContext,
        agent_active: bool,
    ) -> tuple[str, list[str], list[str]]:
        entities = self._entities(agent, tool, agent_active)
        try:
            allowed, ids, errors = policy_set.evaluate(self._request(agent["id"], tool["key"], action, ctx), entities)
        except Exception as exc:  # circuit breaker: the engine failing never allows
            return DENY, [], [f"policy engine error: {exc}"]
        if errors:
            return DENY, ids, errors
        if allowed:
            return ALLOW, ids, []
        if ctx.approved_by_human:
            return DENY, ids, []
        hypothetical = replace(ctx, approved_by_human=True, approved_amount_cents=ctx.amount_cents)
        try:
            h_allowed, _h_ids, h_errors = policy_set.evaluate(
                self._request(agent["id"], tool["key"], action, hypothetical), entities
            )
        except Exception as exc:
            return DENY, ids, [f"policy engine error: {exc}"]
        if h_allowed and not h_errors:
            return REQUIRE_APPROVAL, ids, []
        return DENY, ids, h_errors

    def decide(
        self,
        agent: dict[str, Any],
        tool: dict[str, Any],
        action: str,
        ctx: GateContext,
        *,
        agent_active: bool = True,
    ) -> PolicyDecision:
        effect, ids, errors = self._effect(self.enforced, agent, tool, action, ctx, agent_active)
        shadow_effect: str | None = None
        shadow_ids: list[str] = []
        if self.shadow is not None:
            shadow_effect, shadow_ids, _ = self._effect(self.shadow, agent, tool, action, ctx, agent_active)
        return PolicyDecision(effect, ids, errors, shadow_effect, shadow_ids)

    def describe(self) -> dict[str, Any]:
        enforced = set(self.enforced.policy_ids())
        shadow_only = sorted(set(self.shadow.policy_ids()) - enforced) if self.shadow else []
        return {
            "engine": "cedar",
            "engine_version": _cedarpy_version(),
            "circuit_breaker": "fail_closed",
            "enforced": sorted(enforced),
            "shadow": shadow_only,
        }
