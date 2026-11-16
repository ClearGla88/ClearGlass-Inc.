import copy

from cg_testlib import validated_contract
from clearguard_core import DESIGN_MODE_NOTICE
from clearguard_core.capability import load_registry
from clearguard_core.config import TrustedConfig
from clearguard_core.contracts import load_contracts
from clearguard_core.health import (
    READY,
    UNAVAILABLE,
    UNCONFIGURED,
    UNSUPPORTED_HAZARDS,
    HostIntegrations,
    activate,
    assess,
    stale_inputs,
)


def test_design_build_without_config(now):
    r = assess(None, "missing", load_contracts(), load_registry(), HostIntegrations(), now)
    assert r.lifecycle == UNCONFIGURED
    assert r.coverage == "NONE" and r.routing == "FAILED" and r.integrity == "UNVERIFIED"
    assert any("trusted configuration not loaded (missing)" in f for f in r.failures)
    ok, message = activate(r, HostIntegrations())
    assert not ok and DESIGN_MODE_NOTICE in message


def test_design_build_with_config_is_still_unavailable(trusted, now):
    r = assess(trusted, "verified", load_contracts(), load_registry(), HostIntegrations(), now)
    assert r.lifecycle == UNAVAILABLE
    assert r.integrity == "VERIFIED_AS_CONFIGURED"
    assert "no emergency interface in this build" in r.emergency_authorization
    # Only detectors in the configured scope are assessed: no camera is configured.
    assert "camera-obstacle" not in {d.detector_id for d in r.detectors}
    assert "platform-fall-detection" in {d.detector_id for d in r.detectors}
    assert set(UNSUPPORTED_HAZARDS) == set(r.unsupported_hazards)


def test_invalid_signature_is_a_suspected_integrity_failure(now):
    r = assess(None, "invalid", load_contracts(), load_registry(), HostIntegrations(), now)
    assert r.integrity == "SUSPECTED_FAILURE"


def test_placeholders_and_consent_are_readiness_failures(config_data, now, later):
    data = copy.deepcopy(config_data)
    data["approved_by"] = "[CONFIRM]"
    r = assess(TrustedConfig(data), "verified", load_contracts(), load_registry(), HostIntegrations(), later(90000))
    assert any("unresolved value(s): approved_by" in f for f in r.failures)
    assert any("consent is expired" in f for f in r.failures)


def test_a_fully_evidenced_live_host_can_activate(trusted, now):
    contracts = {cid: validated_contract(c) for cid, c in load_contracts().items()}
    host = HostIntegrations(
        live=True, sensors={"platform_fall_detection": "granted"}, emergency_interface=True, connectivity="ONLINE",
        outputs={"headphones": True, "watch_haptic": True, "phone_notification": True},
    )
    r = assess(trusted, "verified", contracts, load_registry(), host, now)
    assert r.failures == [], r.failures
    assert r.lifecycle == READY and r.coverage == "FULL_FOR_CONFIGURED_SCOPE" and r.routing == "AVAILABLE"
    ok, message = activate(r, host)
    assert ok and "configured, validated scope only" in message


def test_partial_coverage_and_degraded_routing(trusted, now):
    contracts = {cid: validated_contract(c) for cid, c in load_contracts().items()}
    host = HostIntegrations(live=True, sensors={"platform_fall_detection": "revoked"}, emergency_interface=True,
                            outputs={"headphones": False, "watch_haptic": True, "phone_notification": True})
    r = assess(trusted, "verified", contracts, load_registry(), host, now)
    assert r.coverage == "PARTIAL" and r.routing == "DEGRADED"
    assert any("input platform_fall_detection: revoked" in f for f in r.failures)
    assert not activate(r, host)[0]


def test_silence_is_not_evidence_of_safety(now, later):
    limits = {"camera": 2.0, "fall": 30.0}
    assert stale_inputs({}, limits, now) == ["camera", "fall"]
    assert stale_inputs({"camera": now, "fall": now}, limits, later(5)) == ["camera"]
