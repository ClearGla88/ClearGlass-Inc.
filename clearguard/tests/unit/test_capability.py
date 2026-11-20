import pytest
from cg_testlib import PKG_ROOT
from clearguard_core.capability import Capability, Evidence, Level, load_registry, registry_problems


def ev(kind, reviewer=None):
    return Evidence(kind, "ref", "2026-11-16", reviewer)


def test_promotion_is_one_state_at_a_time_with_matching_evidence():
    cap = Capability("x", "X")
    cap.promote(Level.SPECIFIED, ev("requirement"))
    with pytest.raises(ValueError, match="one at a time"):
        cap.promote(Level.VERIFIED, ev("test"))
    with pytest.raises(ValueError, match="'implementation' evidence"):
        cap.promote(Level.IMPLEMENTED, ev("test"))
    cap.promote(Level.IMPLEMENTED, ev("implementation"))
    cap.promote(Level.VERIFIED, ev("test"))
    assert cap.level == Level.VERIFIED


def test_validated_needs_a_named_reviewer_and_active_needs_live_health():
    cap = Capability("x", "X", Level.VERIFIED)
    with pytest.raises(ValueError, match="reviewer"):
        cap.promote(Level.VALIDATED, ev("validation"))
    cap.promote(Level.VALIDATED, ev("validation", reviewer="reviewer"))
    with pytest.raises(ValueError, match="live input"):
        cap.promote(Level.ACTIVE, ev("live_health", reviewer="host"))
    cap.promote(Level.ACTIVE, ev("live_health", reviewer="host"), live_health_ok=True)
    cap.demote(Level.VALIDATED)
    assert cap.level == Level.VALIDATED


def test_shipped_registry_is_consistent_and_claims_nothing_beyond_verified():
    caps = load_registry()
    assert registry_problems(caps, PKG_ROOT) == []
    assert max(c.level for c in caps) == Level.VERIFIED
    # Every hardware-facing capability is specified only.
    by_id = {c.cap_id: c for c in caps}
    for cid in ("headphone_output", "emergency_interface", "fall_detection_relay", "camera_obstacle_detection"):
        assert by_id[cid].level == Level.SPECIFIED


def test_registry_problems_catch_unsupported_claims(tmp_path):
    caps = [
        Capability("a", "A", Level.VERIFIED, [ev("requirement"), ev("implementation")]),
        Capability("b", "B", Level.ACTIVE, []),
        Capability("c", "C", Level.SPECIFIED, [Evidence("requirement", "missing/file.md", "2026-11-16")]),
    ]
    problems = registry_problems(caps, str(tmp_path))
    assert any("a: VERIFIED claimed without 'test'" in p for p in problems)
    assert any("b: ACTIVE is a runtime state" in p for p in problems)
    assert any("evidence file not found: missing/file.md" in p for p in problems)
