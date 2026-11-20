"""State, coverage and readiness (spec sections 2, 8, 13 and 17).

Lifecycle and the four health dimensions are tracked separately. Coverage is
judged per detector against the configured scope, never against "every
danger". Activation needs a live host, validated detectors, a verified output
channel and a trusted configuration; this build has no live host, so it always
refuses and says so.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from . import DESIGN_MODE_NOTICE
from . import contracts as contracts_mod
from .capability import Capability, Level
from .config import ALERT_CHANNELS, TrustedConfig, placeholders

UNCONFIGURED = "UNCONFIGURED"
SELF_TEST = "SELF_TEST"
READY = "READY"
MONITORING = "MONITORING"
PAUSED = "PAUSED"
UNAVAILABLE = "UNAVAILABLE"

# Hazards no detector in this design can support; they are reported, not attempted.
UNSUPPORTED_HAZARDS = (
    "another person's intent",
    "being followed or surveilled",
    "concealed weapons",
    "toxic substances, radiation or explosives",
    "medical emergencies or diagnoses",
    "lane-level crossing safety",
    "anything outside the configured, validated scope",
)


@dataclass
class HostIntegrations:
    """What the host application actually exposes. Every field defaults to
    'nothing', which is exactly what this build has."""

    live: bool = False
    sensors: dict[str, str] = field(default_factory=dict)  # sensor -> permission state
    outputs: dict[str, bool] = field(default_factory=dict)  # channel -> passed a playback test
    emergency_interface: bool = False
    connectivity: str = "UNKNOWN"
    background_execution: bool | None = None
    battery_pct: float | None = None
    thermal_state: str | None = None


@dataclass
class DetectorStatus:
    detector_id: str
    hazard: str
    available: bool
    limitations: list[str]


@dataclass
class Readiness:
    lifecycle: str
    mode: str
    config_status: str
    connectivity: str
    coverage: str
    routing: str
    integrity: str
    detectors: list[DetectorStatus]
    verified_capabilities: list[str]
    permissions: dict[str, str]
    channel_tests: dict[str, str]
    emergency_authorization: str
    failures: list[str]
    unsupported_hazards: tuple[str, ...] = UNSUPPORTED_HAZARDS


def _in_scope(contract: dict, configured_sensors: set[str]) -> bool:
    if contract["implementation"] == "app_state":
        return True
    return bool(set(contract["required_inputs"]) & configured_sensors)


def assess(config: TrustedConfig | None, config_status: str, contracts: dict[str, dict],
           capabilities: list[Capability], host: HostIntegrations, now: datetime) -> Readiness:
    failures: list[str] = []
    if config is None:
        failures.append(f"trusted configuration not loaded ({config_status})")
    else:
        unresolved = placeholders(config.data)
        if unresolved:
            failures.append(f"configuration has {len(unresolved)} unresolved value(s): {', '.join(unresolved[:5])}")
        if not config.consent_active(now):
            failures.append("consent is expired, revoked or not yet in effect")
    if not host.live:
        failures.append("no live host integration: sensors, headphone output and emergency interface are absent")

    configured_sensors = config.sensors() if config else set()
    detectors: list[DetectorStatus] = []
    for contract in contracts.values():
        if config is not None and not _in_scope(contract, configured_sensors):
            continue
        limits: list[str] = []
        if not contracts_mod.is_validated(contract):
            limits.append("detector not validated")
        if not host.live:
            limits.append("no live host integration")
        for sensor in contract["required_inputs"]:
            if sensor in configured_sensors or contract["implementation"] != "app_state":
                state = host.sensors.get(sensor, "unavailable")
                if state != "granted":
                    limits.append(f"input {sensor}: {state}")
        detectors.append(DetectorStatus(contract["detector_id"], contract["hazard"], not limits, limits))
    for status in detectors:
        if not status.available:
            failures.append(f"{status.detector_id}: " + "; ".join(status.limitations))

    available = [d for d in detectors if d.available]
    if not detectors or not available:
        coverage = "NONE"
    elif len(available) == len(detectors):
        coverage = "FULL_FOR_CONFIGURED_SCOPE"
    else:
        coverage = "PARTIAL"

    wanted = config.data["alerting"]["channels"] if config else list(ALERT_CHANNELS)
    channel_tests = {
        ch: ("passed" if host.outputs.get(ch) else "not tested: no host integration" if not host.live else "failed")
        for ch in wanted
    }
    passed = [ch for ch, result in channel_tests.items() if result == "passed"]
    routing = "AVAILABLE" if len(passed) == len(wanted) else "DEGRADED" if passed else "FAILED"
    if routing == "FAILED":
        failures.append("no alert channel has passed a delivery test")

    if config_status == "invalid":
        integrity = "SUSPECTED_FAILURE"
    elif config is not None:
        integrity = "VERIFIED_AS_CONFIGURED"
    else:
        integrity = "UNVERIFIED"

    if config is None:
        emergency = "not configured"
    elif not config.consent_active(now):
        emergency = "blocked: consent not in effect"
    else:
        count = len(config.data["actions"])
        interface = "emergency interface available" if host.emergency_interface else "no emergency interface in this build"
        emergency = f"{count} action(s) approved in the signed configuration; {interface}"
    if config is not None and config.data["actions"] and not host.emergency_interface:
        failures.append("approved emergency actions cannot run: no emergency interface")

    lifecycle = UNCONFIGURED if config is None else (READY if not failures else UNAVAILABLE)
    return Readiness(
        lifecycle=lifecycle,
        mode=config.mode if config else "design",
        config_status=config_status,
        connectivity=host.connectivity,
        coverage=coverage,
        routing=routing,
        integrity=integrity,
        detectors=detectors,
        verified_capabilities=[c.title for c in capabilities if c.level >= Level.VERIFIED],
        permissions=dict(host.sensors),
        channel_tests=channel_tests,
        emergency_authorization=emergency,
        failures=failures,
    )


def activate(readiness: Readiness, host: HostIntegrations) -> tuple[bool, str]:
    """The only path to MONITORING. Refuses unless every readiness check passes."""
    if readiness.failures or not host.live:
        note = f" {DESIGN_MODE_NOTICE}" if not host.live else ""
        return False, f"Activation refused: {len(readiness.failures)} readiness failure(s) remain.{note}"
    return True, "Monitoring started for the configured, validated scope only."


def stale_inputs(last_seen: dict[str, datetime], limits: dict[str, float], now: datetime) -> list[str]:
    """Inputs whose newest sample is older than their freshness limit. An input
    never seen at all counts as stale: silence is not evidence of safety."""
    stale = []
    for name, limit in sorted(limits.items()):
        seen = last_seen.get(name)
        if seen is None or (now - seen).total_seconds() > limit:
            stale.append(name)
    return stale
