"""Pre-approved alert templates, the alert controller, and delivery tracking
(spec sections 9 and 10).

Urgent alerts use fixed templates, never generated language, so a model can
neither delay nor reword them. Delivery is tracked state by state; playback is
not hearing, and a missing acknowledgement is not unconsciousness.
"""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from .events import Priority
from .timeutil import clock

TEMPLATES: dict[str, tuple[Priority, str]] = {
    "obstacle_ahead": (Priority.CRITICAL, "Obstacle ahead. Check your path."),
    "possible_fall": (Priority.WARNING, "Possible fall detected. Do you need help?"),
    "official_warning": (Priority.WARNING, "Official emergency warning received. Check your phone."),
    "missed_check_in": (Priority.WARNING, "Check-in missed. Do you need help?"),
    "help_request_received": (Priority.CRITICAL, "Help request received. Confirm to notify your contact."),
    "camera_blocked": (Priority.ADVISORY, "Visual detection unavailable. Camera blocked."),
    "monitoring_lost": (Priority.ADVISORY, "Monitoring unavailable. Alerts may not reach you."),
    "headphones_lost_watch": (Priority.ADVISORY, "Headphones disconnected. Watch alerts remain available."),
    "headphones_lost_phone": (Priority.ADVISORY, "Headphones disconnected. Phone alerts remain available."),
    "headphones_lost_none": (Priority.ADVISORY, "Headphones disconnected. No verified backup alert channel."),
}

# Phrases the spec rules out: false reassurance, unobserved escape routes,
# crossing judgments, abrupt movement commands, and speculative intent.
BANNED = re.compile(
    r"\b(you are safe|you're safe|all clear|safe to cross|crossing is (?:safe|clear)|escape|run\b|"
    r"stop now|freeze|attacker|threat|danger is over|someone is)",
    re.IGNORECASE,
)


def template_problems(template_id: str, text: str) -> list[str]:
    problems = []
    words = len(text.split())
    if not 3 <= words <= 10:
        problems.append(f"{template_id}: {words} words; urgent alerts use 3 to 10")
    match = BANNED.search(text)
    if match:
        problems.append(f"{template_id}: banned phrase '{match.group(0)}'")
    return problems


def lint_templates() -> list[str]:
    return [p for tid, (_, text) in TEMPLATES.items() for p in template_problems(tid, text)]


# Delivery states, in the order the spec lists them.
CREATED = "CREATED"
QUEUED = "QUEUED"
ACCEPTED_BY_PLATFORM = "ACCEPTED_BY_PLATFORM"
PLAYBACK_STARTED = "PLAYBACK_STARTED"
PLAYBACK_COMPLETED = "PLAYBACK_COMPLETED"
USER_ACKNOWLEDGED = "USER_ACKNOWLEDGED"
FAILED = "FAILED"
EXPIRED = "EXPIRED"

TRANSITIONS = {
    CREATED: {QUEUED, FAILED, EXPIRED},
    QUEUED: {ACCEPTED_BY_PLATFORM, FAILED, EXPIRED},
    ACCEPTED_BY_PLATFORM: {PLAYBACK_STARTED, USER_ACKNOWLEDGED, FAILED, EXPIRED},
    PLAYBACK_STARTED: {PLAYBACK_COMPLETED, USER_ACKNOWLEDGED, FAILED},
    PLAYBACK_COMPLETED: {USER_ACKNOWLEDGED, EXPIRED},
    USER_ACKNOWLEDGED: set(),
    FAILED: set(),
    EXPIRED: set(),
}

_ids = itertools.count(1)


@dataclass
class Alert:
    alert_id: str
    event_id: str
    detector_id: str
    template_id: str
    priority: Priority
    text: str
    created_at: datetime
    expires_at: datetime
    simulated: bool = False

    def spoken(self) -> str:
        return f"[SIMULATED] {self.text}" if self.simulated else self.text

    def is_current(self, now: datetime) -> bool:
        return now < self.expires_at

    def replay_text(self, now: datetime) -> str:
        if self.is_current(now):
            return self.spoken()
        return f"Historical alert from {clock(self.created_at)}, no longer current: {self.spoken()}"


def build_alert(template_id: str, event_id: str, detector_id: str, created_at: datetime,
                expires_at: datetime, *, simulated: bool) -> Alert:
    priority, text = TEMPLATES[template_id]
    return Alert(
        alert_id=f"A{next(_ids):06d}", event_id=event_id, detector_id=detector_id, template_id=template_id,
        priority=priority, text=text, created_at=created_at, expires_at=expires_at, simulated=simulated,
    )


@dataclass
class Delivery:
    alert_id: str
    channel: str
    state: str = CREATED
    history: list[tuple[str, str, str]] = field(default_factory=list)  # (time, state, detail)

    def advance(self, state: str, at: datetime, detail: str = "") -> None:
        if state not in TRANSITIONS[self.state]:
            raise ValueError(f"delivery {self.alert_id}/{self.channel}: {self.state} -> {state} is not allowed")
        self.state = state
        self.history.append((at.isoformat(), state, detail))

    def describe(self) -> str:
        meaning = {
            CREATED: "created, not yet sent",
            QUEUED: "queued on this device",
            ACCEPTED_BY_PLATFORM: "accepted by the platform; playback not confirmed",
            PLAYBACK_STARTED: "playback started",
            PLAYBACK_COMPLETED: "playback completed; this does not confirm it was heard",
            USER_ACKNOWLEDGED: "acknowledged by the user",
            FAILED: "failed",
            EXPIRED: "expired before delivery",
        }[self.state]
        last = self.history[-1][2] if self.history and self.history[-1][2] else ""
        return f"{self.channel}: {meaning}" + (f" ({last})" if last else "")


class OutputChannel(Protocol):
    name: str
    verified: bool

    def submit(self, alert: Alert, delivery: Delivery, now: datetime) -> None:
        """Advance ``delivery`` with whatever the host platform actually reports."""


class UnavailableChannel:
    """Stands in for an output this build has no host integration for."""

    def __init__(self, name: str):
        self.name = name
        self.verified = False

    def submit(self, alert: Alert, delivery: Delivery, now: datetime) -> None:
        delivery.advance(FAILED, now, f"no host integration for {self.name} (design mode)")


class AlertController:
    """Delivers through the first verified channel in the configured order,
    falling back to the next verified one when delivery fails."""

    def __init__(self, channels: list[OutputChannel], max_volume_pct: int = 50):
        self.channels = channels
        self.max_volume_pct = max_volume_pct

    def verified_channels(self) -> list[str]:
        return [c.name for c in self.channels if c.verified]

    def headphone_loss_template(self) -> str:
        verified = set(self.verified_channels())
        if "watch_haptic" in verified:
            return "headphones_lost_watch"
        if "phone_notification" in verified:
            return "headphones_lost_phone"
        return "headphones_lost_none"

    def dispatch(self, alert: Alert, now: datetime) -> list[Delivery]:
        if not alert.is_current(now):
            stale = Delivery(alert.alert_id, "none")
            stale.advance(EXPIRED, now, "alert expired before dispatch; obsolete instructions are not replayed")
            return [stale]
        deliveries: list[Delivery] = []
        for channel in self.channels:
            if not channel.verified:
                continue
            delivery = Delivery(alert.alert_id, channel.name)
            channel.submit(alert, delivery, now)
            deliveries.append(delivery)
            if delivery.state != FAILED:
                return deliveries
        if not deliveries:
            none = Delivery(alert.alert_id, "none")
            none.advance(FAILED, now, "no verified alert channel")
            deliveries.append(none)
        return deliveries
