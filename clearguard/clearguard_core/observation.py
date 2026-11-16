"""Observation integrity (spec section 5).

Every observation must carry provenance and quality fields. The gate rejects or
quarantines malformed, stale, replayed, duplicated, out-of-order, clock-
inconsistent and implausible inputs. Independence is judged from lineage: two
services fed by the same sensor are one piece of evidence, not two.
"""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime

from .timeutil import parse_time

ACCEPTED = "ACCEPTED"
ACCEPTED_DEGRADED = "ACCEPTED_DEGRADED"
QUARANTINED = "QUARANTINED"
REJECTED = "REJECTED"

FIELDS = (
    "source_id", "observation_id", "event_time", "receipt_time", "clock_uncertainty_s",
    "measurement", "units", "measurement_uncertainty", "sensor_health", "permission_state",
    "freshness_limit_s", "integrity_status", "lineage",
)
SENSOR_HEALTH = {"ok", "degraded", "failed"}
PERMISSION_STATES = {"granted", "denied", "revoked", "unknown"}
INTEGRITY_STATES = {"verified", "unverified", "failed"}


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


@dataclass(frozen=True)
class Observation:
    source_id: str
    observation_id: str
    event_time: datetime
    receipt_time: datetime
    clock_uncertainty_s: float
    measurement: float | bool
    units: str
    measurement_uncertainty: float
    sensor_health: str
    permission_state: str
    freshness_limit_s: float
    integrity_status: str
    lineage: tuple[str, ...]
    digest: str

    def roots(self) -> set[str]:
        return set(self.lineage) | {self.source_id}


@dataclass
class Admission:
    status: str
    reasons: list[str] = field(default_factory=list)
    observation: Observation | None = None
    observation_id: str | None = None

    @property
    def usable(self) -> bool:
        return self.status in (ACCEPTED, ACCEPTED_DEGRADED)


