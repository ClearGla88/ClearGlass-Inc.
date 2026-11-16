"""Emergency workflow and consent (SPEC section 11).

Only actions listed in the authenticated configuration can run, only for the
exact trigger listed, only while consent is valid, and only through a
dispatcher the host platform provides. This package ships no dispatcher, so
in design mode every request is refused at once and the refusal says so.

Each request gets an application-level instance id derived from the action
and the triggering event, so a repeated request cannot place a second call
or send a second message. Cancellation works only before an attempt: a sent
message or a placed call is never described as recalled. Dispatch and
delivery are recorded only when the dispatcher or the platform reports them.
No code path calls a real emergency service.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from .config import Action, TrustedConfig
from .errors import GuardianError
from .hazards import HazardEvent
from .states import ACTION_TRANSITIONS, PRIORITY_RANK, ActionOutcome, EmergencyState, check_transition

A, E = ActionOutcome, EmergencyState
NOT_ATTEMPTED = {A.REQUESTED, A.AUTHORIZED}


class EmergencyUnavailable(GuardianError):
    """No approved action can run: say so immediately, never imply otherwise."""


class Dispatcher:
    """Host-platform interface. ``dispatch`` returns 'connected', 'sent' or 'failed'."""

    available: bool = False

    def dispatch(self, instance: "ActionInstance") -> str:  # pragma: no cover - host integration
        raise NotImplementedError


@dataclass
class ActionInstance:
    instance_id: str
    action: Action
    event_id: str
    created_at: float
    outcome: ActionOutcome = A.REQUESTED
    attempts: int = 0
    authorized_until: float | None = None
    countdown_ends_at: float | None = None
    reason: str = ""
    history: list = field(default_factory=list)

    def move(self, target: ActionOutcome, now: float, reason: str = "") -> None:
        check_transition(ACTION_TRANSITIONS, self.outcome, target)
        self.outcome, self.reason = target, reason
        self.history.append((target.value, now, reason))


class EmergencyWorkflow:
    def __init__(self, config: TrustedConfig | None, dispatcher: Dispatcher | None = None) -> None:
        self.config, self.dispatcher = config, dispatcher
        self.instances: dict[str, ActionInstance] = {}
        self.check_in_due_at: float | None = None
        self.resolved = False
        self.external_actions_blocked: str | None = None  # set on an integrity failure

    @staticmethod
    def instance_id(action_id: str, event_id: str) -> str:
        return hashlib.sha256(f"{action_id}|{event_id}".encode()).hexdigest()[:16]

    def _dispatch_ready(self) -> bool:
        return self.dispatcher is not None and self.dispatcher.available is True

    def request(self, action_id: str, event: HazardEvent, now: float, *,
                host_confirmed: bool = False) -> ActionInstance:
        if self.config is None:
            raise EmergencyUnavailable("no authenticated configuration; no emergency action is approved")
        action = self.config.action(action_id)
        if action is None:
            raise EmergencyUnavailable(f"{action_id!r} is not in the approved action matrix")
        iid = self.instance_id(action_id, event.event_id)
        if iid in self.instances:
            return self.instances[iid]  # deduplicated: never a second call or message
        inst = ActionInstance(iid, action, event.event_id, now)
        inst.history.append((A.REQUESTED.value, now, ""))
        self.instances[iid] = inst
        self.resolved = False

        if self.external_actions_blocked:
            inst.move(A.FAILED, now, f"external actions blocked: {self.external_actions_blocked}")
        elif not self.config.consent_valid(now):
            inst.move(A.FAILED, now, "consent has expired")
        elif (event.hazard is not action.trigger_hazard
              or PRIORITY_RANK[event.priority] < PRIORITY_RANK[action.min_priority]):
            inst.move(A.FAILED, now, "event does not meet the approved trigger")
        elif event.expired(now):
            inst.move(A.FAILED, now, "triggering event has expired")
        elif not self._dispatch_ready():
            inst.move(A.FAILED, now, "emergency action unavailable on this device")
        elif action.requires_host_confirmation and not host_confirmed:
            inst.reason = "waiting for confirmation on the host"
        else:
            self._authorize(inst, now)
        return inst

    def confirm(self, instance_id: str, now: float) -> ActionInstance:
        inst = self.instances[instance_id]
        if inst.outcome is not A.REQUESTED:
            return inst
        if self.external_actions_blocked or not self.config.consent_valid(now):
            inst.move(A.FAILED, now, "consent expired or external actions blocked")
        elif not self._dispatch_ready():
            inst.move(A.FAILED, now, "emergency action unavailable on this device")
        else:
            self._authorize(inst, now)
        return inst

    def _authorize(self, inst: ActionInstance, now: float) -> None:
        inst.move(A.AUTHORIZED, now)
        inst.authorized_until = now + inst.action.expires_after_s
        if inst.action.countdown_s > 0:
            inst.countdown_ends_at = now + inst.action.countdown_s
        else:
            self._attempt(inst, now)

    def tick(self, now: float) -> None:
        for inst in list(self.instances.values()):
            if inst.outcome is not A.AUTHORIZED:
                continue
            if now >= inst.authorized_until:
                inst.move(A.FAILED, now, "authorization expired before an attempt")
            elif inst.countdown_ends_at is None or now >= inst.countdown_ends_at:
                self._attempt(inst, now)

    def _attempt(self, inst: ActionInstance, now: float) -> None:
        inst.move(A.ATTEMPTED, now)
        inst.countdown_ends_at = None
        inst.attempts += 1
        try:
            result = self.dispatcher.dispatch(inst)
        except Exception as exc:
            result = "failed"
            inst.history.append(("DISPATCH_ERROR", now, exc.__class__.__name__))
        if result == "connected":
            inst.move(A.CONNECTED, now)
        elif result == "sent":
            inst.move(A.SENT, now)
        elif inst.attempts <= inst.action.retry_limit:
            inst.move(A.AUTHORIZED, now, "attempt failed; retry pending")
        else:
            inst.move(A.FAILED, now, "attempt failed; retry limit reached")

    def confirm_delivery(self, instance_id: str, now: float) -> ActionInstance:
        """Only the platform's delivery confirmation reaches DELIVERED."""
        inst = self.instances[instance_id]
        inst.move(A.DELIVERED, now, "platform confirmed delivery")
        return inst

    def report_failure(self, instance_id: str, now: float, reason: str) -> ActionInstance:
        inst = self.instances[instance_id]
        inst.move(A.FAILED, now, reason)
        return inst

    def cancel(self, now: float, *, kind: str | None = None) -> tuple[list[str], list[str]]:
        """Cancel what has not been attempted. Returns (cancelled, not recallable)."""
        cancelled, too_late = [], []
        for inst in self.instances.values():
            if kind is not None and inst.action.kind != kind:
                continue
            if inst.outcome in NOT_ATTEMPTED:
                inst.move(A.CANCELLED, now, "cancelled by the user")
                cancelled.append(inst.action.action_id)
            elif inst.outcome in (A.ATTEMPTED, A.CONNECTED, A.SENT, A.DELIVERED):
                too_late.append(inst.action.action_id)
        if self.check_in_due_at is not None and kind is None:
            self.check_in_due_at = None
        return cancelled, too_late

    def start_check_in(self, due_at: float) -> None:
        self.check_in_due_at, self.resolved = due_at, False

    def check_in_answered(self) -> None:
        self.check_in_due_at = None

    def check_in_overdue(self, now: float) -> bool:
        return self.check_in_due_at is not None and now >= self.check_in_due_at

    def resolve(self) -> None:
        self.resolved, self.check_in_due_at = True, None

    @property
    def state(self) -> EmergencyState:
        if self.resolved:
            return E.RESOLVED
        outcomes = [i.outcome for i in self.instances.values()]
        if A.ATTEMPTED in outcomes or A.SENT in outcomes:
            return E.ATTEMPTING
        if A.CONNECTED in outcomes:
            return E.CONNECTED
        authorized = [i for i in self.instances.values() if i.outcome is A.AUTHORIZED]
        if any(i.countdown_ends_at is not None for i in authorized):
            return E.COUNTDOWN
        if authorized:
            return E.ATTEMPTING
        if self.check_in_due_at is not None or A.REQUESTED in outcomes:
            return E.CHECK_IN
        if outcomes:
            if A.DELIVERED in outcomes:
                return E.DELIVERED
            if all(o is A.CANCELLED for o in outcomes):
                return E.CANCELLED
            return E.FAILED
        return E.IDLE
