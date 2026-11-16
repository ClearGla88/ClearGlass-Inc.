from guardian_core import DESIGN_MODE_STATEMENT, NO_HAZARD_STATEMENT, STARTUP_LINE
from guardian_core.config import validate
from guardian_core.guardian import Guardian
from guardian_core.health import AdapterStatus, HealthSupervisor
from guardian_core.states import Coverage, Integrity, Lifecycle, Routing
from gs_testlib import NOW, FakeChannel, FakeDispatcher, config_dict, fall_event, observation


def adapter(name="watch-accel"):
    return AdapterStatus(name, "accelerometer", freshness_s=5.0, permission="granted", healthy=True)


def live_guardian(**kw):
    kw.setdefault("config", validate(config_dict()))
    kw.setdefault("adapters", [adapter()])
    kw.setdefault("channels", [FakeChannel()])
    return Guardian(**kw)


def monitoring_guardian(**kw):
    g = live_guardian(**kw)
    g.ingest(observation(), NOW)
    assert g.self_test(NOW) == []
    assert g.activate(NOW) == []
    return g


def test_design_mode_startup_says_so_and_never_claims_monitoring():
    report = Guardian().startup_report(NOW)
    assert report.splitlines()[0] == STARTUP_LINE
    assert DESIGN_MODE_STATEMENT in report
    assert "Active permissions: none." in report
    assert "no alert channel has passed its delivery test" in report


def test_design_mode_status_and_activation_are_refused():
    g = Guardian()
    reply = g.command("Guardian, status.", NOW)
    assert DESIGN_MODE_STATEMENT in reply.text and "Not monitoring." in reply.text
    assert NO_HAZARD_STATEMENT not in reply.text
    failures = g.activate(NOW)
    assert failures[0].startswith("lifecycle is UNCONFIGURED") and g.health.lifecycle is Lifecycle.UNCONFIGURED


def test_coverage_depends_on_fresh_permitted_input():
    sup = HealthSupervisor([adapter("a"), adapter("b")], [FakeChannel()])
    assert sup.coverage(NOW, configured=False) is Coverage.UNKNOWN
    assert sup.coverage(NOW, configured=True) is Coverage.NONE  # silence is not coverage
    sup.adapters["a"].last_observation_at = NOW - 1
    assert sup.coverage(NOW, configured=True) is Coverage.PARTIAL
    sup.adapters["b"].last_observation_at = NOW - 1
    assert sup.coverage(NOW, configured=True) is Coverage.FULL_FOR_CONFIGURED_SCOPE
    sup.adapters["b"].permission = "revoked"
    assert sup.coverage(NOW, configured=True) is Coverage.PARTIAL
    assert sup.coverage(NOW + 60, configured=True) is Coverage.NONE


def test_routing_reflects_tested_channels_only():
    assert HealthSupervisor([], []).routing() is Routing.FAILED
    assert HealthSupervisor([], [FakeChannel(verified=None)]).routing() is Routing.UNKNOWN
    assert HealthSupervisor([], [FakeChannel(), FakeChannel(verified=False)]).routing() is Routing.DEGRADED
    assert HealthSupervisor([], [FakeChannel()]).routing() is Routing.AVAILABLE


def test_full_activation_path_and_no_hazard_wording():
    g = monitoring_guardian()
    assert g.health.lifecycle is Lifecycle.MONITORING
    status = g.command("guardian status", NOW).text
    assert NO_HAZARD_STATEMENT in status and DESIGN_MODE_STATEMENT not in status
    assert "safe" not in status.lower().replace(NO_HAZARD_STATEMENT.lower(), "")


def test_monitoring_lapses_when_input_goes_stale():
    g = monitoring_guardian()
    status = g.command("Guardian, status", NOW + 60).text
    assert "No sensor input is covering the configured scope." in status
    assert NO_HAZARD_STATEMENT not in status


