"""State vocabularies and transition tables (SPEC sections 1, 8, 10 and 11).

A transition that is not listed is refused with TransitionError. Tables are
data, so tests can check every allowed and every refused pair.
"""

from __future__ import annotations

from enum import Enum
from typing import Mapping

from .errors import TransitionError


class CapabilityState(str, Enum):
    REQUESTED = "REQUESTED"
    SPECIFIED = "SPECIFIED"
    IMPLEMENTED = "IMPLEMENTED"
    VERIFIED = "VERIFIED"
    VALIDATED = "VALIDATED"
    ACTIVE = "ACTIVE"


CAPABILITY_ORDER = tuple(CapabilityState)


class Lifecycle(str, Enum):
    UNCONFIGURED = "UNCONFIGURED"
    SELF_TEST = "SELF_TEST"
    READY = "READY"
    MONITORING = "MONITORING"
    PAUSED = "PAUSED"
    UNAVAILABLE = "UNAVAILABLE"


class Connectivity(str, Enum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    UNKNOWN = "UNKNOWN"


class Coverage(str, Enum):
    FULL_FOR_CONFIGURED_SCOPE = "FULL_FOR_CONFIGURED_SCOPE"
    PARTIAL = "PARTIAL"
    NONE = "NONE"
    UNKNOWN = "UNKNOWN"


class Routing(str, Enum):
    AVAILABLE = "AVAILABLE"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class Integrity(str, Enum):
    VERIFIED_AS_CONFIGURED = "VERIFIED_AS_CONFIGURED"
    UNVERIFIED = "UNVERIFIED"
    SUSPECTED_FAILURE = "SUSPECTED_FAILURE"


class Priority(str, Enum):
    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    ADVISORY = "ADVISORY"


PRIORITY_RANK = {Priority.ADVISORY: 1, Priority.WARNING: 2, Priority.CRITICAL: 3}


class DeliveryState(str, Enum):
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    ACCEPTED_BY_PLATFORM = "ACCEPTED_BY_PLATFORM"
    PLAYBACK_STARTED = "PLAYBACK_STARTED"
    PLAYBACK_COMPLETED = "PLAYBACK_COMPLETED"
    USER_ACKNOWLEDGED = "USER_ACKNOWLEDGED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class EmergencyState(str, Enum):
    IDLE = "IDLE"
    CHECK_IN = "CHECK_IN"
    COUNTDOWN = "COUNTDOWN"
    ATTEMPTING = "ATTEMPTING"
    CONNECTED = "CONNECTED"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    RESOLVED = "RESOLVED"


class ActionOutcome(str, Enum):
    REQUESTED = "REQUESTED"
    AUTHORIZED = "AUTHORIZED"
    ATTEMPTED = "ATTEMPTED"
    CONNECTED = "CONNECTED"
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


L, D, A = Lifecycle, DeliveryState, ActionOutcome

LIFECYCLE_TRANSITIONS: Mapping[Lifecycle, frozenset] = {
    L.UNCONFIGURED: frozenset({L.SELF_TEST}),
    L.SELF_TEST: frozenset({L.READY, L.UNAVAILABLE, L.UNCONFIGURED}),
    L.READY: frozenset({L.MONITORING, L.SELF_TEST, L.UNCONFIGURED}),
    L.MONITORING: frozenset({L.PAUSED, L.UNAVAILABLE, L.READY}),
    L.PAUSED: frozenset({L.MONITORING, L.READY, L.UNAVAILABLE}),
    L.UNAVAILABLE: frozenset({L.SELF_TEST, L.UNCONFIGURED}),
}

# Terminal states have no exits. Playback completion is not hearing: only a
# received acknowledgement reaches USER_ACKNOWLEDGED.
DELIVERY_TRANSITIONS: Mapping[DeliveryState, frozenset] = {
    D.CREATED: frozenset({D.QUEUED, D.FAILED, D.EXPIRED}),
    D.QUEUED: frozenset({D.ACCEPTED_BY_PLATFORM, D.FAILED, D.EXPIRED}),
    D.ACCEPTED_BY_PLATFORM: frozenset({D.PLAYBACK_STARTED, D.USER_ACKNOWLEDGED, D.FAILED, D.EXPIRED}),
    D.PLAYBACK_STARTED: frozenset({D.PLAYBACK_COMPLETED, D.USER_ACKNOWLEDGED, D.FAILED, D.EXPIRED}),
    D.PLAYBACK_COMPLETED: frozenset({D.USER_ACKNOWLEDGED, D.EXPIRED}),
    D.USER_ACKNOWLEDGED: frozenset(),
    D.FAILED: frozenset(),
    D.EXPIRED: frozenset(),
}

# CANCELLED is reachable only before an attempt: a sent message or a placed
# call cannot be recalled.
ACTION_TRANSITIONS: Mapping[ActionOutcome, frozenset] = {
    A.REQUESTED: frozenset({A.AUTHORIZED, A.FAILED, A.CANCELLED}),
    A.AUTHORIZED: frozenset({A.ATTEMPTED, A.FAILED, A.CANCELLED}),
    A.ATTEMPTED: frozenset({A.CONNECTED, A.SENT, A.FAILED, A.AUTHORIZED}),
    A.CONNECTED: frozenset({A.DELIVERED, A.FAILED}),
    A.SENT: frozenset({A.DELIVERED, A.FAILED}),
    A.DELIVERED: frozenset(),
    A.FAILED: frozenset(),
    A.CANCELLED: frozenset(),
}


def check_transition(table: Mapping, current: Enum, target: Enum) -> None:
    """Raise TransitionError unless ``current -> target`` is in ``table``."""
    if target not in table.get(current, frozenset()):
        raise TransitionError(f"{current.value} -> {target.value} is not an allowed transition")
