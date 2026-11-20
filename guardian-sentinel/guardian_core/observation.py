"""Observation integrity (SPEC section 5).

Every observation carries provenance and quality fields. The gate rejects
malformed, unauthorized, failed, duplicate or stale input, and quarantines
input that is out of order, inconsistent with the clock, or physically
implausible. Quarantined input is kept for review but never drives an alert.

Two observations are independent evidence only if they come from different
sources and share no upstream root in their lineage. Disagreement between
sources is reported as disagreement, never averaged away.
"""

from __future__ import annotations

import math
from collections import OrderedDict
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .errors import ObservationError

SENSOR_HEALTH = {"ok", "degraded", "failed"}
PERMISSION = {"granted", "revoked", "unknown"}
INTEGRITY = {"verified", "unverified", "failed"}
FIELDS = {
    "source_id", "observation_id", "kind", "value", "unit", "uncertainty", "event_ts",
    "receipt_ts", "clock_uncertainty_s", "sensor_health", "permission", "freshness_s",
    "integrity", "lineage",
}


@dataclass(frozen=True)
class Observation:
    source_id: str
    observation_id: str
    kind: str
    value: float
    unit: str
    uncertainty: float
    event_ts: float
    receipt_ts: float
    clock_uncertainty_s: float
    sensor_health: str
    permission: str
    freshness_s: float
    integrity: str
    lineage: tuple[str, ...]


