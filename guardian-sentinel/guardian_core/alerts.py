"""Alert controller (SPEC sections 9 and 10).

Urgent alerts use preapproved templates only, so language generation can
never delay or rewrite them. Every template is linted: 3 to 10 words for
CRITICAL and WARNING, no claim of safety, no speculation about intent.

Delivery goes only to channels whose test has passed (``verified is True``).
Each alert records its delivery states separately; playback completion is
not treated as hearing, and a missing acknowledgement is not interpreted.
Duplicates are suppressed only inside an explicit window, and a higher
priority always gets through. Expired alerts are never replayed as current.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .errors import HazardError
from .hazards import HazardEvent, HazardKind
from .states import DELIVERY_TRANSITIONS, PRIORITY_RANK, DeliveryState, Priority, check_transition

D = DeliveryState


@dataclass(frozen=True)
class Template:
    priority: Priority
    text: str
    hazard: HazardKind


TEMPLATES: dict[str, Template] = {
    "obstacle_ahead": Template(Priority.CRITICAL, "Obstacle ahead. Check your path.", HazardKind.OBSTACLE),
    "possible_fall": Template(Priority.WARNING, "Possible fall detected. Do you need help?", HazardKind.FALL),
    "check_in_due": Template(Priority.WARNING, "Check-in due. Please respond now.", HazardKind.MISSED_CHECK_IN),
    "official_warning": Template(Priority.WARNING, "Official emergency warning issued. Check your phone.",
                                 HazardKind.OFFICIAL_WARNING),
    "help_request_received": Template(Priority.CRITICAL, "Help request received. Checking emergency options.",
                                      HazardKind.HELP_REQUEST),
    "camera_blocked": Template(Priority.ADVISORY, "Visual detection unavailable. Camera blocked.",
                               HazardKind.CAPABILITY_LOSS),
    "headphones_disconnected_watch_verified": Template(
        Priority.ADVISORY, "Headphones disconnected. Watch alerts remain available.", HazardKind.CAPABILITY_LOSS),
    "headphones_disconnected_no_fallback": Template(
        Priority.ADVISORY, "Headphones disconnected. No verified backup alert channel.", HazardKind.CAPABILITY_LOSS),
    "monitoring_unavailable": Template(
        Priority.ADVISORY, "Monitoring unavailable. Supported hazards are not being checked.",
        HazardKind.CAPABILITY_LOSS),
}

FORBIDDEN_PHRASES = (
    "you are safe", "you're safe", "safe to cross", "all clear", "no danger", "danger is gone",
    "attacker", "threat", "someone is following", "being followed", "run!", "guaranteed",
    "certified", "nsa-grade", "darpa-grade", "nsc-grade",
)


def lint_message(text: str, priority: Priority) -> list[str]:
    problems = []
    words = len(text.split())
    if priority in (Priority.CRITICAL, Priority.WARNING) and not 3 <= words <= 10:
        problems.append(f"{priority.value} message has {words} words; use 3 to 10")
    if priority is Priority.ADVISORY and words > 12:
        problems.append(f"advisory has {words} words; keep it brief")
    lowered = text.lower()
    problems += [f"forbidden phrase: {p!r}" for p in FORBIDDEN_PHRASES if p in lowered]
    return problems


def headphone_loss_template(watch_fallback_verified: bool) -> str:
    """Never claim a fallback that has not passed its test."""
    return ("headphones_disconnected_watch_verified" if watch_fallback_verified
            else "headphones_disconnected_no_fallback")


class Channel:
    """An output path offered by the host platform.

    ``verified`` is None until tested, then True or False. Only a channel
    with ``verified is True`` receives alerts. ``submit`` returns True when
    the platform accepted the alert; acceptance is not playback.
    """

    def __init__(self, name: str, kind: str, verified: bool | None = None) -> None:
        self.name, self.kind, self.verified = name, kind, verified

    def submit(self, alert: "Alert") -> bool:  # pragma: no cover - overridden by integrations
        raise NotImplementedError


@dataclass
class Alert:
    alert_id: str
    event: HazardEvent
    template_id: str
    priority: Priority
    text: str
    created_at: float
    state: DeliveryState = D.CREATED
    channel: str | None = None
    history: list = field(default_factory=list)

    @property
    def expires_at(self) -> float:
        return self.event.expires_at

    def move(self, target: DeliveryState, now: float, detail: str = "") -> None:
        check_transition(DELIVERY_TRANSITIONS, self.state, target)
        self.state = target
        self.history.append((target.value, now, detail))


TERMINAL = {D.USER_ACKNOWLEDGED, D.FAILED, D.EXPIRED}


class AlertController:
    def __init__(self, channels=(), dedupe_window_s: float | None = None) -> None:
        self.channels = list(channels)
        self.dedupe_window_s = dedupe_window_s  # None: never suppress
        self.alerts: list[Alert] = []
        self.suppressed: dict[tuple[str, str], int] = {}
        self._n = 0

    def raise_alert(self, event: HazardEvent, template_id: str, now: float) -> Alert | None:
        template = TEMPLATES.get(template_id)
        if template is None:
            raise HazardError(f"no approved template {template_id!r}")
        if template.hazard is not event.hazard:
            raise HazardError(f"template {template_id!r} does not describe a {event.hazard.value} event")

        if self.dedupe_window_s is not None:
            for prior in reversed(self.alerts):
                if now - prior.created_at > self.dedupe_window_s:
                    break
                same = prior.event.hazard is event.hazard and prior.template_id == template_id
                if (same and prior.state not in (D.FAILED, D.EXPIRED)
                        and PRIORITY_RANK[event.priority] <= PRIORITY_RANK[prior.priority]):
                    key = (event.hazard.value, template_id)
                    self.suppressed[key] = self.suppressed.get(key, 0) + 1
                    return None

        self._n += 1
        alert = Alert(f"alert-{self._n}", event, template_id, max(
            template.priority, event.priority, key=PRIORITY_RANK.__getitem__), template.text, now)
        alert.history.append((D.CREATED.value, now, ""))
        self.alerts.append(alert)
        if event.expired(now):
            alert.move(D.EXPIRED, now, "event expired before delivery")
            return alert

        ready = [c for c in self.channels if c.verified is True]
        if not ready:
            alert.move(D.FAILED, now, "no verified alert channel")
            return alert
        alert.move(D.QUEUED, now)
        for channel in ready:
            try:
                accepted = channel.submit(alert)
            except Exception as exc:  # a broken channel must not stop the next one
                alert.history.append(("CHANNEL_ERROR", now, f"{channel.name}: {exc.__class__.__name__}"))
                continue
            if accepted:
                alert.channel = channel.name
                alert.move(D.ACCEPTED_BY_PLATFORM, now, channel.name)
                return alert
            alert.history.append(("CHANNEL_REFUSED", now, channel.name))
        alert.move(D.FAILED, now, "every verified channel refused the alert")
        return alert

    def on_platform_event(self, alert_id: str, state: DeliveryState, now: float, detail: str = "") -> Alert:
        alert = next((a for a in self.alerts if a.alert_id == alert_id), None)
        if alert is None:
            raise HazardError(f"unknown alert {alert_id!r}")
        alert.move(state, now, detail)
        return alert

    def expire(self, now: float) -> list[Alert]:
        expired = []
        for alert in self.alerts:
            if alert.state not in TERMINAL and alert.event.expired(now):
                alert.move(D.EXPIRED, now, "event aged out")
                expired.append(alert)
        return expired

    def last(self) -> Alert | None:
        return self.alerts[-1] if self.alerts else None

    def active(self, now: float) -> list[Alert]:
        return [a for a in self.alerts if a.state not in (D.FAILED, D.EXPIRED) and not a.event.expired(now)]

    def repeat_last(self, now: float) -> str | None:
        alert = self.last()
        if alert is None:
            return None
        if alert.event.expired(now) or alert.state is D.EXPIRED:
            return f"Earlier alert, now expired: {alert.text}"
        return alert.text