def parse(raw: object) -> tuple[Observation | None, list[str]]:
    if not isinstance(raw, dict):
        return None, ["malformed: observation must be an object"]
    problems = [f"malformed: missing {name}" for name in FIELDS if name not in raw]
    unknown = sorted(set(raw) - set(FIELDS))
    problems += [f"malformed: unknown field {name}" for name in unknown]
    if problems:
        return None, problems
    for name in ("source_id", "observation_id", "units"):
        if not isinstance(raw[name], str) or not raw[name].strip():
            problems.append(f"malformed: {name} must be a non-empty string")
    for name in ("clock_uncertainty_s", "measurement_uncertainty", "freshness_limit_s"):
        if not _number(raw[name]) or raw[name] < 0:
            problems.append(f"malformed: {name} must be a number of 0 or more")
    if _number(raw["freshness_limit_s"]) and raw["freshness_limit_s"] == 0:
        problems.append("malformed: freshness_limit_s must be greater than 0")
    if not (_number(raw["measurement"]) or isinstance(raw["measurement"], bool)):
        problems.append("malformed: measurement must be a number or true/false")
    if raw["sensor_health"] not in SENSOR_HEALTH:
        problems.append(f"malformed: sensor_health must be one of {sorted(SENSOR_HEALTH)}")
    if raw["permission_state"] not in PERMISSION_STATES:
        problems.append(f"malformed: permission_state must be one of {sorted(PERMISSION_STATES)}")
    if raw["integrity_status"] not in INTEGRITY_STATES:
        problems.append(f"malformed: integrity_status must be one of {sorted(INTEGRITY_STATES)}")
    if not isinstance(raw["lineage"], list) or not all(isinstance(x, str) and x for x in raw["lineage"]):
        problems.append("malformed: lineage must be a list of upstream source ids")
    times = {}
    for name in ("event_time", "receipt_time"):
        try:
            times[name] = parse_time(raw[name])
        except ValueError as exc:
            problems.append(f"malformed: {name}: {exc}")
    if problems:
        return None, problems
    digest = hashlib.sha256(json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return Observation(
        source_id=raw["source_id"], observation_id=raw["observation_id"],
        event_time=times["event_time"], receipt_time=times["receipt_time"],
        clock_uncertainty_s=float(raw["clock_uncertainty_s"]), measurement=raw["measurement"],
        units=raw["units"], measurement_uncertainty=float(raw["measurement_uncertainty"]),
        sensor_health=raw["sensor_health"], permission_state=raw["permission_state"],
        freshness_limit_s=float(raw["freshness_limit_s"]), integrity_status=raw["integrity_status"],
        lineage=tuple(raw["lineage"]), digest=digest,
    ), []


class ObservationGate:
    """Admits observations one at a time. ``max_rates`` maps (source_id, units)
    to the largest physically plausible change per second, taken from a reviewed
    detector contract. Without an entry, no jump check is made for that input."""

    def __init__(self, max_rates: dict[tuple[str, str], float] | None = None, history: int = 4096):
        self.max_rates = dict(max_rates or {})
        self._history = history
        self._seen: OrderedDict[str, str] = OrderedDict()
        self._last: dict[str, Observation] = {}
        self.admitted: dict[str, Observation] = {}

    def _remember(self, obs: Observation) -> None:
        self._seen[obs.observation_id] = obs.digest
        while len(self._seen) > self._history:
            self._seen.popitem(last=False)

    def admit(self, raw: object, now: datetime) -> Admission:
        obs, problems = parse(raw)
        oid = raw.get("observation_id") if isinstance(raw, dict) else None
        if obs is None:
            return Admission(REJECTED, problems, None, oid if isinstance(oid, str) else None)

        prior = self._seen.get(obs.observation_id)
        if prior is not None:
            if prior == obs.digest:
                return Admission(REJECTED, ["duplicate: observation already received"], obs, obs.observation_id)
            return Admission(
                QUARANTINED, ["replay conflict: same observation_id with different content"], obs, obs.observation_id
            )
        self._remember(obs)

        def out(status: str, reasons: list[str]) -> Admission:
            return Admission(status, reasons, obs, obs.observation_id)

        if obs.permission_state != "granted":
            return out(REJECTED, [f"permission {obs.permission_state}: input not authorized"])
        if obs.sensor_health == "failed":
            return out(REJECTED, ["sensor reports failed health"])
        if obs.integrity_status == "failed":
            return out(QUARANTINED, ["integrity check failed upstream"])

        slack = obs.clock_uncertainty_s
        if (obs.event_time - obs.receipt_time).total_seconds() > slack:
            return out(QUARANTINED, ["clock discontinuity: event time is after receipt time"])
        if (obs.receipt_time - now).total_seconds() > slack:
            return out(QUARANTINED, ["clock discontinuity: receipt time is in the future"])
        age = (now - obs.event_time).total_seconds()
        if age > obs.freshness_limit_s + slack:
            return out(REJECTED, [f"stale: {age:.1f} s old, limit {obs.freshness_limit_s:g} s"])

        last = self._last.get(obs.source_id)
        if last is not None:
            gap = (obs.event_time - last.event_time).total_seconds()
            if gap < -slack:
                return out(QUARANTINED, ["out of order: older than the last sample from this source"])
            rate_limit = self.max_rates.get((obs.source_id, obs.units))
            if (
                rate_limit is not None and gap > 0 and last.units == obs.units
                and _number(obs.measurement) and _number(last.measurement)
            ):
                rate = abs(float(obs.measurement) - float(last.measurement)) / gap
                if rate > rate_limit:
                    return out(QUARANTINED, [f"implausible jump: {rate:g} {obs.units}/s exceeds {rate_limit:g}"])

        self._last[obs.source_id] = obs
        self.admitted[obs.observation_id] = obs
        reasons: list[str] = []
        if obs.sensor_health == "degraded":
            reasons.append("sensor reports degraded health")
        if obs.integrity_status == "unverified":
            reasons.append("integrity not verified upstream")
        return out(ACCEPTED_DEGRADED if reasons else ACCEPTED, reasons)


def independent(a: Observation, b: Observation) -> bool:
    """False when the two share any upstream source, including the sensor itself."""
    return not (a.roots() & b.roots())


def independent_count(observations: list[Observation]) -> int:
    """Number of groups of observations with no shared upstream source."""
    parent = list(range(len(observations)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(observations)):
        for j in range(i + 1, len(observations)):
            if not independent(observations[i], observations[j]):
                parent[find(i)] = find(j)
    return len({find(i) for i in range(len(observations))})


@dataclass
class Comparison:
    agree: bool
    values: list[tuple[str, float]]
    note: str


def compare(observations: list[Observation]) -> Comparison:
    """Report whether numeric measurements agree within their stated uncertainty.
    Disagreement is preserved and reported; no averaged value is produced."""
    numeric = [o for o in observations if _number(o.measurement)]
    units = {o.units for o in numeric}
    values = [(o.observation_id, float(o.measurement)) for o in numeric]
    if len(units) > 1:
        return Comparison(False, values, "units differ; values are not comparable")
    for i, a in enumerate(numeric):
        for b in numeric[i + 1:]:
            gap = abs(float(a.measurement) - float(b.measurement))
            if gap > a.measurement_uncertainty + b.measurement_uncertainty:
                return Comparison(False, values, f"{a.observation_id} and {b.observation_id} disagree beyond stated uncertainty")
    return Comparison(True, values, "agree within stated uncertainty")
