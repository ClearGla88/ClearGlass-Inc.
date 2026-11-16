"""Capability states with evidence-gated promotion (SPEC section 1).

A capability moves up one state at a time, and only with the evidence that
state requires. Nothing can be promoted to ACTIVE from this package: ACTIVE
needs runtime-health evidence from a live integration, and none exists here.
A detector cannot become VALIDATED unless its safety contract is complete.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .errors import EvidenceError
from .states import CAPABILITY_ORDER, CapabilityState

C = CapabilityState

REQUIRED_EVIDENCE = {
    C.SPECIFIED: "requirement",
    C.IMPLEMENTED: "code",
    C.VERIFIED: "test",
    C.VALIDATED: "validation_report",
    C.ACTIVE: "runtime_health",
}


@dataclass(frozen=True)
class Evidence:
    kind: str
    reference: str


@dataclass
class Capability:
    name: str
    is_detector: bool = False
    state: CapabilityState = C.REQUESTED
    history: list = field(default_factory=list)


class CapabilityRegistry:
    def __init__(self) -> None:
        self._caps: dict[str, Capability] = {}

    def add(self, name: str, *, is_detector: bool = False) -> Capability:
        if name in self._caps:
            raise EvidenceError(f"capability {name!r} already registered")
        cap = Capability(name, is_detector)
        self._caps[name] = cap
        return cap

    def get(self, name: str) -> Capability:
        try:
            return self._caps[name]
        except KeyError:
            raise EvidenceError(f"unknown capability {name!r}") from None

    def promote(self, name: str, target: CapabilityState, evidence: Evidence,
                *, contract_missing: list[str] | None = None) -> None:
        """Move ``name`` up exactly one state, recording ``evidence``.

        ``contract_missing`` is the output of ``contracts.missing()`` and is
        required when promoting a detector to VALIDATED.
        """
        cap = self.get(name)
        current = CAPABILITY_ORDER.index(cap.state)
        if CAPABILITY_ORDER.index(target) != current + 1:
            raise EvidenceError(
                f"{name}: {cap.state.value} -> {target.value} skips or reverses a state")
        needed = REQUIRED_EVIDENCE[target]
        if evidence.kind != needed or not evidence.reference.strip():
            raise EvidenceError(f"{name}: {target.value} requires {needed!r} evidence with a reference")
        if target is C.VALIDATED and cap.is_detector:
            if contract_missing is None:
                raise EvidenceError(f"{name}: a detector needs its safety contract to be VALIDATED")
            if contract_missing:
                raise EvidenceError(
                    f"{name}: safety contract incomplete: {', '.join(contract_missing)}")
        cap.state = target
        cap.history.append((target.value, evidence))

    def demote(self, name: str, target: CapabilityState, reason: str) -> None:
        cap = self.get(name)
        if CAPABILITY_ORDER.index(target) >= CAPABILITY_ORDER.index(cap.state):
            raise EvidenceError(f"{name}: demotion must lower the state")
        if not reason.strip():
            raise EvidenceError(f"{name}: demotion needs a reason")
        cap.state = target
        cap.history.append((target.value, Evidence("demotion", reason)))

    def at_least(self, state: CapabilityState) -> list[str]:
        floor = CAPABILITY_ORDER.index(state)
        return sorted(n for n, c in self._caps.items() if CAPABILITY_ORDER.index(c.state) >= floor)

    def below(self, state: CapabilityState) -> list[str]:
        floor = CAPABILITY_ORDER.index(state)
        return sorted(n for n, c in self._caps.items() if CAPABILITY_ORDER.index(c.state) < floor)

    def report(self) -> list[tuple[str, str]]:
        return sorted((n, c.state.value) for n, c in self._caps.items())


# What this package can honestly claim. Logic components are tested here;
# anything needing hardware or a host platform is only specified.
_TESTED_LOGIC = {
    "trusted_configuration": "tests/test_gs_config.py",
    "observation_integrity": "tests/test_gs_observation.py",
    "detector_contracts": "tests/test_gs_contracts_hazards.py",
    "safety_policy_engine": "tests/test_gs_emergency.py",
    "alert_controller": "tests/test_gs_alerts.py",
    "health_supervisor": "tests/test_gs_health_commands.py",
    "emergency_workflow_state_machine": "tests/test_gs_emergency.py",
    "user_commands": "tests/test_gs_health_commands.py",
    "audit_log": "tests/test_gs_audit.py",
}
_SPECIFIED_ONLY = {
    "sensor_adapters": False,
    "obstacle_detector": True,
    "fall_detector": True,
    "official_warning_feed": True,
    "headphone_output": False,
    "watch_haptic_fallback": False,
    "emergency_dispatch": False,
    "location_sharing": False,
}


def default_registry() -> CapabilityRegistry:
    reg = CapabilityRegistry()
    for name, test_ref in _TESTED_LOGIC.items():
        reg.add(name)
        reg.promote(name, C.SPECIFIED, Evidence("requirement", "SPEC.md"))
        reg.promote(name, C.IMPLEMENTED, Evidence("code", f"guardian_core ({name})"))
        reg.promote(name, C.VERIFIED, Evidence("test", test_ref))
    for name, is_detector in _SPECIFIED_ONLY.items():
        reg.add(name, is_detector=is_detector)
        reg.promote(name, C.SPECIFIED, Evidence("requirement", "SPEC.md"))
    return reg
