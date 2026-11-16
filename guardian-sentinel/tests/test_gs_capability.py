import pytest

from guardian_core.capability import CapabilityRegistry, Evidence, default_registry
from guardian_core.contracts import missing
from guardian_core.errors import EvidenceError
from guardian_core.states import CapabilityState as C
from gs_testlib import contract


def _to_verified(reg, name):
    reg.promote(name, C.SPECIFIED, Evidence("requirement", "SPEC.md"))
    reg.promote(name, C.IMPLEMENTED, Evidence("code", "x.py"))
    reg.promote(name, C.VERIFIED, Evidence("test", "test_x.py"))


def test_promotion_is_one_step_with_the_matching_evidence():
    reg = CapabilityRegistry()
    reg.add("x")
    with pytest.raises(EvidenceError):
        reg.promote("x", C.IMPLEMENTED, Evidence("code", "x.py"))  # skips SPECIFIED
    with pytest.raises(EvidenceError):
        reg.promote("x", C.SPECIFIED, Evidence("test", "t"))  # wrong evidence kind
    with pytest.raises(EvidenceError):
        reg.promote("x", C.SPECIFIED, Evidence("requirement", "  "))  # empty reference
    _to_verified(reg, "x")
    assert reg.get("x").state is C.VERIFIED


def test_detector_needs_a_complete_contract_to_be_validated():
    reg = CapabilityRegistry()
    reg.add("fall", is_detector=True)
    _to_verified(reg, "fall")
    report = Evidence("validation_report", "VR-1")
    with pytest.raises(EvidenceError):
        reg.promote("fall", C.VALIDATED, report)
    with pytest.raises(EvidenceError, match="incomplete"):
        reg.promote("fall", C.VALIDATED, report, contract_missing=missing(contract(test_evidence=[])))
    reg.promote("fall", C.VALIDATED, report, contract_missing=missing(contract()))
    assert reg.get("fall").state is C.VALIDATED


def test_demotion_needs_a_reason_and_must_lower_the_state():
    reg = CapabilityRegistry()
    reg.add("x")
    _to_verified(reg, "x")
    with pytest.raises(EvidenceError):
        reg.demote("x", C.VERIFIED, "same")
    with pytest.raises(EvidenceError):
        reg.demote("x", C.IMPLEMENTED, " ")
    reg.demote("x", C.IMPLEMENTED, "test removed")
    assert reg.get("x").state is C.IMPLEMENTED


def test_default_registry_claims_nothing_validated_or_active():
    reg = default_registry()
    assert reg.at_least(C.VALIDATED) == []
    for name in ("sensor_adapters", "headphone_output", "emergency_dispatch", "fall_detector"):
        assert reg.get(name).state is C.SPECIFIED


def test_default_registry_test_references_exist():
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    reg = default_registry()
    for name in reg.at_least(C.VERIFIED):
        ref = reg.get(name).history[-1][1].reference
        assert os.path.isfile(os.path.join(root, ref)), ref
