"""Health supervisor (SPEC sections 8 and 13).

Lifecycle and the four health dimensions are tracked separately, so being
offline can coexist with healthy local monitoring. Coverage is computed only
against the configured, validated scope, never "every danger". An adapter
counts as covering only with a granted permission, a healthy sensor and an
observation inside its freshness limit: silence is not evidence of safety.
"""

from __future__ import annotations

from dataclasses import dataclass

from .states import (LIFECYCLE_TRANSITIONS, Connectivity, Coverage, Integrity, Lifecycle, Routing,
                     check_transition)


@dataclass
class AdapterStatus:
    name: str
    sensor: str
    freshness_s: float
    permission: str = "unknown"
    healthy: bool = False
    last_observation_at: float | None = None

    def fresh(self, now: float) -> bool:
        return (self.permission == "granted" and self.healthy and self.last_observation_at is not None
                and 0 <= now - self.last_observation_at <= self.freshness_s)


class HealthSupervisor:
    def __init__(self, adapters=(), channels=()) -> None:
        self.adapters = {a.name: a for a in adapters}
        self.channels = list(channels)
        self.lifecycle = Lifecycle.UNCONFIGURED
        self.connectivity = Connectivity.UNKNOWN
        self.integrity = Integrity.UNVERIFIED
        self.faults: list[str] = []

    def move(self, target: Lifecycle) -> None:
        check_transition(LIFECYCLE_TRANSITIONS, self.lifecycle, target)
        self.lifecycle = target

    def coverage(self, now: float, configured: bool) -> Coverage:
        if not configured:
            return Coverage.UNKNOWN
        if not self.adapters:
            return Coverage.NONE
        fresh = sum(a.fresh(now) for a in self.adapters.values())
        if fresh == len(self.adapters):
            return Coverage.FULL_FOR_CONFIGURED_SCOPE
        return Coverage.PARTIAL if fresh else Coverage.NONE

    def routing(self) -> Routing:
        verified = [c for c in self.channels if c.verified is True]
        if not self.channels:
            return Routing.FAILED
        if len(verified) == len(self.channels):
            return Routing.AVAILABLE
        if verified:
            return Routing.DEGRADED
        if any(c.verified is None for c in self.channels):
            return Routing.UNKNOWN
        return Routing.FAILED

    def report_integrity_fault(self, component: str, observed_fault: str) -> None:
        """Record what was observed, not a guess about who caused it."""
        self.integrity = Integrity.SUSPECTED_FAILURE
        self.faults.append(f"{component}: {observed_fault}")

    def readiness_failures(self, config, now: float, self_test_passed: bool) -> list[str]:
        failures = []
        if config is None:
            failures.append("no authenticated configuration loaded")
        elif not config.consent_valid(now):
            failures.append("consent has expired")
        if not any(a.fresh(now) for a in self.adapters.values()):
            failures.append("no sensor adapter is providing fresh, permitted input")
        if not any(c.verified is True for c in self.channels):
            failures.append("no alert channel has passed its delivery test")
        if self.integrity is Integrity.SUSPECTED_FAILURE:
            failures.append("integrity fault recorded: " + "; ".join(self.faults))
        if not self_test_passed:
            failures.append("self-test has not passed")
        return failures
