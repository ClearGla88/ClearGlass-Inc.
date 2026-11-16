"""Detector safety contracts (SPEC section 7).

A contract is data reviewed by a person. Nothing here supplies default
thresholds, timing budgets or acceptance criteria: the spec forbids inventing
universal targets, so every value must come from the documented review. A
detector whose contract has any gap cannot be promoted to VALIDATED.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any

from .errors import HazardError
from .hazards import HazardKind

TEXT_FIELDS = ("detector_id", "intended_use", "trigger_rule", "clearing_rule",
               "alert_template_id", "false_alert_criterion", "missed_event_criterion",
               "degraded_behavior", "owner", "reviewer")
LIST_FIELDS = ("required_inputs", "operating_conditions", "known_failure_modes", "test_evidence")
NUMBER_FIELDS = ("max_event_age_s", "timing_budget_ms")


@dataclass(frozen=True)
class DetectorContract:
    detector_id: str | None = None
    hazard: HazardKind | None = None
    intended_use: str | None = None
    required_inputs: tuple[str, ...] = ()
    quality_limits: tuple[tuple[str, str], ...] = ()
    operating_conditions: tuple[str, ...] = ()
    known_failure_modes: tuple[str, ...] = ()
    trigger_rule: str | None = None
    clearing_rule: str | None = None
    max_event_age_s: float | None = None
    timing_budget_ms: float | None = None
    alert_template_id: str | None = None
    false_alert_criterion: str | None = None
    missed_event_criterion: str | None = None
    degraded_behavior: str | None = None
    test_evidence: tuple[str, ...] = ()
    owner: str | None = None
    reviewer: str | None = None
    confidence_calibrated: bool = False


def from_dict(raw: Any) -> DetectorContract:
    if not isinstance(raw, dict):
        raise HazardError("contract must be an object")
    known = {f.name for f in fields(DetectorContract)}
    unknown = set(raw) - known
    if unknown:
        raise HazardError(f"contract has unknown field(s) {sorted(unknown)}")
    data = dict(raw)
    if data.get("hazard") is not None:
        try:
            data["hazard"] = HazardKind(data["hazard"])
        except ValueError:
            raise HazardError(f"unsupported hazard category: {data['hazard']!r}") from None
    for name in LIST_FIELDS:
        if name in data:
            data[name] = tuple(data[name])
    if "quality_limits" in data:
        if not isinstance(data["quality_limits"], dict):
            raise HazardError("quality_limits must be an object")
        data["quality_limits"] = tuple(sorted((str(k), str(v)) for k, v in data["quality_limits"].items()))
    if "confidence_calibrated" in data and not isinstance(data["confidence_calibrated"], bool):
        raise HazardError("confidence_calibrated must be true or false")
    return DetectorContract(**data)


def missing(contract: DetectorContract, known_templates: set[str] | None = None) -> list[str]:
    """Names of contract requirements that are absent or unusable."""
    gaps = []
    if contract.hazard is None:
        gaps.append("hazard")
    for name in TEXT_FIELDS:
        value = getattr(contract, name)
        if not isinstance(value, str) or not value.strip():
            gaps.append(name)
    for name in LIST_FIELDS:
        value = getattr(contract, name)
        if not value or not all(isinstance(v, str) and v.strip() for v in value):
            gaps.append(name)
    if not contract.quality_limits:
        gaps.append("quality_limits")
    for name in NUMBER_FIELDS:
        value = getattr(contract, name)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            gaps.append(name)
    if (known_templates is not None and isinstance(contract.alert_template_id, str)
            and contract.alert_template_id.strip() and contract.alert_template_id not in known_templates):
        gaps.append("alert_template_id (not an approved template)")
    if (isinstance(contract.owner, str) and isinstance(contract.reviewer, str)
            and contract.owner.strip() and contract.owner == contract.reviewer):
        gaps.append("reviewer (must differ from owner)")
    return gaps
