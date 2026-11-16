"""Emergency workflow and consent (spec section 11).

External actions come only from the signed action matrix. Each one is keyed by
(action_id, incident_id), so a repeated request never sends twice. States are
reported exactly as the platform confirms them: nothing is described as sent or
delivered without that confirmation, and nothing already sent is described as
recalled. This build has no emergency integration, so every attempt reports
FAILED and points to the phone's native emergency call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

from .config import TrustedConfig

# Workflow states.
IDLE = "IDLE"
CHECK_IN = "CHECK_IN"
COUNTDOWN = "COUNTDOWN"
ATTEMPTING = "ATTEMPTING"
CONNECTED = "CONNECTED"
DELIVERED = "DELIVERED"
FAILED = "FAILED"
CANCELLED = "CANCELLED"
RESOLVED = "RESOLVED"

# Action states.
REQUESTED = "REQUESTED"
AUTHORIZED = "AUTHORIZED"
ATTEMPTED = "ATTEMPTED"
SENT = "SENT"
BLOCKED = "BLOCKED"

PENDING = {REQUESTED, AUTHORIZED}
IN_FLIGHT_OR_DONE = {ATTEMPTED, CONNECTED, SENT, DELIVERED}
TERMINAL = {DELIVERED, FAILED, CANCELLED, BLOCKED}

NATIVE_HINT = "Use your phone's native emergency call if you need help now."


@dataclass
class PlatformResult:
    state: str  # CONNECTED, SENT, DELIVERED or FAILED
    detail: str
    confirmed: bool = False


class EmergencyPlatform(Protocol):
    available: bool

    def execute(self, record: ActionRecord, contact: dict, payload: dict) -> PlatformResult: ...


class UnavailablePlatform:
    available = False

    def execute(self, record: ActionRecord, contact: dict, payload: dict) -> PlatformResult:
        return PlatformResult(FAILED, "no emergency integration in this build (design mode)")


@dataclass
class ActionRecord:
    key: str
    action_id: str
    incident_id: str
    trigger: str
    recipient_id: str
    recipient_label: str
    state: str
    workflow: str
    requested_at: datetime
    expires_at: datetime
    countdown_s: int
    max_attempts: int
    needs_confirmation: bool
    cancellable: bool
    countdown_ends: datetime | None = None
    payload: dict = field(default_factory=dict)
    withheld: list[str] = field(default_factory=list)
    attempts: int = 0
    history: list[tuple[str, str, str]] = field(default_factory=list)

    def log(self, at: datetime, state: str, detail: str) -> None:
        self.state = state
        self.history.append((at.isoformat(), state, detail))

    def describe(self) -> str:
        last = self.history[-1][2] if self.history else ""
        text = {
            REQUESTED: "requested; waiting for your confirmation" if self.needs_confirmation else "requested",
            AUTHORIZED: "authorized; not yet attempted",
            ATTEMPTED: "attempted; no confirmation from the platform yet",
            CONNECTED: "connected, as reported by the platform",
            SENT: "sent; delivery not confirmed",
            DELIVERED: "delivered, as confirmed by the platform",
            FAILED: "failed",
            CANCELLED: "cancelled before anything was sent",
            BLOCKED: "blocked",
        }[self.state]
        return f"{self.action_id} to {self.recipient_label}: {text}" + (f" ({last})" if last else "")


@dataclass
class RequestResult:
    records: list[ActionRecord]
    messages: list[str]


class EmergencyWorkflow:
    def __init__(self, config: TrustedConfig | None, platform: EmergencyPlatform | None = None, *,
                 real_emergency_services_allowed: bool = False):
        self.config = config
        self.platform = platform or UnavailablePlatform()
        # Design and test use never contact real emergency services.
        self.real_emergency_services_allowed = real_emergency_services_allowed
        self.records: dict[str, ActionRecord] = {}

    def request(self, trigger: str, incident_id: str, now: datetime, facts: dict | None = None) -> RequestResult:
        facts = facts or {}
        if self.config is None:
            return RequestResult([], ["No trusted configuration is loaded, so no emergency action is approved.", NATIVE_HINT])
        if not self.config.consent_active(now):
            return RequestResult([], ["Consent is expired or revoked, so no external action was taken.", NATIVE_HINT])
        actions = self.config.actions_for(trigger)
        if not actions:
            return RequestResult([], [f"No approved action for '{trigger}'.", NATIVE_HINT])
        out: list[ActionRecord] = []
        messages: list[str] = []
        for action in actions:
            key = f"{action['action_id']}:{incident_id}"
            if key in self.records:
                out.append(self.records[key])
                messages.append(f"{action['action_id']} was already requested for this incident; not repeated.")
                continue
            contact = self.config.contact(action["recipient"])
            record = ActionRecord(
                key=key, action_id=action["action_id"], incident_id=incident_id, trigger=trigger,
                recipient_id=action["recipient"], recipient_label=contact["label"], state=REQUESTED, workflow=IDLE, requested_at=now,
                expires_at=now + timedelta(seconds=action["expires_after_s"]),
                countdown_s=action["countdown_s"],
                max_attempts=1 + action["max_retries"],
                needs_confirmation=action["requires_confirmation_at_execution"],
                cancellable=action["cancellable"],
            )
            record.payload = {f: facts[f] for f in action["disclose"] if f in facts}
            record.withheld = [f for f in action["disclose"] if f not in facts]
            self.records[key] = record
            out.append(record)
            record.log(now, REQUESTED, "from the approved action matrix")
            if contact["is_emergency_service"] and not self.real_emergency_services_allowed:
                record.log(now, BLOCKED, "design and test use never contact real emergency services")
                record.workflow = FAILED
                messages.append(f"{record.action_id} is blocked: design and test use never contact emergency services. {NATIVE_HINT}")
                continue
            if record.needs_confirmation:
                record.workflow = CHECK_IN
                messages.append(f"Confirm to run {record.action_id} ({contact['label']}).")
            else:
                self._authorize(record, now, "approved in advance by the signed configuration")
            messages += self._advance(record, now)
        return RequestResult(out, messages)

    def confirm(self, incident_id: str, now: datetime) -> RequestResult:
        records, messages = [], []
        for record in self.records.values():
            if record.incident_id == incident_id and record.state == REQUESTED and record.needs_confirmation:
                self._authorize(record, now, "confirmed by the user at execution time")
                records.append(record)
                messages += self._advance(record, now)
        if not records:
            messages.append("Nothing is waiting for confirmation.")
        return RequestResult(records, messages)

    def tick(self, now: datetime) -> list[str]:
        messages: list[str] = []
        for record in self.records.values():
            if record.state in PENDING:
                messages += self._advance(record, now)
        return messages

    @staticmethod
    def _authorize(record: ActionRecord, now: datetime, detail: str) -> None:
        """The cancellation countdown starts when the action is authorized."""
        record.log(now, AUTHORIZED, detail)
        if record.countdown_s:
            record.countdown_ends = now + timedelta(seconds=record.countdown_s)

    def _advance(self, record: ActionRecord, now: datetime) -> list[str]:
        if now >= record.expires_at:
            record.log(now, FAILED, "expired before execution")
            record.workflow = FAILED
            return [f"{record.action_id} expired before it was attempted. {NATIVE_HINT}"]
        if record.state != AUTHORIZED:
            return []
        if record.countdown_ends is not None and now < record.countdown_ends:
            record.workflow = COUNTDOWN
            left = int((record.countdown_ends - now).total_seconds())
            note = " Say 'Guardian, cancel escalation' to stop it." if record.cancellable else ""
            return [f"{record.action_id} starts in {left} s.{note}"]
        contact = self.config.contact(record.recipient_id)
        record.workflow = ATTEMPTING
        result = PlatformResult(FAILED, "not attempted")
        while record.attempts < record.max_attempts:
            record.attempts += 1
            record.log(now, ATTEMPTED, f"attempt {record.attempts} of {record.max_attempts}")
            result = self.platform.execute(record, contact, dict(record.payload))
            if result.state != FAILED or not self.platform.available:
                break
        if result.state == FAILED:
            record.log(now, FAILED, result.detail)
            record.workflow = FAILED
            return [f"Emergency action unavailable: {result.detail}. {NATIVE_HINT}"]
        if result.state == DELIVERED and not result.confirmed:
            record.log(now, SENT, "platform reported delivery without confirmation")
        else:
            record.log(now, result.state, result.detail)
        record.workflow = {CONNECTED: CONNECTED, DELIVERED: DELIVERED}.get(record.state, ATTEMPTING)
        return [record.describe()]

    def cancel(self, now: datetime, incident_id: str | None = None) -> list[str]:
        messages: list[str] = []
        for record in self.records.values():
            if incident_id is not None and record.incident_id != incident_id:
                continue
            if record.state in PENDING:
                if record.cancellable:
                    record.log(now, CANCELLED, "cancelled by the user")
                    record.workflow = CANCELLED
                    messages.append(f"{record.action_id} cancelled before anything was sent.")
                else:
                    messages.append(f"{record.action_id} is not cancellable under the approved policy.")
            elif record.state in IN_FLIGHT_OR_DONE:
                messages.append(f"{record.action_id} was already attempted; it cannot be recalled.")
        return messages or ["No escalation is in progress."]

    def resolve(self, incident_id: str, now: datetime) -> None:
        for record in self.records.values():
            if record.incident_id == incident_id:
                record.workflow = RESOLVED
                record.history.append((now.isoformat(), record.state, "incident resolved"))

    def active(self) -> list[ActionRecord]:
        return [r for r in self.records.values() if r.state not in TERMINAL]