def _num(raw: dict, name: str, *, minimum: float | None = None) -> float:
    value = raw[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ObservationError(f"{name} must be a finite number")
    if minimum is not None and value < minimum:
        raise ObservationError(f"{name} must be at least {minimum}")
    return float(value)


def _str(raw: dict, name: str, allowed: set[str] | None = None) -> str:
    value = raw[name]
    if not isinstance(value, str) or not value.strip() or len(value) > 128:
        raise ObservationError(f"{name} must be a non-empty string of at most 128 characters")
    if allowed is not None and value not in allowed:
        raise ObservationError(f"{name} must be one of {sorted(allowed)}")
    return value


def parse_observation(raw: Any) -> Observation:
    if not isinstance(raw, dict):
        raise ObservationError("observation must be an object")
    unknown, absent = set(raw) - FIELDS, FIELDS - set(raw)
    if unknown or absent:
        raise ObservationError(f"unknown {sorted(unknown)} / missing {sorted(absent)} fields")
    lineage = raw["lineage"]
    if (not isinstance(lineage, list) or not lineage
            or not all(isinstance(x, str) and x.strip() for x in lineage)):
        raise ObservationError("lineage must be a non-empty list of upstream source ids")
    return Observation(
        source_id=_str(raw, "source_id"),
        observation_id=_str(raw, "observation_id"),
        kind=_str(raw, "kind"),
        value=_num(raw, "value"),
        unit=_str(raw, "unit"),
        uncertainty=_num(raw, "uncertainty", minimum=0.0),
        event_ts=_num(raw, "event_ts"),
        receipt_ts=_num(raw, "receipt_ts"),
        clock_uncertainty_s=_num(raw, "clock_uncertainty_s", minimum=0.0),
        sensor_health=_str(raw, "sensor_health", SENSOR_HEALTH),
        permission=_str(raw, "permission", PERMISSION),
        freshness_s=_num(raw, "freshness_s", minimum=0.0),
        integrity=_str(raw, "integrity", INTEGRITY),
        lineage=tuple(lineage),
    )


class Verdict(str, Enum):
    ACCEPT = "ACCEPT"
    QUARANTINE = "QUARANTINE"
    REJECT = "REJECT"


@dataclass(frozen=True)
class Admission:
    verdict: Verdict
    reasons: tuple[str, ...]
    observation: Observation | None
    flags: tuple[str, ...] = ()


class ObservationGate:
    """Stateful admission checks for a stream of observations.

    ``max_rate`` maps ``(kind, unit)`` to the largest physically plausible
    change per second, taken from the detector contract. Kinds without a
    limit get no jump check: the gate does not invent one.
    """

    def __init__(self, max_rate: dict[tuple[str, str], float] | None = None,
                 seen_capacity: int = 4096) -> None:
        self.max_rate = dict(max_rate or {})
        self._seen: OrderedDict[tuple[str, str], None] = OrderedDict()
        self._capacity = seen_capacity
        self._last: dict[str, Observation] = {}
        self.quarantine: list[Admission] = []

    def admit(self, raw: Any, now: float) -> Admission:
        try:
            obs = parse_observation(raw)
        except ObservationError as exc:
            return Admission(Verdict.REJECT, (f"malformed: {exc}",), None)

        if obs.permission != "granted":
            return Admission(Verdict.REJECT, (f"permission_{obs.permission}",), obs)
        if obs.integrity == "failed":
            return Admission(Verdict.REJECT, ("integrity_failed",), obs)
        if obs.sensor_health == "failed":
            return Admission(Verdict.REJECT, ("sensor_failed",), obs)
        key = (obs.source_id, obs.observation_id)
        if key in self._seen:
            return Admission(Verdict.REJECT, ("duplicate_or_replay",), obs)
        self._remember(key)

        slack = obs.clock_uncertainty_s
        if now - obs.event_ts > obs.freshness_s + slack:
            return Admission(Verdict.REJECT, ("stale",), obs)

        reasons = []
        if obs.event_ts > obs.receipt_ts + slack or obs.receipt_ts > now + slack:
            reasons.append("clock_discontinuity")
        last = self._last.get(obs.source_id)
        if last is not None:
            dt = obs.event_ts - last.event_ts
            if dt < 0:
                reasons.append("out_of_order")
            elif obs.kind == last.kind and obs.unit == last.unit:
                limit = self.max_rate.get((obs.kind, obs.unit))
                if limit is not None:
                    change = abs(obs.value - last.value)
                    if (dt == 0 and change > 0) or (dt > 0 and change / dt > limit):
                        reasons.append("implausible_jump")
        if reasons:
            admission = Admission(Verdict.QUARANTINE, tuple(reasons), obs)
            self.quarantine.append(admission)
            return admission

        flags = []
        if obs.integrity == "unverified":
            flags.append("integrity_unverified")
        if obs.sensor_health == "degraded":
            flags.append("sensor_degraded")
        self._last[obs.source_id] = obs
        return Admission(Verdict.ACCEPT, (), obs, tuple(flags))

    def _remember(self, key: tuple[str, str]) -> None:
        self._seen[key] = None
        while len(self._seen) > self._capacity:
            self._seen.popitem(last=False)


def independent(a: Observation, b: Observation) -> bool:
    return a.source_id != b.source_id and not (set(a.lineage) & set(b.lineage))


def independent_groups(observations: list[Observation]) -> int:
    """Number of mutually independent evidence groups (shared lineage merges)."""
    groups: list[set[str]] = []
    for obs in observations:
        roots = set(obs.lineage) | {"source:" + obs.source_id}
        merged = [g for g in groups if g & roots]
        for g in merged:
            groups.remove(g)
            roots |= g
        groups.append(roots)
    return len(groups)


def compare(observations: list[Observation]) -> dict:
    """Report agreement only when every pair of uncertainty intervals overlaps."""
    values = [(o.source_id, o.value, o.uncertainty) for o in observations]
    units = {(o.kind, o.unit) for o in observations}
    if len(units) > 1:
        return {"agreement": False, "reason": "different kinds or units", "values": values}
    agree = all(
        abs(a.value - b.value) <= a.uncertainty + b.uncertainty
        for i, a in enumerate(observations) for b in observations[i + 1:]
    )
    return {"agreement": agree, "reason": "intervals overlap" if agree else "material disagreement",
            "values": values}
