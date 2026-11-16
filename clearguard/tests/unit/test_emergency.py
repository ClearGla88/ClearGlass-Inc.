import copy

from clearguard_core.config import TrustedConfig
from clearguard_core.emergency import (
    AUTHORIZED,
    BLOCKED,
    CANCELLED,
    CHECK_IN,
    COUNTDOWN,
    DELIVERED,
    FAILED,
    NATIVE_HINT,
    REQUESTED,
    SENT,
    EmergencyWorkflow,
    PlatformResult,
)

FACTS = {"help_request": True, "event_category": "explicit_help_request"}


class FakePlatform:
    available = True

    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def execute(self, record, contact, payload):
        self.calls.append((record.action_id, contact["contact_id"], payload))
        return self.results.pop(0) if len(self.results) > 1 else self.results[0]


def config(data, **action_changes):
    data = copy.deepcopy(data)
    data["actions"][0].update(action_changes)
    return TrustedConfig(data)


def test_without_config_or_consent_nothing_is_sent(config_data, now):
    result = EmergencyWorkflow(None).request("explicit_help_request", "i1", now)
    assert result.records == [] and NATIVE_HINT in result.messages
    revoked = copy.deepcopy(config_data)
    revoked["consent"]["revoked"] = True
    result = EmergencyWorkflow(TrustedConfig(revoked)).request("explicit_help_request", "i1", now)
    assert result.records == [] and "Consent is expired or revoked" in result.messages[0]


def test_confirmation_countdown_and_cancel(config_data, now, later):
    platform = FakePlatform(PlatformResult(DELIVERED, "ok", confirmed=True))
    wf = EmergencyWorkflow(config(config_data), platform)
    [record] = wf.request("explicit_help_request", "i1", now, FACTS).records
    assert record.state == REQUESTED and record.workflow == CHECK_IN
    wf.confirm("i1", later(1))
    assert record.state == AUTHORIZED and record.workflow == COUNTDOWN
    assert wf.cancel(later(2)) == ["notify-primary-on-help cancelled before anything was sent."]
    assert record.state == CANCELLED
    wf.tick(later(20))
    assert platform.calls == []


def test_repeated_request_is_not_sent_twice(config_data, now, later):
    platform = FakePlatform(PlatformResult(DELIVERED, "ok", confirmed=True))
    wf = EmergencyWorkflow(config(config_data, requires_confirmation_at_execution=False, countdown_s=0), platform)
    first = wf.request("explicit_help_request", "i1", now, FACTS)
    second = wf.request("explicit_help_request", "i1", later(1), FACTS)
    assert first.records[0] is second.records[0]
    assert "not repeated" in second.messages[0]
    assert len(platform.calls) == 1
    assert first.records[0].state == DELIVERED


def test_only_disclosed_fields_are_shared(config_data, now):
    platform = FakePlatform(PlatformResult(DELIVERED, "ok", confirmed=True))
    wf = EmergencyWorkflow(config(config_data, requires_confirmation_at_execution=False, countdown_s=0), platform)
    [record] = wf.request("explicit_help_request", "i1", now, dict(FACTS, precise_location="hidden")).records
    assert platform.calls[0][2] == {"help_request": True}
    assert record.withheld == ["event_time"]


def test_unconfirmed_delivery_is_reported_as_sent(config_data, now):
    platform = FakePlatform(PlatformResult(DELIVERED, "platform said so", confirmed=False))
    wf = EmergencyWorkflow(config(config_data, requires_confirmation_at_execution=False, countdown_s=0), platform)
    [record] = wf.request("explicit_help_request", "i1", now, FACTS).records
    assert record.state == SENT and "delivery not confirmed" in record.describe()
    assert wf.cancel(now) == ["notify-primary-on-help was already attempted; it cannot be recalled."]


def test_unavailable_platform_fails_at_once_with_native_hint(config_data, now):
    wf = EmergencyWorkflow(config(config_data, requires_confirmation_at_execution=False, countdown_s=0))
    result = wf.request("explicit_help_request", "i1", now, FACTS)
    record = result.records[0]
    assert record.state == FAILED and record.attempts == 1
    assert any("Emergency action unavailable" in m and NATIVE_HINT in m for m in result.messages)


def test_retries_are_bounded(config_data, now):
    platform = FakePlatform(PlatformResult(FAILED, "network"))
    wf = EmergencyWorkflow(config(config_data, requires_confirmation_at_execution=False, countdown_s=0), platform)
    [record] = wf.request("explicit_help_request", "i1", now, FACTS).records
    assert record.state == FAILED and record.attempts == 3 and len(platform.calls) == 3


def test_real_emergency_services_are_never_contacted_in_design_use(config_data, now):
    platform = FakePlatform(PlatformResult(DELIVERED, "ok", confirmed=True))
    wf = EmergencyWorkflow(config(config_data, recipient="ems", requires_confirmation_at_execution=False,
                                  countdown_s=0), platform)
    [record] = wf.request("explicit_help_request", "i1", now, FACTS).records
    assert record.state == BLOCKED and platform.calls == []


def test_action_expires_if_never_confirmed(config_data, now, later):
    wf = EmergencyWorkflow(config(config_data, expires_after_s=60))
    [record] = wf.request("explicit_help_request", "i1", now, FACTS).records
    messages = wf.tick(later(61))
    assert record.state == FAILED and "expired before it was attempted" in messages[0]


def test_non_cancellable_action_says_so(config_data, now):
    wf = EmergencyWorkflow(config(config_data, cancellable=False))
    wf.request("explicit_help_request", "i1", now, FACTS)
    assert wf.cancel(now) == ["notify-primary-on-help is not cancellable under the approved policy."]
