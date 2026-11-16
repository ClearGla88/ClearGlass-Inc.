import copy

import pytest
from cg_testlib import event, validated_contract
from clearguard_core.config import TrustedConfig
from clearguard_core.contracts import is_validated, load_contracts, validation_gaps
from clearguard_core.events import parse_event
from clearguard_core.policy import (
    ALERT,
    ESCALATE,
    EXPIRED,
    REJECTED,
    SUPPRESSED_DUPLICATE,
    SafetyPolicyEngine,
)


def ev(**kw):
    parsed, problems = parse_event(event(**kw))
    assert parsed is not None, problems
    return parsed


def test_shipped_contracts_are_well_formed_and_none_is_validated():
    contracts = load_contracts()
    assert len(contracts) == 6
    for contract in contracts.values():
        assert not is_validated(contract)
        gaps = validation_gaps(contract)
        assert "no approving review by an accountable reviewer" in gaps
        # No reliability or timing target is invented in the shipped file.
        assert contract["acceptance_criteria"]["missed_event_rate_max"] is None
        assert contract["timing_budget_ms"] is None


def test_validated_fixture_has_no_gaps():
    contract = validated_contract(load_contracts()["platform-fall-detection"])
    assert validation_gaps(contract) == []


def test_simulation_alerts_are_labelled(now, later):
    engine = SafetyPolicyEngine(None, load_contracts(), simulation=True)
    decision = engine.evaluate(ev(), later(1), {"obs-1"})
    assert decision.outcome == ALERT
    assert decision.alert.spoken() == "[SIMULATED] Possible fall detected. Do you need help?"
    assert "detector not validated: simulation only" in decision.reasons


def test_operation_refuses_unvalidated_detectors(later):
    engine = SafetyPolicyEngine(None, load_contracts(), simulation=False)
    decision = engine.evaluate(ev(), later(1), {"obs-1"})
    assert decision.outcome == REJECTED and "not validated" in decision.reasons[0]


def test_validated_detector_alerts_without_simulation_label(later):
    contracts = load_contracts()
    contracts["platform-fall-detection"] = validated_contract(contracts["platform-fall-detection"])
    engine = SafetyPolicyEngine(None, contracts, simulation=False)
    decision = engine.evaluate(ev(), later(1), {"obs-1"})
    assert decision.outcome == ALERT and not decision.alert.simulated
    assert decision.alert.spoken() == "Possible fall detected. Do you need help?"
    # The contract's own age limit (60 s in the fixture) also expires events.
    old = engine.evaluate(ev(eid="old", at=0, ttl=600), later(90), {"obs-1"})
    assert old.outcome == EXPIRED and "60 s limit" in old.reasons[0]


@pytest.mark.parametrize("kw, reason", [
    ({"detector": "made-up"}, "no detector contract"),
    ({"detector": "camera-obstacle"}, "not contracted for"),
    ({"observations": ("obs-9",)}, "not admitted: obs-9"),
])
def test_rejections(kw, reason, later):
    engine = SafetyPolicyEngine(None, load_contracts(), simulation=True)
    decision = engine.evaluate(ev(**kw), later(1), {"obs-1"})
    assert decision.outcome == REJECTED and reason in decision.reasons[0]


@pytest.mark.parametrize("text", [
    "A man nearby showed hostile intent.",
    "The person is armed with a knife.",
    "The user is being followed.",
    "Toxic gas detected.",
    "The user is unconscious.",
    "Possible stroke.",
])
def test_unsupported_claims_are_rejected(text):
    parsed, problems = parse_event(event(observed_facts=[text]))
    assert parsed is None and any("unsupported claim" in p for p in problems)


def test_inferences_are_screened_but_unknowns_may_name_limits():
    _, problems = parse_event(event(inferences=["Hostile intent likely."]))
    assert any("unsupported claim" in p for p in problems)
    parsed, problems = parse_event(event(unknowns=["Whether anyone nearby has hostile intent cannot be known."]))
    assert parsed is not None, problems


def test_confidence_requires_calibration(later):
    _, problems = parse_event(event(confidence=0.9))
    assert any("calibrated detector" in p for p in problems)
    engine = SafetyPolicyEngine(None, load_contracts(), simulation=True)
    decision = engine.evaluate(ev(confidence=0.9, calibrated=True), later(1), {"obs-1"})
    assert decision.outcome == REJECTED and "without calibration evidence" in decision.reasons[0]


def test_unsupported_category_and_missing_sources():
    assert parse_event(event(category="intruder"))[0] is None
    _, problems = parse_event(event(observations=()))
    assert any("must cite the observations" in p for p in problems)
    parsed, _ = parse_event(event(detector="help-request-command", category="explicit_help_request",
                                  observations=(), observed_facts=["The user said 'Guardian, emergency help.'"]))
    assert parsed is not None


def test_expiry_duplicates_and_escalation(later):
    engine = SafetyPolicyEngine(None, load_contracts(), simulation=True)
    assert engine.evaluate(ev(eid="e0", ttl=5), later(10), {"obs-1"}).outcome == EXPIRED
    first = engine.evaluate(ev(eid="e1"), later(1), {"obs-1"})
    assert first.outcome == ALERT
    assert engine.evaluate(ev(eid="e2", at=2), later(3), {"obs-1"}).outcome == SUPPRESSED_DUPLICATE
    escalated = engine.evaluate(ev(eid="e3", at=4, priority="CRITICAL"), later(5), {"obs-1"})
    assert escalated.outcome == ESCALATE
    # Once the earlier alert expires, the same hazard may alert again.
    assert engine.evaluate(ev(eid="e4", at=200), later(201), {"obs-1"}).outcome == ALERT


def test_actions_are_proposed_only_with_consent(config_data, later):
    help_event = dict(detector="help-request-command", category="explicit_help_request", observations=(),
                      observed_facts=["The user asked for help."], priority="CRITICAL")
    engine = SafetyPolicyEngine(TrustedConfig(copy.deepcopy(config_data)), load_contracts(), simulation=True)
    decision = engine.evaluate(ev(**help_event), later(1))
    assert decision.proposed_actions == ["notify-primary-on-help"]

    revoked = copy.deepcopy(config_data)
    revoked["consent"]["revoked"] = True
    engine = SafetyPolicyEngine(TrustedConfig(revoked), load_contracts(), simulation=True)
    decision = engine.evaluate(ev(**help_event), later(1))
    assert decision.proposed_actions == []
    assert any("consent expired or revoked" in r for r in decision.reasons)