def test_pause_and_resume_are_confirmed_only_when_they_happen():
    g = monitoring_guardian()
    assert g.command("Guardian, pause.", NOW).confirmed
    assert g.health.lifecycle is Lifecycle.PAUSED
    assert not g.command("Guardian, pause.", NOW).confirmed
    reply = g.command("Guardian, resume.", NOW + 60)  # input now stale
    assert not reply.confirmed and "no sensor adapter" in reply.text
    g.ingest(observation(observation_id="o-2", event_ts=NOW + 59, receipt_ts=NOW + 59.5), NOW + 60)
    assert g.command("Guardian, resume.", NOW + 60).confirmed


def test_why_and_repeat_cite_the_recorded_event():
    g = monitoring_guardian()
    g.raise_hazard(fall_event(), "possible_fall", NOW)
    why = g.command("Guardian, why did you alert?", NOW + 1).text
    assert "fall-v0" in why and "event fall-1" in why and "o-1" in why
    assert g.command("Guardian, repeat the last alert.", NOW + 1).text == "Possible fall detected. Do you need help?"
    assert g.command("Guardian, repeat the last alert.", NOW + 500).text.startswith("Earlier alert")


def test_emergency_help_in_design_mode_points_to_native_controls():
    reply = Guardian().command("Guardian, emergency help", NOW)
    assert not reply.confirmed and "phone's emergency call" in reply.text


def test_emergency_help_with_dispatcher_starts_a_cancellable_countdown():
    d = FakeDispatcher(["sent", "sent"])
    g = monitoring_guardian(dispatcher=d)
    reply = g.command("Guardian, emergency help", NOW)
    assert reply.confirmed and "cancel escalation" in reply.text
    cancel = g.command("Guardian, cancel escalation", NOW + 5)
    assert cancel.confirmed and "notify_partner_help" in cancel.text
    g.emergency.tick(NOW + 60)
    assert d.calls == []
    assert not g.command("Guardian, cancel escalation", NOW + 61).confirmed


def test_stop_sharing_reports_what_cannot_be_recalled():
    d = FakeDispatcher(["sent", "sent"])
    g = monitoring_guardian(dispatcher=d)
    assert g.command("Guardian, stop sharing", NOW).text == "No location sharing is active."
    g.command("Guardian, emergency help", NOW)
    g.emergency.tick(NOW + 30)
    reply = g.command("Guardian, stop sharing", NOW + 31)
    assert not reply.confirmed and "cannot be recalled: share_location_help" in reply.text


def test_integrity_fault_isolates_external_actions_but_keeps_local_alerts():
    d = FakeDispatcher(["sent"])
    g = monitoring_guardian(dispatcher=d)
    g.report_integrity_fault("config store", "file changed outside the app", NOW)
    assert g.health.integrity is Integrity.SUSPECTED_FAILURE
    alert = g.raise_hazard(fall_event(), "possible_fall", NOW)
    assert alert.state.value == "ACCEPTED_BY_PLATFORM"
    reply = g.command("Guardian, emergency help", NOW)
    assert not reply.confirmed and "external actions blocked" in reply.text
    assert d.calls == []


def test_delete_states_its_limits_and_unknown_commands_are_refused():
    g = monitoring_guardian()
    g.raise_hazard(fall_event(), "possible_fall", NOW)
    reply = g.command("Guardian, delete recent data", NOW)
    assert reply.confirmed and "not affected" in reply.text and g.alerts.alerts == []
    assert not g.command("Guardian, unlock the door", NOW).confirmed
    assert not g.command("status", NOW).confirmed


def test_what_is_unavailable_lists_inactive_and_unsupported():
    text = Guardian().command("Guardian, what is unavailable?", NOW).text
    assert "headphone_output" in text and "concealed weapons" in text and "Readiness failure" in text
    g = Guardian()
    g.command("Guardian, status", NOW)
    g.audit.verify()
