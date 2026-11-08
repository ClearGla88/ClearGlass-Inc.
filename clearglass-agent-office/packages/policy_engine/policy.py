"""Load and validate the policy-as-code file (config/policy.json).

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


@dataclass(frozen=True)
class Policy:
    version: str
    tiers: dict[str, dict[str, Any]]
    approval: dict[str, Any]
    actions: dict[str, ActionSpec]
    hard_blocked: dict[str, str]
    department_rules: dict[str, dict[str, Any]]
    escalation_modifiers: dict[str, dict[str, Any]]
    injection_markers: tuple[str, ...]
    unknown_action: dict[str, Any]
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


def load_policy(path: str | Path) -> Policy:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return parse_policy(raw)


def parse_policy(raw: dict[str, Any]) -> Policy:
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
        )
    if not actions:
        problems.append("actions must not be empty")

    unknown = raw.get("unknown_action") or {}
    if unknown.get("decision") != "deny":
        problems.append("unknown_action.decision must be 'deny' (fail closed)")

    approval = raw.get("approval") or {}
    if "operator" not in approval.get("approver_roles", []):
        problems.append("approval.approver_roles must include 'operator'")
    if not approval.get("bind_to_payload", False):
        problems.append("approval.bind_to_payload must be true")

    markers = tuple(m.lower() for m in (raw.get("untrusted_input") or {}).get("markers", []))
    if not markers:
        problems.append("untrusted_input.markers must not be empty")

    if problems:
        raise PolicyError("; ".join(problems))

    return Policy(
        version=str(version),
        tiers=tiers,
        approval=approval,
        actions=actions,
        hard_blocked=dict(raw.get("hard_blocked") or {}),
        department_rules=dict(raw.get("department_rules") or {}),
        escalation_modifiers=dict(raw.get("escalation_modifiers") or {}),
        injection_markers=markers,
        unknown_action=unknown,
        raw=raw,
    )
