"""Safety-policy engine (spec section 4).

Deterministic. Every hazard event passes through here before any alert or
external action, and no language model sits on this path. It checks event
validity, contract status, freshness, consent and duplicates, then picks a
pre-approved template. It proposes external actions; it never executes them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from . import contracts as contracts_mod
from .alerts import Alert, build_alert
from .config import TrustedConfig
from .events import APP_SOURCED, HazardEvent, event_problems

ALERT = "ALERT"
ESCALATE = "ESCALATE"  # a higher-priority alert on a hazard already alerted
SUPPRESSED_DUPLICATE = "SUPPRESSED_DUPLICATE"
EXPIRED = "EXPIRED"
REJECTED = "REJECTED"


@dataclass
class Decision:
    outcome: str
    event_id: str
    reasons: list[str] = field(default_factory=list)
    alert: Alert | None = None
    proposed_actions: list[str] = field(default_factory=list)
    simulated: bool = False


class SafetyPolicyEngine:
    """``simulation=True`` lets contracts that are not validated produce alerts,
    every one of them marked [SIMULATED]. With ``simulation=False`` an alert
    requires a validated contract."""

    def __init__(self, config: TrustedConfig | None, contracts: dict[str, dict], *, simulation: bool):
        self.config = config
        self.contracts = contracts
        self.simulation = simulation
        self._active: dict[tuple[str, str], Alert] = {}

    def evaluate(self, event: HazardEvent, now: datetime, admitted: set[str] | None = None) -> Decision:
        def decide(outcome: str, *reasons: str) -> Decision:
            return Decision(outcome, event.event_id, list(reasons), simulated=self.simulation)

        problems = event_problems(event)
        if problems:
            return decide(REJECTED, *problems)

        contract = self.contracts.get(event.detector_id)
        if contract is None:
            return decide(REJECTED, f"no detector contract for '{event.detector_id}'")
        if contract["hazard"] != event.category:
            return decide(REJECTED, f"detector '{event.detector_id}' is not contracted for '{event.category}'")
        if event.confidence is not None and not contract["calibrated_confidence"]:
            return decide(REJECTED, "confidence supplied by a detector without calibration evidence")
        validated = contracts_mod.is_validated(contract)
        if not validated and not self.simulation:
            return decide(REJECTED, f"detector '{event.detector_id}' is not validated; it cannot alert in operation")

        if event.category not in APP_SOURCED:
            known = admitted if admitted is not None else set()
            missing = [oid for oid in event.observation_ids if oid not in known]
            if missing:
                return decide(REJECTED, "cites observations that were not admitted: " + ", ".join(missing))

        if now >= event.expires_at:
            return decide(EXPIRED, "event expired before evaluation")
        max_age = contract.get("max_event_age_s")
        if isinstance(max_age, (int, float)) and (now - event.created_at).total_seconds() > max_age:
            return decide(EXPIRED, f"event older than the contract's {max_age:g} s limit")

        key = (event.detector_id, event.category)
        prior = self._active.get(key)
        outcome = ALERT
        if prior is not None and prior.is_current(now):
            if event.priority <= prior.priority:
                return decide(SUPPRESSED_DUPLICATE, f"alert {prior.alert_id} on this hazard is still current")
            outcome = ESCALATE

        alert = build_alert(
            contract["alert_template"], event.event_id, event.detector_id, now, event.expires_at,
            simulated=self.simulation or not validated,
        )
        self._active[key] = alert
        decision = Decision(outcome, event.event_id, [], alert, simulated=alert.simulated)
        if not validated:
            decision.reasons.append("detector not validated: simulation only")

        if self.config is not None:
            actions = [a["action_id"] for a in self.config.actions_for(event.category)]
            if actions and not self.config.consent_active(now):
                decision.reasons.append("consent expired or revoked: external actions blocked")
            else:
                decision.proposed_actions = actions
        return decision

    def clear(self, detector_id: str, category: str) -> None:
        self._active.pop((detector_id, category), None)
