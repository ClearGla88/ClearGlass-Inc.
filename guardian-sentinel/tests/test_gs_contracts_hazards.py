import pytest

from guardian_core.alerts import TEMPLATES
from guardian_core.contracts import from_dict, missing
from guardian_core.errors import HazardError
from guardian_core.hazards import make_event
from gs_testlib import CONTRACT, NOW, contract, fall_event


def test_complete_contract_has_no_gaps():
    assert missing(contract(), set(TEMPLATES)) == []


def test_empty_contract_lists_every_requirement_and_supplies_no_defaults():
    gaps = missing(from_dict({}))
    for name in ("hazard", "max_event_age_s", "timing_budget_ms", "false_alert_criterion",
                 "missed_event_criterion", "test_evidence", "reviewer", "owner"):
        assert name in gaps


def test_contract_checks_template_and_independent_review():
    assert "alert_template_id (not an approved template)" in missing(
        contract(alert_template_id="custom_text"), set(TEMPLATES))
    assert "reviewer (must differ from owner)" in missing(contract(reviewer="detector owner"))


def test_contract_rejects_unknown_fields_and_hazards():
    with pytest.raises(HazardError):
        from_dict(dict(CONTRACT, guarantee="99.99%"))
    with pytest.raises(HazardError, match="unsupported hazard"):
        from_dict(dict(CONTRACT, hazard="hostile_person"))


@pytest.mark.parametrize("hazard", ["hostile_intent", "being_followed", "concealed_weapon", "radiation"])
def test_unsupported_hazard_categories_cannot_be_created(hazard):
    with pytest.raises(HazardError, match="unsupported hazard"):
        make_event(event_id="e", hazard=hazard, priority="CRITICAL", detector_id="d", created_at=NOW,
                   max_age_s=10, observation_ids=("o",), observed_facts=("x",), contract=contract())


def test_detector_events_need_contract_facts_and_observations():
    base = dict(event_id="e", hazard="fall", priority="WARNING", detector_id="fall-v0",
                created_at=NOW, max_age_s=120, observation_ids=("o",), observed_facts=("x",))
    with pytest.raises(HazardError, match="safety contract"):
        make_event(**base)
    with pytest.raises(HazardError, match="observed fact"):
        make_event(**dict(base, observed_facts=()), contract=contract())
    with pytest.raises(HazardError, match="observation ids"):
        make_event(**dict(base, observation_ids=()), contract=contract())
    with pytest.raises(HazardError, match="different hazard"):
        make_event(**dict(base, hazard="obstacle"), contract=contract())


def test_confidence_only_from_a_calibrated_detector():
    with pytest.raises(HazardError, match="calibrated"):
        fall_event(confidence=0.9)
    event = make_event(event_id="e", hazard="fall", priority="WARNING", detector_id="fall-v0",
                       created_at=NOW, max_age_s=120, observation_ids=("o",), observed_facts=("x",),
                       contract=contract(confidence_calibrated=True), confidence=0.9)
    assert event.confidence == 0.9


def test_event_expiry_comes_from_the_contract_age():
    event = fall_event()
    assert event.expires_at == NOW + 120
    assert not event.expired(NOW + 119) and event.expired(NOW + 120)
