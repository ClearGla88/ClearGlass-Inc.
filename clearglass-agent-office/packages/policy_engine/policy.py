"""Load and validate the policy-as-code files.

- ``config/policy.json``: the enforced policy.
- ``config/policy.shadow.json`` (optional): candidate rules that are evaluated
  and logged on every request but never enforced.

Validation fails loudly at startup: a malformed policy must stop the office,
never fall back to a permissive default.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_core.models import LEVEL_ORDER, TIER_ORDER


class PolicyError(ValueError):
    """The policy file is malformed or internally inconsistent."""


@dataclass(frozen=True)
class ActionSpec:
    action_type: str
    domain: str
    level: str
    tier: str
    verify: str = "artifact"
    external: bool = False
    sandbox_only: bool = False
    lawful_sources_only: bool = False
    untrusted_input: bool = False
    requires_test_evidence: bool = False


MODIFIER_OPS = ("equals", "in", "non_empty", "greater_than")
MODIFIER_SCOPES = ("acting", "all")


@dataclass(frozen=True)
class Modifier:
    """Raise an action's tier when one parameter matches. Modifiers can only raise risk."""

    id: str
    param: str
    op: str
    value: Any
    applies_to: str  # "acting" (write/execute actions) or "all"
    factor: str
    min_tier: str | None = None
    bump: int = 0

    def matches(self, params: dict[str, Any]) -> bool:
        if self.param not in params:
            return False
        actual = params[self.param]
        if self.op == "equals":
            return actual == self.value and type(actual) is type(self.value)
        if self.op == "in":
            return isinstance(actual, str) and actual.lower() in self.value
        if self.op == "non_empty":
            return bool(actual)
        if self.op == "greater_than":
            return isinstance(actual, int) and not isinstance(actual, bool) and actual > self.value
        return False


SHADOW_EFFECTS = ("approval_required", "deny")
SHADOW_CONDITIONS = (
    "action_types",
    "domains",
    "departments",
    "min_tier",
    "external",
    "param_equals",
    "param_greater_than",
)


@dataclass(frozen=True)
class ShadowRule:
    """A candidate rule: matched requests are logged with the outcome it would have forced."""

    id: str
    description: str
    effect: str
    when: dict[str, Any]


@dataclass(frozen=True)
class Policy:
    version: str
    tiers: dict[str, dict[str, Any]]
    approval: dict[str, Any]
    actions: dict[str, ActionSpec]
    hard_blocked: dict[str, str]
    department_rules: dict[str, dict[str, Any]]
    modifiers: tuple[Modifier, ...]
    injection_markers: tuple[str, ...]
    unknown_action: dict[str, Any]
    shadow_rules: tuple[ShadowRule, ...] = ()
    shadow_version: str | None = None
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    def spec(self, action_type: str) -> ActionSpec | None:
        return self.actions.get(action_type)

    def tier_score(self, tier: str) -> int:
        return int(self.tiers[tier]["score"])

    def tier_requires_approval(self, tier: str) -> bool:
        return self.tiers[tier].get("approval", "none") != "none"

    def required_plans(self, tier: str) -> tuple[str, ...]:
        return tuple(self.tiers[tier].get("requires", ()))

    @property
    def approval_ttl_hours(self) -> int:
        return int(self.approval.get("ttl_hours", 72))

    @property
    def min_reason_chars(self) -> int:
        return int(self.approval.get("min_reason_chars", 12))

    @property
    def approver_roles(self) -> tuple[str, ...]:
        return tuple(self.approval.get("approver_roles", ("operator",)))


def load_policy(path: str | Path, shadow_path: str | Path | None = None) -> Policy:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    shadow = None
    if shadow_path is not None and Path(shadow_path).exists():
        shadow = json.loads(Path(shadow_path).read_text(encoding="utf-8"))
    return parse_policy(raw, shadow)


def _parse_modifiers(entries: Any, problems: list[str]) -> tuple[Modifier, ...]:
    if not isinstance(entries, list):
        problems.append("escalation_modifiers must be a list")
        return ()
    out: list[Modifier] = []
    for i, m in enumerate(entries):
        mid = str(m.get("id") or f"#{i}")
        op = m.get("op")
        if op not in MODIFIER_OPS:
            problems.append(f"modifier {mid}: op must be one of {MODIFIER_OPS}")
        if m.get("applies_to") not in MODIFIER_SCOPES:
            problems.append(f"modifier {mid}: applies_to must be one of {MODIFIER_SCOPES}")
        if not m.get("param"):
            problems.append(f"modifier {mid}: param is required")
        has_min, has_bump = "min_tier" in m, "bump" in m
        if has_min == has_bump:
            problems.append(f"modifier {mid}: set exactly one of min_tier or bump")
        if has_min and m["min_tier"] not in TIER_ORDER:
            problems.append(f"modifier {mid}: invalid min_tier {m['min_tier']!r}")
        if has_bump and (not isinstance(m["bump"], int) or m["bump"] < 1):
            problems.append(f"modifier {mid}: bump must be a positive integer")
        value = m.get("value")
        if op == "in":
            if not isinstance(value, list) or not value:
                problems.append(f"modifier {mid}: 'in' needs a non-empty list")
            else:
                value = tuple(str(v).lower() for v in value)
        if op == "greater_than" and (not isinstance(value, int) or isinstance(value, bool)):
            problems.append(f"modifier {mid}: 'greater_than' needs an integer")
        out.append(
            Modifier(
                id=mid,
                param=str(m.get("param", "")),
                op=str(op),
                value=value,
                applies_to=str(m.get("applies_to")),
                factor=str(m.get("factor") or mid),
                min_tier=m.get("min_tier"),
                bump=int(m.get("bump", 0) or 0),
            )
        )
    return tuple(out)


