"""Deterministic risk classification (gate stage 3).

The base risk comes from the operation the tool declares; contextual factors
can only raise it. The same request always classifies the same way, and an
operation a tool does not declare classifies as critical (fail closed).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import RiskLevel

SENSITIVE_CLASSIFICATIONS = frozenset({"confidential", "pii", "secret", "regulated"})


@dataclass(frozen=True)
class RiskAssessment:
    level: RiskLevel
    reasons: list[str] = field(default_factory=list)


def classify(tool: dict[str, Any], action: str, payload: dict[str, Any]) -> RiskAssessment:
    operations = (tool.get("capability_surface") or {}).get("operations", {})
    op = operations.get(action)
    if not op:
        return RiskAssessment(RiskLevel.CRITICAL, [f"operation {action!r} not declared by tool"])
    try:
        level = RiskLevel(op.get("risk", "critical"))
    except ValueError:
        return RiskAssessment(RiskLevel.CRITICAL, ["tool declares an unknown risk level"])
    reasons = [f"{tool['key']}.{action} declares {level.value}"]

    if tool.get("environment") == "production" and level.rank < RiskLevel.HIGH.rank:
        level = RiskLevel.HIGH
        reasons.append("production environment raises risk to high")
    if payload.get("external") is True:
        level = level.at_least(RiskLevel.HIGH)
        reasons.append("external exposure")
    if str(payload.get("data_classification", "internal")).lower() in SENSITIVE_CLASSIFICATIONS:
        level = level.at_least(RiskLevel.HIGH)
        reasons.append("sensitive data classification")
    if payload.get("reversible") is False:
        level = level.at_least(RiskLevel.HIGH)
        reasons.append("irreversible action")
    try:
        amount = int(payload.get("amount_cents", 0) or 0)
    except (TypeError, ValueError):
        return RiskAssessment(RiskLevel.CRITICAL, reasons + ["amount_cents is not an integer"])
    if amount > 0:
        level = RiskLevel.CRITICAL
        reasons.append("moves money")
    return RiskAssessment(level, reasons)
