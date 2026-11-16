"""Hazard events (SPEC sections 6 and 7).

Only the supported categories exist. There is no category for another
person's intent, appearance or presence, and none for weapons, substances,
radiation, explosives or medical diagnosis: those need validated
instrumentation this design does not have.

Every event separates observed facts, inferences, unknowns, alternative
explanations and limitations. A numeric confidence is accepted only from a
detector whose contract declares it calibrated.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from .errors import HazardError
from .states import Priority


class HazardKind(str, Enum):
    OBSTACLE = "obstacle"
    FALL = "fall"
    OFFICIAL_WARNING = "official_warning"
    MISSED_CHECK_IN = "missed_check_in"
    HELP_REQUEST = "help_request"
    CAPABILITY_LOSS = "capability_loss"


USER_ORIGINATED = {HazardKind.MISSED_CHECK_IN, HazardKind.HELP_REQUEST}

UNSUPPORTED_HAZARDS = (
    "intent or hostility of other people",
    "following or surveillance by other people",
    "concealed weapons",
    "toxic substances",
    "radiation",
    "explosives",
    "medical emergencies or diagnosis",
    "lane-level crossing safety",
)


@dataclass(frozen=True)
class HazardEvent:
    event_id: str
    hazard: HazardKind
    priority: Priority
    detector_id: str
    created_at: float
    expires_at: float
    observation_ids: tuple[str, ...]
    observed_facts: tuple[str, ...]
    inferences: tuple[str, ...] = ()
    unknowns: tuple[str, ...] = ()
    alternative_explanations: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    confidence: float | None = None

    def expired(self, now: float) -> bool:
        return now >= self.expires_at


def make_event(*, event_id: str, hazard: str | HazardKind, priority: Priority, detector_id: str,
               created_at: float, max_age_s: float, observation_ids: tuple[str, ...],
               observed_facts: tuple[str, ...], contract=None, confidence: float | None = None,
               inferences: tuple[str, ...] = (), unknowns: tuple[str, ...] = (),
               alternative_explanations: tuple[str, ...] = (),
               limitations: tuple[str, ...] = ()) -> HazardEvent:
    try:
        kind = HazardKind(hazard)
    except ValueError:
        raise HazardError(f"unsupported hazard category: {hazard!r}") from None
    if not event_id or not detector_id:
        raise HazardError("event_id and detector_id are required")
    if not observed_facts:
        raise HazardError("an event needs at least one observed fact")
    if not (isinstance(max_age_s, (int, float)) and math.isfinite(max_age_s) and max_age_s > 0):
        raise HazardError("max_age_s must be a positive number from the detector contract")
    if kind not in USER_ORIGINATED:
        if contract is None:
            raise HazardError(f"{kind.value} events need the detector's safety contract")
        if contract.hazard is not kind:
            raise HazardError("the detector contract covers a different hazard")
        if not observation_ids:
            raise HazardError("a detector event must cite its observation ids")
    if confidence is not None:
        calibrated = contract is not None and contract.confidence_calibrated is True
        if not calibrated:
            raise HazardError("numeric confidence needs a detector declared calibrated in its contract")
        if not (isinstance(confidence, float) and 0.0 <= confidence <= 1.0):
            raise HazardError("confidence must be a float from 0 to 1")
    return HazardEvent(event_id, kind, Priority(priority), detector_id, created_at,
                       created_at + max_age_s, tuple(observation_ids), tuple(observed_facts),
                       tuple(inferences), tuple(unknowns), tuple(alternative_explanations),
                       tuple(limitations), confidence)
