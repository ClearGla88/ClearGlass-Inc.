import pytest
from cg_testlib import observation as raw_obs
from clearguard_core.observation import (
    ACCEPTED,
    ACCEPTED_DEGRADED,
    QUARANTINED,
    REJECTED,
    ObservationGate,
    compare,
    independent,
    independent_count,
    parse,
)


def admit(gate, raw, now):
    return gate.admit(raw, now)


def test_good_observation_is_accepted(now, later):
    result = ObservationGate().admit(raw_obs(), later(1))
    assert result.status == ACCEPTED and result.usable


@pytest.mark.parametrize("raw, expected", [
    ({k: v for k, v in raw_obs().items() if k != "lineage"}, "missing lineage"),
    (dict(raw_obs(), color="red"), "unknown field color"),
    (dict(raw_obs(), measurement="fell"), "measurement must be"),
    (dict(raw_obs(), event_time="2026-11-16T15:00:00"), "no UTC offset"),
    (dict(raw_obs(), freshness_limit_s=0), "greater than 0"),
    ("not an object", "must be an object"),
])
def test_malformed_is_rejected(raw, expected, later):
    result = ObservationGate().admit(raw, later(1))
    assert result.status == REJECTED
    assert any(expected in r for r in result.reasons), result.reasons


def test_duplicate_and_replay(later):
    gate = ObservationGate()
    assert gate.admit(raw_obs("o1"), later(1)).usable
    assert gate.admit(raw_obs("o1"), later(1)).status == REJECTED
    conflict = gate.admit(raw_obs("o1", measurement=False), later(2))
    assert conflict.status == QUARANTINED and "replay conflict" in conflict.reasons[0]


def test_stale_future_and_out_of_order(later):
    gate = ObservationGate()
    stale = gate.admit(raw_obs("old", at=-60, received=-59.8), later(0))
    assert stale.status == REJECTED and "stale" in stale.reasons[0]
    future = gate.admit(raw_obs("fut", at=10, received=1), later(1))
    assert future.status == QUARANTINED and "event time is after receipt" in future.reasons[0]
    ahead = gate.admit(raw_obs("ahead", at=9, received=9.2), later(1))
    assert ahead.status == QUARANTINED and "receipt time is in the future" in ahead.reasons[0]
    assert gate.admit(raw_obs("o5", at=5, received=5.2), later(6)).usable
    late = gate.admit(raw_obs("o3", at=3, received=3.2), later(6))
    assert late.status == QUARANTINED and "out of order" in late.reasons[0]


def test_implausible_jump_needs_a_contract_rate(later):
    source = "phone-1.accelerometer"

    def sample(oid, at, value):
        return raw_obs(oid, at=at, source_id=source, measurement=value, units="m/s2",
                       measurement_uncertainty=0.1, lineage=[])

    unchecked = ObservationGate()
    assert unchecked.admit(sample("a", 0, 1.0), later(1)).usable
    assert unchecked.admit(sample("b", 1, 900.0), later(2)).usable
    checked = ObservationGate(max_rates={(source, "m/s2"): 100.0})
    assert checked.admit(sample("a", 0, 1.0), later(1)).usable
    jump = checked.admit(sample("b", 1, 900.0), later(2))
    assert jump.status == QUARANTINED and "implausible jump" in jump.reasons[0]


@pytest.mark.parametrize("override, status, reason", [
    ({"permission_state": "revoked"}, REJECTED, "permission revoked"),
    ({"sensor_health": "failed"}, REJECTED, "failed health"),
    ({"integrity_status": "failed"}, QUARANTINED, "integrity check failed"),
    ({"sensor_health": "degraded"}, ACCEPTED_DEGRADED, "degraded"),
    ({"integrity_status": "unverified"}, ACCEPTED_DEGRADED, "not verified"),
])
def test_health_permission_and_integrity(override, status, reason, later):
    result = ObservationGate().admit(raw_obs(**override), later(1))
    assert result.status == status
    assert any(reason in r for r in result.reasons)


def test_shared_upstream_is_not_independent():
    a, _ = parse(raw_obs("a", source_id="svc-1", lineage=["imu-1"]))
    b, _ = parse(raw_obs("b", source_id="svc-2", lineage=["imu-1"]))
    c, _ = parse(raw_obs("c", source_id="svc-3", lineage=["cam-1"]))
    assert not independent(a, b)
    assert independent(a, c)
    assert independent_count([a, b, c]) == 2


def test_disagreement_is_preserved_not_averaged():
    a, _ = parse(raw_obs("a", measurement=1.0, units="m", measurement_uncertainty=0.1))
    b, _ = parse(raw_obs("b", measurement=1.15, units="m", measurement_uncertainty=0.1))
    c, _ = parse(raw_obs("c", measurement=3.0, units="m", measurement_uncertainty=0.1))
    assert compare([a, b]).agree
    result = compare([a, b, c])
    assert not result.agree and "disagree" in result.note
    assert ("c", 3.0) in result.values
