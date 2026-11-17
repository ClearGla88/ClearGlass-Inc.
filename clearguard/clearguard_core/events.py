"""Hazard events (spec section 6): facts, inferences, unknowns, alternatives and
limitations kept apart, only supported categories, and no inference of intent,
weapons, substances or medical state."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum

from .timeutil import parse_time


class Priority(IntEnum):
    ADVISORY = 1
    WARNING = 2
    CRITICAL = 3


CATEGORIES = {
    "obstacle_ahead",
    "device_fall_event",
    "official_emergency_warning",
    "missed_check_in",
    "explicit_help_request",
    "monitoring_capability_lost",
}
# Raised by the application itself (a command, a timer, the health supervisor),
# so they cite application state rather than sensor observations.
APP_SOURCED = {"missed_check_in", "explicit_help_request", "monitoring_capability_lost"}

# Claims this system has no validated instrument for. Checked in facts and
# inferences; unknowns may say what cannot be determined.
PROHIBITED_CLAIMS = re.compile(
    r"\b(hostile|intent|intentions?|weapons?|guns?|knife|knives|armed|being followed|"
    r"following (?:you|the user|sir)|stalk\w*|surveil\w*|suspicious (?:person|man|woman|individual)|"
    r"toxic|chemical|radiation|radioactive|explosives?|bombs?|diagnos\w*|seizure|stroke|"
    r"heart attack|unconscious|attacker|threat score)\b",
    re.IGNORECASE,
)

EVENT_FIELDS = (
    "event_id", "detector_id", "category", "priority", "created_at", "expires_at", "observation_ids",
    "observed_facts", "inferences", "unknowns", "alternatives", "limitations",
)
OPTIONAL_FIELDS = ("confidence", "calibrated")


@dataclass(frozen=True)
class HazardEvent:
    event_id: str
    detector_id: str
    category: str
    priority: Priority
    created_at: datetime
    expires_at: datetime
    observation_ids: tuple[str, ...]
    observed_facts: tuple[str, ...]
    inferences: tuple[str, ...] = ()
    unknowns: tuple[str, ...] = ()
    alternatives: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    confidence: float | None = None
    calibrated: bool = False
    extra: dict = field(default_factory=dict, compare=False)


def _str_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(x, str) for x in value)


def parse_event(raw: object) -> tuple[HazardEvent | None, list[str]]:
    if not isinstance(raw, dict):
        return None, ["event must be an object"]
    problems = [f"missing {name}" for name in EVENT_FIELDS if name not in raw]
    problems += [f"unknown field {k}" for k in sorted(set(raw) - set(EVENT_FIELDS) - set(OPTIONAL_FIELDS))]
    if problems:
        return None, problems
    if raw["category"] not in CATEGORIES:
        problems.append(f"unsupported hazard category '{raw['category']}'")
    if raw["priority"] not in Priority.__members__:
        problems.append("priority must be CRITICAL, WARNING or ADVISORY")
    for name in ("observation_ids", "observed_facts", "inferences", "unknowns", "alternatives", "limitations"):
        if not _str_list(raw[name]):
            problems.append(f"{name} must be a list of strings")
    for name in ("event_id", "detector_id"):
        if not isinstance(raw[name], str) or not raw[name]:
            problems.append(f"{name} must be a non-empty string")
    times = {}
    for name in ("created_at", "expires_at"):
        try:
            times[name] = parse_time(raw[name])
        except ValueError as exc:
            problems.append(f"{name}: {exc}")
    confidence = raw.get("confidence")
    if confidence is not None and (
        isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1
    ):
        problems.append("confidence must be a number from 0 to 1, or absent")
    if not isinstance(raw.get("calibrated", False), bool):
        problems.append("calibrated must be true or false")
    if problems:
        return None, problems
    event = HazardEvent(
        event_id=raw["event_id"], detector_id=raw["detector_id"], category=raw["category"],
        priority=Priority[raw["priority"]], created_at=times["created_at"], expires_at=times["expires_at"],
        observation_ids=tuple(raw["observation_ids"]), observed_facts=tuple(raw["observed_facts"]),
        inferences=tuple(raw["inferences"]), unknowns=tuple(raw["unknowns"]),
        alternatives=tuple(raw["alternatives"]), limitations=tuple(raw["limitations"]),
        confidence=None if confidence is None else float(confidence),
        calibrated=bool(raw.get("calibrated", False)),
    )
    problems = event_problems(event)
    return (None, problems) if problems else (event, [])


def event_problems(event: HazardEvent) -> list[str]:
    problems: list[str] = []
    if event.category not in CATEGORIES:
        problems.append(f"unsupported hazard category '{event.category}'")
    if event.expires_at <= event.created_at:
        problems.append("expires_at must be after created_at")
    if not event.observed_facts:
        problems.append("an event needs at least one observed fact")
    if event.category not in APP_SOURCED and not event.observation_ids:
        problems.append("a sensor-derived event must cite the observations it rests on")
    if event.confidence is not None and not event.calibrated:
        problems.append("a confidence value is allowed only from a calibrated detector")
    for text in event.observed_facts + event.inferences:
        match = PROHIBITED_CLAIMS.search(text)
        if match:
            problems.append(f"unsupported claim '{match.group(0)}': no validated instrument supports it")
    return problems
