"""Capability states (spec section 1) and the evidence needed to move between them.

A capability moves up one state at a time, and only with evidence of the kind that
state requires. ACTIVE also needs a live health signal from a host integration,
which this build never has, so nothing here can become ACTIVE.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from enum import IntEnum

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
REGISTRY_PATH = os.path.join(DATA_DIR, "capabilities.json")


class Level(IntEnum):
    REQUESTED = 0
    SPECIFIED = 1
    IMPLEMENTED = 2
    VERIFIED = 3
    VALIDATED = 4
    ACTIVE = 5


# Evidence kind that justifies reaching each state.
EVIDENCE_FOR = {
    Level.SPECIFIED: "requirement",
    Level.IMPLEMENTED: "implementation",
    Level.VERIFIED: "test",
    Level.VALIDATED: "validation",
    Level.ACTIVE: "live_health",
}


@dataclass(frozen=True)
class Evidence:
    kind: str
    reference: str
    recorded_on: str
    reviewer: str | None = None


@dataclass
class Capability:
    cap_id: str
    title: str
    level: Level = Level.REQUESTED
    evidence: list[Evidence] = field(default_factory=list)
    limits: list[str] = field(default_factory=list)

    def promote(self, target: Level, evidence: Evidence, *, live_health_ok: bool = False) -> None:
        """Move up exactly one state. Raises ValueError and changes nothing otherwise."""
        if target != self.level + 1:
            raise ValueError(
                f"{self.cap_id}: cannot move from {self.level.name} to {target.name}; "
                "states are reached one at a time"
            )
        needed = EVIDENCE_FOR[target]
        if evidence.kind != needed:
            raise ValueError(f"{self.cap_id}: {target.name} needs '{needed}' evidence, got '{evidence.kind}'")
        if not evidence.reference.strip() or not evidence.recorded_on.strip():
            raise ValueError(f"{self.cap_id}: evidence needs a reference and a date")
        if target >= Level.VALIDATED and not (evidence.reviewer or "").strip():
            raise ValueError(f"{self.cap_id}: {target.name} needs a named accountable reviewer")
        if target == Level.ACTIVE and not live_health_ok:
            raise ValueError(f"{self.cap_id}: ACTIVE needs a healthy live input from the host application")
        self.evidence.append(evidence)
        self.level = target

    def demote(self, target: Level) -> None:
        """Drop to a lower state, for example ACTIVE to VALIDATED when health is lost."""
        if target >= self.level:
            raise ValueError(f"{self.cap_id}: demotion must go down")
        self.level = target


def _from_dict(raw: dict) -> Capability:
    return Capability(
        cap_id=raw["id"],
        title=raw["title"],
        level=Level[raw["level"]],
        evidence=[Evidence(**e) for e in raw.get("evidence", [])],
        limits=list(raw.get("limits", [])),
    )


def load_registry(path: str = REGISTRY_PATH) -> list[Capability]:
    with open(path, encoding="utf-8") as handle:
        raw = json.load(handle)
    if raw.get("schema") != "clearguard.capabilities/1":
        raise ValueError("capability registry: unknown schema")
    return [_from_dict(item) for item in raw["capabilities"]]


def registry_problems(caps: list[Capability], package_root: str | None = None) -> list[str]:
    """Each state must be backed by one evidence record per step, and file
    references must exist. A shipped registry may not claim ACTIVE."""
    problems: list[str] = []
    seen: set[str] = set()
    for cap in caps:
        if cap.cap_id in seen:
            problems.append(f"{cap.cap_id}: duplicate id")
        seen.add(cap.cap_id)
        if cap.level == Level.ACTIVE:
            problems.append(f"{cap.cap_id}: ACTIVE is a runtime state and cannot be recorded in a file")
        kinds = [e.kind for e in cap.evidence]
        for step in range(Level.SPECIFIED, cap.level + 1):
            if EVIDENCE_FOR[Level(step)] not in kinds:
                problems.append(f"{cap.cap_id}: {cap.level.name} claimed without '{EVIDENCE_FOR[Level(step)]}' evidence")
        if cap.level >= Level.VALIDATED and not any(e.reviewer for e in cap.evidence if e.kind == "validation"):
            problems.append(f"{cap.cap_id}: VALIDATED without a named reviewer")
        if package_root:
            for ev in cap.evidence:
                target = ev.reference.split("#", 1)[0]
                if target and not os.path.exists(os.path.join(package_root, target)):
                    problems.append(f"{cap.cap_id}: evidence file not found: {target}")
    return problems
