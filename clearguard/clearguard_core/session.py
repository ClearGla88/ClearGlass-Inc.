"""One Guardian session: wires the observation gate, policy engine, alert
controller, emergency workflow, health assessment and audit trail together,
and answers the voice commands (spec sections 15 to 17)."""

from __future__ import annotations

import itertools
from datetime import datetime

from . import ASSISTANT_NAME, DEFAULT_PRINCIPAL, DESIGN_MODE_NOTICE, NO_HAZARD_TEXT
from .alerts import AlertController, UnavailableChannel
from .audit import AuditLog
from .capability import Capability, load_registry
from .commands import REFUSAL, Response, parse
from .config import ALERT_CHANNELS, LOCATION_FIELDS, TrustedConfig, placeholders
from .contracts import load_contracts
from .emergency import PENDING, EmergencyPlatform, EmergencyWorkflow
from .events import HazardEvent, parse_event
from .health import (
    MONITORING,
    PAUSED,
    UNAVAILABLE,
    UNCONFIGURED,
    HostIntegrations,
    Readiness,
    activate,
    assess,
)
from .observation import Admission, ObservationGate
from .policy import ALERT, ESCALATE, Decision, SafetyPolicyEngine
from .timeutil import clock, iso


class Session:
    def __init__(self, *, config: TrustedConfig | None = None, config_status: str = "missing",
                 contracts: dict[str, dict] | None = None, capabilities: list[Capability] | None = None,
                 host: HostIntegrations | None = None, simulation: bool = False,
                 platform: EmergencyPlatform | None = None, audit: AuditLog | None = None,
                 channels: list | None = None):
        self.config = config
        self.config_status = config_status
        self.contracts = contracts if contracts is not None else load_contracts()
        self.capabilities = capabilities if capabilities is not None else load_registry()
        self.host = host or HostIntegrations()
        self.simulation = simulation
        self.gate = ObservationGate()
        self.policy = SafetyPolicyEngine(config, self.contracts, simulation=simulation)
        wanted = config.data["alerting"]["channels"] if config else list(ALERT_CHANNELS)
        volume = config.data["alerting"]["max_volume_pct"] if config else 50
        self.alerts = AlertController(channels or [UnavailableChannel(c) for c in wanted], volume)
        self.emergency = EmergencyWorkflow(config, platform)
        self.audit = audit or AuditLog()
        self.lifecycle = UNCONFIGURED if config is None else UNAVAILABLE
        self.history: list[dict] = []
        self._incidents = itertools.count(1)

    @property
    def principal(self) -> str:
        return self.config.principal if self.config else DEFAULT_PRINCIPAL

    def readiness(self, now: datetime) -> Readiness:
        return assess(self.config, self.config_status, self.contracts, self.capabilities, self.host, now)

    def missing_setup(self) -> list[str]:
        if self.config is None:
            return [(
                "a signed configuration: fill in clearguard.example.json, create a key with "
                "'clearguard keygen', then 'clearguard sign-config'"
            )]
        return [f"configuration value {path}" for path in placeholders(self.config.data)]

    def startup(self, now: datetime) -> list[str]:
        r = self.readiness(now)
        lines = [
            (f"{self.principal}, {ASSISTANT_NAME} is not monitoring yet. I will verify authorized devices, "
             "sensor coverage, alert delivery, and emergency preferences."),
            f"Mode: {r.mode} (lifecycle {r.lifecycle})",
            "Verified capabilities (software tested against stated requirements, not field-validated):",
            *[f"  - {title}" for title in r.verified_capabilities],
            "Unsupported hazards:",
            *[f"  - {h}" for h in r.unsupported_hazards],
            "Active permissions: " + (", ".join(f"{k}={v}" for k, v in r.permissions.items()) or "none reported by a host"),
            f"Coverage: {r.coverage}",
            *[f"  - {d.detector_id} ({d.hazard}): " + ("available" if d.available else "; ".join(d.limitations))
              for d in r.detectors],
            "Headphone and fallback test results:",
            *[f"  - {ch}: {result}" for ch, result in r.channel_tests.items()],
            f"Emergency authorization: {r.emergency_authorization}",
            f"Remaining readiness failures: {len(r.failures)}",
            *[f"  - {f}" for f in r.failures],
        ]
        missing = self.missing_setup()
        if missing:
            lines.append("Missing setup information:")
            lines += [f"  - {m}" for m in missing]
        if not self.host.live:
            lines.append(DESIGN_MODE_NOTICE)
        return lines

    def try_activate(self, now: datetime) -> tuple[bool, str]:
        ok, message = activate(self.readiness(now), self.host)
        if ok:
            self.lifecycle = MONITORING
        self.audit.append("activation", {"granted": ok, "message": message}, now)
        return ok, message

    # Inputs -------------------------------------------------------------

    def observe(self, raw: object, now: datetime) -> Admission:
        admission = self.gate.admit(raw, now)
        self.audit.append("observation", {
            "observation_id": admission.observation_id, "status": admission.status, "reasons": admission.reasons,
        }, now)
        return admission

    def raise_event(self, raw: object, now: datetime) -> tuple[Decision, list]:
        if isinstance(raw, HazardEvent):
            event, problems = raw, []
        else:
            event, problems = parse_event(raw)
        if event is None:
            event_id = raw.get("event_id", "?") if isinstance(raw, dict) else "?"
            decision = Decision("REJECTED", str(event_id), problems, simulated=self.simulation)
            self.audit.append("decision", {"event_id": decision.event_id, "outcome": decision.outcome,
                                           "reasons": decision.reasons}, now)
            return decision, []
        decision = self.policy.evaluate(event, now, set(self.gate.admitted))
        deliveries = []
        if decision.outcome in (ALERT, ESCALATE) and decision.alert is not None:
            deliveries = self.alerts.dispatch(decision.alert, now)
            self.history.append({"event": event, "decision": decision, "deliveries": deliveries})
        self.audit.append("decision", {
            "event_id": event.event_id, "detector_id": event.detector_id, "outcome": decision.outcome,
            "reasons": decision.reasons, "alert_id": decision.alert.alert_id if decision.alert else None,
            "template": decision.alert.template_id if decision.alert else None,
            "deliveries": [d.state for d in deliveries], "proposed_actions": decision.proposed_actions,
            "simulated": decision.simulated,
        }, now)
        return decision, deliveries

    # Commands -----------------------------------------------------------

    def command(self, text: str, now: datetime) -> Response:
        name = parse(text)
        if name is None:
            response = Response(None, REFUSAL)
        else:
            response = getattr(self, f"_cmd_{name}")(now)
            response.command = name
        self.audit.append("command", {"command": response.command, "confirmed": response.confirmed}, now)
        return response

    def _cmd_status(self, now: datetime) -> Response:
        r = self.readiness(now)
        text = (
            f"Mode {r.mode}. Lifecycle {self.lifecycle}. Coverage {r.coverage}. Alert routing {r.routing}. "
            f"Connectivity {r.connectivity}. Integrity {r.integrity}."
        )
        current = [h for h in self.history if h["decision"].alert.is_current(now)]
        if self.lifecycle == MONITORING and r.coverage != "NONE" and not current:
            text += f" {NO_HAZARD_TEXT}"
        if not self.host.live:
            text += f" {DESIGN_MODE_NOTICE}"
        return Response(None, text)

    def _cmd_unavailable(self, now: datetime) -> Response:
        r = self.readiness(now)
        parts = [f"{d.detector_id}: {'; '.join(d.limitations)}" for d in r.detectors if not d.available]
        parts += [f"{ch}: {res}" for ch, res in r.channel_tests.items() if res != "passed"]
        text = "Unavailable: " + (" | ".join(parts) if parts else "nothing in the configured scope") + ". "
        text += "Not supported by design: " + ", ".join(r.unsupported_hazards) + "."
        return Response(None, text)

    def _last(self) -> dict | None:
        return self.history[-1] if self.history else None

    def _cmd_why(self, now: datetime) -> Response:
        last = self._last()
        if last is None:
            return Response(None, "No alert has been issued in this session.")
        event, alert = last["event"], last["decision"].alert
        sources = ", ".join(event.observation_ids) or "application state"
        text = (
            f"Alert {alert.alert_id} at {clock(alert.created_at)}: \"{alert.spoken()}\" "
            f"Event {event.event_id} from detector {event.detector_id}; sources: {sources}. "
            f"Observed: {'; '.join(f.rstrip('.') for f in event.observed_facts)}."
        )
        if event.limitations:
            text += f" Limitations: {'; '.join(x.rstrip('.') for x in event.limitations)}."
        return Response(None, text)

    def _cmd_repeat(self, now: datetime) -> Response:
        last = self._last()
        if last is None:
            return Response(None, "No alert has been issued in this session.")
        return Response(None, last["decision"].alert.replay_text(now))

    def _cmd_pause(self, now: datetime) -> Response:
        if self.lifecycle != MONITORING:
            return Response(None, f"Not monitoring (lifecycle {self.lifecycle}), so there is nothing to pause.")
        self.lifecycle = PAUSED
        return Response(None, "Paused. Guardian is not monitoring.", confirmed=True)

    def _cmd_resume(self, now: datetime) -> Response:
        if self.lifecycle != PAUSED:
            return Response(None, "Not paused. Monitoring starts only through the app's activation checks.")
        ok, message = self.try_activate(now)
        if not ok:
            self.lifecycle = UNAVAILABLE
        return Response(None, message, confirmed=ok)

    def _cmd_stop_sharing(self, now: datetime) -> Response:
        pending = [r for r in self.emergency.records.values()
                   if r.state in PENDING and set(r.payload) & LOCATION_FIELDS]
        messages = []
        for record in pending:
            messages += self.emergency.cancel(now, record.incident_id)
        sent = [r for r in self.emergency.records.values()
                if r.state not in PENDING and set(r.payload) & LOCATION_FIELDS and r.attempts]
        if sent:
            messages.append("Location already sent cannot be recalled.")
        if not messages:
            messages.append("No location sharing is active in this session.")
        return Response(None, " ".join(messages), confirmed=bool(pending))

    def _cmd_delete_recent(self, now: datetime) -> Response:
        alerts, observations = len(self.history), len(self.gate.admitted)
        self.history.clear()
        self.gate.admitted.clear()
        self.audit.append("deleted_recent_data", {"alerts": alerts, "observations": observations}, now)
        return Response(None, (
            f"Deleted {alerts} alert record(s) and {observations} observation(s) held in this session. "
            "The audit trail keeps minimal records without location or media. Anything already sent to "
            "a contact, or copied to a backup, is not deleted by this command."
        ), confirmed=True)

    def _cmd_emergency_help(self, now: datetime) -> Response:
        incident = f"I{next(self._incidents):04d}"
        result = self.emergency.request("explicit_help_request", incident, now, facts={
            "help_request": True, "event_time": iso(now), "event_category": "explicit_help_request",
        })
        confirmed = any(r.state in ("CONNECTED", "SENT", "DELIVERED") for r in result.records)
        text = f"Help request received (incident {incident}). " + " ".join(result.messages)
        return Response(None, text.strip(), confirmed=confirmed)

    def _cmd_confirm(self, now: datetime) -> Response:
        waiting = sorted({r.incident_id for r in self.emergency.records.values() if r.state == "REQUESTED"})
        if not waiting:
            return Response(None, "Nothing is waiting for confirmation.")
        result = self.emergency.confirm(waiting[-1], now)
        confirmed = any(r.state in ("CONNECTED", "SENT", "DELIVERED") for r in result.records)
        return Response(None, " ".join(result.messages), confirmed=confirmed)

    def _cmd_cancel_escalation(self, now: datetime) -> Response:
        messages = self.emergency.cancel(now)
        confirmed = any("cancelled before anything was sent" in m for m in messages)
        return Response(None, " ".join(messages), confirmed=confirmed)
