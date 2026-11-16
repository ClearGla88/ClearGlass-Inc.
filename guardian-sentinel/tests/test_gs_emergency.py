import pytest

from guardian_core.config import validate
from guardian_core.emergency import EmergencyUnavailable, EmergencyWorkflow
from guardian_core.states import ActionOutcome as A, EmergencyState as E
from gs_testlib import NOW, FakeDispatcher, config_dict, fall_event, help_event


def wf(dispatcher=None, **cfg):
    return EmergencyWorkflow(validate(config_dict(**cfg)), dispatcher)


def test_no_config_or_unknown_action_is_disclosed_immediately():
    with pytest.raises(EmergencyUnavailable, match="no authenticated configuration"):
        EmergencyWorkflow(None, FakeDispatcher()).request("x", help_event(), NOW)
    with pytest.raises(EmergencyUnavailable, match="not in the approved action matrix"):
        wf(FakeDispatcher()).request("call_everyone", help_event(), NOW)


def test_no_dispatcher_fails_at_once_with_the_reason():
    inst = wf(None).request("notify_partner_help", help_event(), NOW)
    assert inst.outcome is A.FAILED and inst.reason == "emergency action unavailable on this device"


def test_trigger_consent_and_expiry_are_enforced():
    d = FakeDispatcher()
    assert wf(d).request("notify_partner_help", fall_event(), NOW).reason == "event does not meet the approved trigger"
    expired = wf(d, consent_expires_at="2026-12-01T00:00:00Z").request("notify_partner_help", help_event(), NOW)
    assert expired.reason == "consent has expired"
    stale = wf(d).request("notify_partner_help", help_event(created_at=NOW - 2000), NOW)
    assert stale.reason == "triggering event has expired"
    assert d.calls == []


def test_countdown_then_send_then_platform_confirmed_delivery():
    d = FakeDispatcher(["sent"])
    flow = wf(d)
    inst = flow.request("notify_partner_help", help_event(), NOW)
    assert inst.outcome is A.AUTHORIZED and flow.state is E.COUNTDOWN
    flow.tick(NOW + 29)
    assert d.calls == []
    flow.tick(NOW + 30)
    assert inst.outcome is A.SENT and flow.state is E.ATTEMPTING  # sent is not delivered
    flow.confirm_delivery(inst.instance_id, NOW + 35)
    assert inst.outcome is A.DELIVERED and flow.state is E.DELIVERED


def test_repeated_requests_never_duplicate_the_action():
    d = FakeDispatcher(["sent", "sent"])
    flow = wf(d)
    first = flow.request("notify_partner_help", help_event(), NOW)
    second = flow.request("notify_partner_help", help_event(), NOW + 1)
    assert first is second and len(flow.instances) == 1
    flow.tick(NOW + 31)
    flow.tick(NOW + 32)
    assert d.calls == ["notify_partner_help"]


def test_cancel_stops_only_what_has_not_been_attempted():
    d = FakeDispatcher(["sent"])
    flow = wf(d)
    help_ = help_event()
    flow.request("notify_partner_help", help_, NOW)
    flow.request("share_location_help", help_, NOW)
    cancelled, too_late = flow.cancel(NOW + 5)
    assert sorted(cancelled) == ["notify_partner_help", "share_location_help"] and too_late == []
    assert flow.state is E.CANCELLED
    flow.tick(NOW + 60)
    assert d.calls == []

    flow2 = wf(FakeDispatcher(["sent"]))
    inst = flow2.request("notify_partner_help", help_event("h2"), NOW)
    flow2.tick(NOW + 30)
    cancelled, too_late = flow2.cancel(NOW + 31)
    assert cancelled == [] and too_late == ["notify_partner_help"] and inst.outcome is A.SENT


def test_host_confirmation_is_required_when_configured():
    d = FakeDispatcher(["connected"])
    flow = wf(d)
    inst = flow.request("notify_partner_fall", fall_event(), NOW)
    assert inst.outcome is A.REQUESTED and inst.reason == "waiting for confirmation on the host"
    assert flow.state is E.CHECK_IN and d.calls == []
    flow.confirm(inst.instance_id, NOW + 2)
    assert inst.outcome is A.CONNECTED and flow.state is E.CONNECTED


def test_retries_are_bounded_by_the_configured_limit():
    d = FakeDispatcher(["failed", "failed", "sent"])
    flow = wf(d)
    inst = flow.request("notify_partner_help", help_event(), NOW)  # retry_limit 1
    flow.tick(NOW + 30)
    assert inst.outcome is A.AUTHORIZED and inst.reason == "attempt failed; retry pending"
    flow.tick(NOW + 31)
    assert inst.outcome is A.FAILED and inst.attempts == 2 and len(d.calls) == 2


def test_dispatcher_exceptions_count_as_failures():
    class Boom(FakeDispatcher):
        def dispatch(self, instance):
            raise OSError("radio off")
    flow = wf(Boom())
    inst = flow.request("notify_partner_fall", fall_event(), NOW, host_confirmed=True)
    assert inst.outcome is A.FAILED and inst.reason == "attempt failed; retry limit reached"


def test_authorization_expires_if_no_attempt_happens_in_time():
    flow = wf(FakeDispatcher())
    inst = flow.request("notify_partner_help", help_event(), NOW)
    inst.countdown_ends_at = NOW + 5000  # e.g. countdown held open by the host
    flow.tick(NOW + 901)
    assert inst.outcome is A.FAILED and inst.reason == "authorization expired before an attempt"


def test_integrity_fault_blocks_external_actions():
    flow = wf(FakeDispatcher())
    flow.external_actions_blocked = "config store: unexpected modification"
    inst = flow.request("notify_partner_help", help_event(), NOW)
    assert inst.outcome is A.FAILED and inst.reason.startswith("external actions blocked")


def test_check_in_cycle():
    flow = wf(FakeDispatcher())
    flow.start_check_in(NOW + 60)
    assert flow.state is E.CHECK_IN and not flow.check_in_overdue(NOW + 59)
    assert flow.check_in_overdue(NOW + 60)
    flow.check_in_answered()
    assert flow.state is E.IDLE
    flow.resolve()
    assert flow.state is E.RESOLVED
