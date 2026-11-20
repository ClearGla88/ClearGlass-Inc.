from guardian_core.observation import ObservationGate, Verdict, compare, independent, independent_groups, parse_observation
from gs_testlib import NOW, observation


def gate():
    return ObservationGate({("acceleration", "m/s2"): 50.0})


def test_good_observation_is_accepted():
    a = gate().admit(observation(), NOW)
    assert a.verdict is Verdict.ACCEPT and a.flags == ()


def test_malformed_observations_are_rejected():
    for raw in ({}, observation(value="9.8"), observation(value=float("nan")), observation(lineage=[]),
                observation(sensor_health="fine"), observation(extra=1), observation(uncertainty=-1)):
        assert gate().admit(raw, NOW).verdict is Verdict.REJECT


def test_unauthorized_failed_or_stale_input_is_rejected():
    assert gate().admit(observation(permission="revoked"), NOW).reasons == ("permission_revoked",)
    assert gate().admit(observation(integrity="failed"), NOW).reasons == ("integrity_failed",)
    assert gate().admit(observation(sensor_health="failed"), NOW).reasons == ("sensor_failed",)
    stale = observation(event_ts=NOW - 30, receipt_ts=NOW - 29)
    assert gate().admit(stale, NOW).reasons == ("stale",)


def test_duplicates_and_replays_are_rejected():
    g = gate()
    assert g.admit(observation(), NOW).verdict is Verdict.ACCEPT
    assert g.admit(observation(), NOW).reasons == ("duplicate_or_replay",)


def test_out_of_order_clock_and_jump_problems_are_quarantined():
    g = gate()
    g.admit(observation(observation_id="a", event_ts=NOW - 1), NOW)
    late = g.admit(observation(observation_id="b", event_ts=NOW - 2), NOW)
    assert late.verdict is Verdict.QUARANTINE and "out_of_order" in late.reasons
    future = g.admit(observation(observation_id="c", event_ts=NOW + 10, receipt_ts=NOW), NOW)
    assert "clock_discontinuity" in future.reasons
    jump = g.admit(observation(observation_id="d", event_ts=NOW - 0.9, value=500.0), NOW)
    assert jump.verdict is Verdict.QUARANTINE and "implausible_jump" in jump.reasons
    assert len(g.quarantine) == 3


def test_no_invented_rate_limit_for_unknown_kinds():
    g = ObservationGate()
    g.admit(observation(observation_id="a", event_ts=NOW - 1), NOW)
    assert g.admit(observation(observation_id="b", event_ts=NOW - 0.5, value=1e6), NOW).verdict is Verdict.ACCEPT


def test_degraded_and_unverified_input_is_flagged_not_hidden():
    a = gate().admit(observation(sensor_health="degraded", integrity="unverified"), NOW)
    assert a.verdict is Verdict.ACCEPT
    assert set(a.flags) == {"sensor_degraded", "integrity_unverified"}


def test_shared_upstream_is_not_independent_evidence():
    a = parse_observation(observation(source_id="svc-a", lineage=["phone-1/gps"]))
    b = parse_observation(observation(source_id="svc-b", lineage=["phone-1/gps", "map-api"]))
    c = parse_observation(observation(source_id="svc-c", lineage=["watch-1/gps"]))
    assert not independent(a, b)
    assert independent(a, c)
    assert independent_groups([a, b, c]) == 2


def test_disagreement_is_preserved_not_averaged():
    a = parse_observation(observation(source_id="s1", value=1.0, uncertainty=0.1))
    b = parse_observation(observation(source_id="s2", value=5.0, uncertainty=0.1))
    result = compare([a, b])
    assert result["agreement"] is False and result["reason"] == "material disagreement"
    assert [v[1] for v in result["values"]] == [1.0, 5.0]
