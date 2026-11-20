"""The Guardian facade: startup report, activation gates and user commands
(SPEC sections 8, 15, 16 and 17).

Every reply is built from recorded state. A command reports success
(``confirmed=True``) only when the state change actually happened here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from . import DESIGN_MODE_STATEMENT, NO_HAZARD_STATEMENT, STARTUP_LINE
from .alerts import AlertController
from .audit import AuditLog
from .capability import default_registry
from .emergency import EmergencyUnavailable, EmergencyWorkflow
from .hazards import UNSUPPORTED_HAZARDS, HazardEvent, HazardKind, make_event
from .health import HealthSupervisor
from .observation import ObservationGate, Verdict
from .states import ActionOutcome, CapabilityState, Coverage, Lifecycle, Priority

NATIVE_EMERGENCY_ADVICE = "If you need help now, use your phone's emergency call."


@dataclass(frozen=True)
class Reply:
    text: str
    confirmed: bool


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


class Guardian:
    def __init__(self, *, config=None, adapters=(), channels=(), dispatcher=None,
                 dedupe_window_s: float | None = None, max_rate=None, audit_key: bytes | None = None) -> None:
        self.config = config
        self.health = HealthSupervisor(adapters, channels)
        self.alerts = AlertController(channels, dedupe_window_s)
        self.emergency = EmergencyWorkflow(config, dispatcher)
        self.gate = ObservationGate(max_rate)
        self.audit = AuditLog(audit_key)
        self.capabilities = default_registry()
        self.self_test_passed = False
        self.events: dict[str, HazardEvent] = {}
        self._help_n = 0

    # --- mode -----------------------------------------------------------------
    @property
    def design_mode(self) -> bool:
        """No live integration of any kind is attached."""
        return (not self.health.adapters and not self.health.channels
                and (self.emergency.dispatcher is None or not self.emergency.dispatcher.available))

    # --- ingestion and alerting -------------------------------------------------
    def ingest(self, raw, now: float):
        admission = self.gate.admit(raw, now)
        obs = admission.observation
        if admission.verdict is Verdict.ACCEPT and obs is not None and obs.source_id in self.health.adapters:
            self.health.adapters[obs.source_id].last_observation_at = obs.event_ts
        self.audit.record("observation", {"verdict": admission.verdict.value,
                                          "reasons": list(admission.reasons)}, now)
        return admission

    def raise_hazard(self, event: HazardEvent, template_id: str, now: float):
        self.events[event.event_id] = event
        alert = self.alerts.raise_alert(event, template_id, now)
        self.audit.record("alert", {"event_id": event.event_id, "template": template_id,
                                    "state": alert.state.value if alert else "SUPPRESSED"}, now)
        return alert

    def report_integrity_fault(self, component: str, observed_fault: str, now: float) -> None:
        """Isolate external actions; local alerting keeps working."""
        self.health.report_integrity_fault(component, observed_fault)
        self.emergency.external_actions_blocked = f"{component}: {observed_fault}"
        self.audit.record("integrity_fault", {"component": component, "fault": observed_fault}, now)

    # --- lifecycle --------------------------------------------------------------
    def self_test(self, now: float) -> list[str]:
        if self.health.lifecycle is not Lifecycle.SELF_TEST:
            self.health.move(Lifecycle.SELF_TEST)
        failures = self.health.readiness_failures(self.config, now, True)
        self.self_test_passed = not failures
        self.health.move(Lifecycle.READY if self.self_test_passed else Lifecycle.UNAVAILABLE)
        self.audit.record("self_test", {"passed": self.self_test_passed, "failures": failures}, now)
        return failures

    def activate(self, now: float) -> list[str]:
        """Enter MONITORING only from READY and only if every check passes now."""
        failures = self.health.readiness_failures(self.config, now, self.self_test_passed)
        if self.health.lifecycle not in (Lifecycle.READY, Lifecycle.PAUSED):
            failures.insert(0, f"lifecycle is {self.health.lifecycle.value}, not READY")
        if not failures:
            self.health.move(Lifecycle.MONITORING)
        self.audit.record("activate", {"ok": not failures, "failures": failures}, now)
        return failures

    # --- reports ----------------------------------------------------------------
    def status_lines(self, now: float) -> list[str]:
        coverage = self.health.coverage(now, self.config is not None)
        lines = []
        if self.design_mode:
            lines.append(DESIGN_MODE_STATEMENT)
        lines += [
            f"Lifecycle: {self.health.lifecycle.value}.",
            f"Connectivity: {self.health.connectivity.value}. Coverage: {coverage.value}. "
            f"Alert routing: {self.health.routing().value}. Integrity: {self.health.integrity.value}.",
            f"Emergency workflow: {self.emergency.state.value}.",
        ]
        active = self.alerts.active(now)
        if self.health.lifecycle is not Lifecycle.MONITORING:
            lines.append("Not monitoring.")
        elif active:
            lines.append(f"Active alert: {active[-1].text}")
        elif coverage in (Coverage.FULL_FOR_CONFIGURED_SCOPE, Coverage.PARTIAL):
            lines.append(NO_HAZARD_STATEMENT + (" Coverage is partial." if coverage is Coverage.PARTIAL else ""))
        else:
            lines.append("No sensor input is covering the configured scope.")
        return lines

    def unavailable_lines(self, now: float) -> list[str]:
        below = self.capabilities.below(CapabilityState.ACTIVE)
        lines = ["Not active: " + ", ".join(below) + "."]
        lines += ["Readiness failure: " + f for f in
                  self.health.readiness_failures(self.config, now, self.self_test_passed)]
        lines.append("Never supported: " + ", ".join(UNSUPPORTED_HAZARDS) + ".")
        return lines

    def startup_report(self, now: float) -> str:
        verified = self.capabilities.at_least(CapabilityState.VERIFIED)
        permissions = sorted(a.name for a in self.health.adapters.values() if a.permission == "granted")
        if self.config is None:
            emergency = "none (no authenticated configuration)"
        elif not self.config.consent_valid(now):
            emergency = "consent expired"
        else:
            emergency = f"{len(self.config.actions)} approved action(s); dispatcher " + (
                "available" if self.emergency._dispatch_ready() else "unavailable")
        tested = [f"{c.name}: {'passed' if c.verified else 'failed' if c.verified is False else 'not tested'}"
                  for c in self.health.channels]
        lines = [STARTUP_LINE]
        if self.design_mode:
            lines.append(DESIGN_MODE_STATEMENT)
        lines += [
            f"Mode: {'DESIGN' if self.design_mode else 'INTEGRATED'}. Lifecycle: {self.health.lifecycle.value}.",
            "Verified capabilities (logic tested here; none validated in the field): " + ", ".join(verified) + ".",
            "Unsupported hazards: " + ", ".join(UNSUPPORTED_HAZARDS) + ".",
            "Active permissions: " + (", ".join(permissions) if permissions else "none") + ".",
            f"Coverage: {self.health.coverage(now, self.config is not None).value}.",
            "Headphone and fallback tests: " + ("; ".join(tested) if tested else "not run (no output channel attached)") + ".",
            f"Emergency authorization: {emergency}.",
        ]
        failures = self.health.readiness_failures(self.config, now, self.self_test_passed)
        lines.append("Remaining readiness failures: " + ("; ".join(failures) if failures else "none") + ".")
        return "\n".join(lines)

    # --- commands ---------------------------------------------------------------
    _PREFIX = re.compile(r"^\s*guardian[,\s]+", re.IGNORECASE)

    def command(self, text: str, now: float) -> Reply:
        if not self._PREFIX.match(text or ""):
            return Reply("Commands start with 'Guardian'.", False)
        verb = self._PREFIX.sub("", text).strip().lower().rstrip(".?!").strip()
        handler = {
            "status": self._cmd_status,
            "what is unavailable": self._cmd_unavailable,
            "why did you alert": self._cmd_why,
            "repeat the last alert": self._cmd_repeat,
            "pause": self._cmd_pause,
            "resume": self._cmd_resume,
            "stop sharing": self._cmd_stop_sharing,
            "delete recent data": self._cmd_delete,
            "emergency help": self._cmd_help,
            "cancel escalation": self._cmd_cancel,
        }.get(verb)
        if handler is None:
            return Reply("Not a supported command.", False)
        reply = handler(now)
        self.audit.record("command", {"command": verb, "confirmed": reply.confirmed}, now)
        return reply

    def _cmd_status(self, now):
        return Reply("\n".join(self.status_lines(now)), True)

    def _cmd_unavailable(self, now):
        return Reply("\n".join(self.unavailable_lines(now)), True)

    def _cmd_why(self, now):
        alert = self.alerts.last()
        if alert is None:
            return Reply("No alert has been raised in this session.", True)
        ev = alert.event
        when = "now expired" if ev.expired(now) else "still current"
        parts = [f"Alert {alert.alert_id} at {_iso(alert.created_at)} ({when}): {ev.hazard.value} "
                 f"from {ev.detector_id}, event {ev.event_id}.",
                 "Observations: " + (", ".join(ev.observation_ids) or "none (user-originated)") + ".",
                 "Observed: " + "; ".join(ev.observed_facts) + "."]
        if ev.limitations:
            parts.append("Limitations: " + "; ".join(ev.limitations) + ".")
        parts.append(f"Delivery: {alert.state.value}.")
        return Reply(" ".join(parts), True)

    def _cmd_repeat(self, now):
        text = self.alerts.repeat_last(now)
        return Reply(text or "No alert has been raised in this session.", True)

    def _cmd_pause(self, now):
        if self.health.lifecycle is not Lifecycle.MONITORING:
            return Reply("Not monitoring, so there is nothing to pause.", False)
        self.health.move(Lifecycle.PAUSED)
        return Reply("Paused. Not monitoring until you say 'Guardian, resume.'", True)

    def _cmd_resume(self, now):
        if self.health.lifecycle is not Lifecycle.PAUSED:
            return Reply(f"Cannot resume from {self.health.lifecycle.value}.", False)
        failures = self.activate(now)
        if failures:
            return Reply("Not resumed: " + "; ".join(failures) + ".", False)
        return Reply("Monitoring resumed.", True)

    def _cmd_stop_sharing(self, now):
        cancelled, too_late = self.emergency.cancel(now, kind="share_location")
        if not cancelled and not too_late:
            return Reply("No location sharing is active.", False)
        parts = []
        if cancelled:
            parts.append("Cancelled before sending: " + ", ".join(cancelled) + ".")
        if too_late:
            parts.append("Already sent and cannot be recalled: " + ", ".join(too_late) + ".")
        return Reply(" ".join(parts), bool(cancelled))

    def _cmd_delete(self, now):
        n_alerts, n_events = len(self.alerts.alerts), len(self.events)
        self.alerts.alerts.clear()
        self.events.clear()
        self.gate.quarantine.clear()
        return Reply(
            f"Deleted {n_alerts} alert(s) and {n_events} event(s) held in this session's memory. "
            "The audit log keeps minimal records without location or media. "
            "Copies already sent to other people or services are not affected.", True)

    def _cmd_help(self, now):
        cfg = self.config
        actions = cfg.actions_for(HazardKind.HELP_REQUEST) if cfg is not None else []
        if not actions or not self.emergency._dispatch_ready():
            return Reply("Emergency action unavailable in this build. " + NATIVE_EMERGENCY_ADVICE, False)
        self._help_n += 1
        event = make_event(
            event_id=f"help-{int(now)}-{self._help_n}", hazard=HazardKind.HELP_REQUEST,
            priority=Priority.CRITICAL, detector_id="user", created_at=now,
            max_age_s=max(a.expires_after_s for a in actions), observation_ids=(),
            observed_facts=("user said 'Guardian, emergency help'",))
        self.raise_hazard(event, "help_request_received", now)
        lines, started = [], False
        for action in actions:
            try:
                inst = self.emergency.request(action.action_id, event, now)
            except EmergencyUnavailable as exc:
                lines.append(f"{action.action_id}: unavailable ({exc}).")
                continue
            if inst.outcome is ActionOutcome.AUTHORIZED and inst.countdown_ends_at is not None:
                started = True
                lines.append(f"{action.action_id}: starts in {action.countdown_s} s. "
                             "Say 'Guardian, cancel escalation' to stop it.")
            elif inst.outcome in (ActionOutcome.CONNECTED, ActionOutcome.SENT, ActionOutcome.ATTEMPTED):
                started = True
                lines.append(f"{action.action_id}: {inst.outcome.value.lower()}; delivery not yet confirmed.")
            else:
                lines.append(f"{action.action_id}: {inst.outcome.value.lower()} ({inst.reason}).")
        if not started:
            lines.append(NATIVE_EMERGENCY_ADVICE)
        return Reply(" ".join(lines), started)

    def _cmd_cancel(self, now):
        cancelled, too_late = self.emergency.cancel(now)
        if not cancelled and not too_late:
            return Reply("Nothing is escalating.", False)
        parts = []
        if cancelled:
            parts.append("Cancelled: " + ", ".join(cancelled) + ".")
        if too_late:
            parts.append("Already attempted and cannot be recalled: " + ", ".join(too_late) + ".")
        return Reply(" ".join(parts), bool(cancelled))

