"""Shared builders for the Guardian Sentinel tests (synthetic data only)."""

from __future__ import annotations

import copy

from guardian_core.alerts import Channel
from guardian_core.contracts import from_dict
from guardian_core.emergency import Dispatcher
from guardian_core.hazards import make_event

NOW = 1_800_000_000.0  # 2027-01-15T08:00:00Z
KEY = bytes(range(32))

BASE_CONFIG = {
    "policy_version": "test-1",
    "approved_at": "2026-11-01T00:00:00Z",
    "approved_by": "owner (test)",
    "enrolled_devices": [
        {"device_id": "phone-1", "kind": "phone"},
        {"device_id": "watch-1", "kind": "watch"},
    ],
    "sensor_scopes": [
        {"device_id": "phone-1", "sensor": "camera", "scope": "foreground_only"},
        {"device_id": "watch-1", "sensor": "accelerometer", "scope": "always_on_when_worn"},
    ],
    "external_services": ["official-alerts-feed"],
    "contacts": [{"contact_id": "partner", "channel": "sms", "recipient_ref": "host-contact-ref-1"}],
    "permitted_actions": [
        {"action_id": "notify_partner_help", "kind": "notify_contact",
         "trigger": {"hazard": "help_request", "min_priority": "CRITICAL"},
         "recipient": "partner", "data_fields": ["display_name", "hazard_kind", "event_time"],
         "countdown_s": 30, "retry_limit": 1, "requires_host_confirmation": False, "expires_after_s": 900},
        {"action_id": "notify_partner_fall", "kind": "notify_contact",
         "trigger": {"hazard": "fall", "min_priority": "WARNING"},
         "recipient": "partner", "data_fields": ["hazard_kind", "event_time"],
         "countdown_s": 0, "retry_limit": 0, "requires_host_confirmation": True, "expires_after_s": 600},
        {"action_id": "share_location_help", "kind": "share_location",
         "trigger": {"hazard": "help_request", "min_priority": "CRITICAL"},
         "recipient": "partner", "data_fields": ["approximate_location"],
         "countdown_s": 30, "retry_limit": 0, "requires_host_confirmation": False, "expires_after_s": 900},
    ],
    "shared_data_fields": ["display_name", "approximate_location", "hazard_kind", "event_time"],
    "consent_expires_at": "2027-12-31T00:00:00Z",
    "cancellation": {"method": "both", "recovery": "re-enroll from the app settings"},
}


def config_dict(**overrides) -> dict:
    cfg = copy.deepcopy(BASE_CONFIG)
    cfg.update(overrides)
    return cfg


def observation(**overrides) -> dict:
    raw = {
        "source_id": "watch-accel", "observation_id": "o-1", "kind": "acceleration",
        "value": 9.8, "unit": "m/s2", "uncertainty": 0.2, "event_ts": NOW - 1.0,
        "receipt_ts": NOW - 0.5, "clock_uncertainty_s": 0.1, "sensor_health": "ok",
        "permission": "granted", "freshness_s": 5.0, "integrity": "verified",
        "lineage": ["watch-1/imu"],
    }
    raw.update(overrides)
    return raw


CONTRACT = {
    "detector_id": "fall-v0", "hazard": "fall", "intended_use": "wrist-worn fall detection, walking",
    "required_inputs": ["watch accelerometer"], "quality_limits": {"sample_rate_hz": ">= 50"},
    "operating_conditions": ["worn on wrist", "walking or standing"],
    "known_failure_modes": ["watch removed", "vigorous exercise"],
    "trigger_rule": "reviewed rule R-1", "clearing_rule": "user response or 60 s of normal motion",
    "max_event_age_s": 120, "timing_budget_ms": 2000, "alert_template_id": "possible_fall",
    "false_alert_criterion": "from review FA-1", "missed_event_criterion": "from review ME-1",
    "degraded_behavior": "advisory that fall detection is unavailable",
    "test_evidence": ["report TE-1"], "owner": "detector owner", "reviewer": "independent reviewer",
    "confidence_calibrated": False,
}


def contract(**overrides):
    raw = copy.deepcopy(CONTRACT)
    raw.update(overrides)
    return from_dict(raw)


def fall_event(event_id="fall-1", priority="WARNING", created_at=NOW, **kw):
    return make_event(event_id=event_id, hazard="fall", priority=priority, detector_id="fall-v0",
                      created_at=created_at, max_age_s=120, observation_ids=("o-1",),
                      observed_facts=("acceleration spike then stillness",), contract=contract(), **kw)


def help_event(event_id="help-1", created_at=NOW, max_age_s=900):
    return make_event(event_id=event_id, hazard="help_request", priority="CRITICAL", detector_id="user",
                      created_at=created_at, max_age_s=max_age_s, observation_ids=(),
                      observed_facts=("user asked for help",))


class FakeChannel(Channel):
    def __init__(self, name="headphones", kind="headphones", verified=True, accept=True, boom=False):
        super().__init__(name, kind, verified)
        self.accept, self.boom, self.received = accept, boom, []

    def submit(self, alert):
        if self.boom:
            raise RuntimeError("channel crashed")
        self.received.append(alert.text)
        return self.accept


class FakeDispatcher(Dispatcher):
    def __init__(self, results=("sent",), available=True):
        self.available = available
        self.results = list(results)
        self.calls = []

    def dispatch(self, instance):
        self.calls.append(instance.action.action_id)
        return self.results.pop(0) if self.results else "failed"