def _parse_shadow(raw: dict[str, Any] | None, problems: list[str]) -> tuple[tuple[ShadowRule, ...], str | None]:
    if raw is None:
        return (), None
    rules: list[ShadowRule] = []
    seen: set[str] = set()
    for i, r in enumerate(raw.get("rules", [])):
        rid = str(r.get("id") or "")
        if not rid or rid in seen:
            problems.append(f"shadow rule #{i}: id missing or duplicated")
        seen.add(rid)
        if r.get("effect") not in SHADOW_EFFECTS:
            problems.append(f"shadow rule {rid}: effect must be one of {SHADOW_EFFECTS}")
        when = r.get("when") or {}
        if not when:
            problems.append(f"shadow rule {rid}: 'when' must name at least one condition")
        unknown = set(when) - set(SHADOW_CONDITIONS)
        if unknown:
            problems.append(f"shadow rule {rid}: unknown conditions {sorted(unknown)}")
        if "min_tier" in when and when["min_tier"] not in TIER_ORDER:
            problems.append(f"shadow rule {rid}: invalid min_tier")
        rules.append(ShadowRule(rid, str(r.get("description", "")), str(r.get("effect")), dict(when)))
    return tuple(rules), str(raw.get("shadow_version") or "unversioned")


def parse_policy(raw: dict[str, Any], shadow: dict[str, Any] | None = None) -> Policy:
    problems: list[str] = []
    version = raw.get("policy_version")
    if not isinstance(version, str) or not version:
        problems.append("policy_version must be a non-empty string")

    tiers = raw.get("tiers", {})
    if set(tiers) != set(TIER_ORDER):
        problems.append(f"tiers must be exactly {sorted(TIER_ORDER)}")
    for name in ("high", "critical"):
        if tiers.get(name, {}).get("approval") in (None, "none"):
            problems.append(f"tier '{name}' must require approval")
    if not tiers.get("critical", {}).get("requires"):
        problems.append("critical tier must list required plans")

    actions: dict[str, ActionSpec] = {}
    for action_type, spec in (raw.get("actions") or {}).items():
        level = spec.get("level")
        tier = spec.get("tier")
        if level not in LEVEL_ORDER or level == "none":
            problems.append(f"{action_type}: invalid level {level!r}")
        if tier not in TIER_ORDER:
            problems.append(f"{action_type}: invalid tier {tier!r}")
        if spec.get("external") and tier in ("low", "medium"):
            problems.append(f"{action_type}: external actions must be high or critical")
        if spec.get("domain") == "finance" and tier != "critical":
            problems.append(f"{action_type}: payment and finance actions must be critical")
        if action_type in (raw.get("hard_blocked") or {}):
            problems.append(f"{action_type}: listed as both allowed and hard-blocked")
        actions[action_type] = ActionSpec(
            action_type=action_type,
            domain=str(spec.get("domain", "")),
            level=str(level),
            tier=str(tier),
            verify=str(spec.get("verify", "artifact")),
            external=bool(spec.get("external", False)),
            sandbox_only=bool(spec.get("sandbox_only", False)),
            lawful_sources_only=bool(spec.get("lawful_sources_only", False)),
            untrusted_input=bool(spec.get("untrusted_input", False)),
            requires_test_evidence=bool(spec.get("requires_test_evidence", False)),
        )
    if not actions:
        problems.append("actions must not be empty")
    if "deploy.production" in actions and not actions["deploy.production"].requires_test_evidence:
        problems.append("deploy.production must require test evidence")

    unknown = raw.get("unknown_action") or {}
    if unknown.get("decision") != "deny":
        problems.append("unknown_action.decision must be 'deny' (fail closed)")

    approval = raw.get("approval") or {}
    if "operator" not in approval.get("approver_roles", []):
        problems.append("approval.approver_roles must include 'operator'")
    if not approval.get("bind_to_payload", False):
        problems.append("approval.bind_to_payload must be true")

    untrusted = raw.get("untrusted_input") or {}
    markers = tuple(m.lower() for m in untrusted.get("markers", []))
    if not markers:
        problems.append("untrusted_input.markers must not be empty")
    if untrusted.get("force_approval") is not True:
        problems.append("untrusted_input.force_approval must be true")

    modifiers = _parse_modifiers(raw.get("escalation_modifiers", []), problems)
    shadow_rules, shadow_version = _parse_shadow(shadow, problems)

    if problems:
        raise PolicyError("; ".join(problems))

    return Policy(
        version=str(version),
        tiers=tiers,
        approval=approval,
        actions=actions,
        hard_blocked=dict(raw.get("hard_blocked") or {}),
        department_rules=dict(raw.get("department_rules") or {}),
        modifiers=modifiers,
        injection_markers=markers,
        unknown_action=unknown,
        shadow_rules=shadow_rules,
        shadow_version=shadow_version,
        raw=raw,
    )
