"""Synthetic builders for tests: a complete configuration with no placeholders,
observations, events, and a contract with every validation field filled in."""

from __future__ import annotations

import copy
import os
from datetime import datetime, timedelta, timezone

PKG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOW = datetime(2026, 11, 16, 15, 0, 0, tzinfo=timezone.utc)


def t(seconds: float = 0) -> str:
    return (NOW + timedelta(seconds=seconds)).isoformat()


def base_config() -> dict:
    return {
        "schema": "clearguard.config/1",
        "policy_version": "test-1",
        "approved_at": t(-3600),
        "approved_by": "test owner",
        "principal_address": "SIR",
        "mode": "design",
        "devices": [
            {"device_id": "phone-1", "kind": "phone"},
            {"device_id": "watch-1", "kind": "watch"},
        ],
        "sensor_scopes": [
            {"device_id": "watch-1", "sensor": "platform_fall_detection", "purpose": "relay platform fall events"},
        ],
        "allowed_services": [],
        "contacts": [
            {"contact_id": "primary", "label": "Primary contact", "channel": "sms", "is_emergency_service": False},
            {"contact_id": "ems", "label": "Emergency services", "channel": "platform_emergency",
             "is_emergency_service": True},
        ],
        "actions": [
            {
                "action_id": "notify-primary-on-help", "trigger": "explicit_help_request", "recipient": "primary",
                "disclose": ["help_request", "event_time"], "countdown_s": 10, "cancellable": True,
                "max_retries": 2, "expires_after_s": 900, "requires_confirmation_at_execution": True,
            },
        ],
        "shared_fields_allowed": ["help_request", "event_time", "event_category", "coarse_location"],
        "consent": {"granted_at": t(-3600), "expires_at": t(86400), "revoked": False},
        "alerting": {"channels": ["headphones", "watch_haptic", "phone_notification"], "max_volume_pct": 60,
                     "directional_audio": False},
        "retention": {"event_hours": 24, "raw_media": "none", "location_in_logs": False, "training_use": False},
    }


def observation(oid: str = "obs-1", *, at: float = 0, received: float | None = None, **overrides) -> dict:
    raw = {
        "source_id": "watch-1.platform_fall_detection",
        "observation_id": oid,
        "event_time": t(at),
        "receipt_time": t(at + 0.2 if received is None else received),
        "clock_uncertainty_s": 0.5,
        "measurement": True,
        "units": "flag",
        "measurement_uncertainty": 0,
        "sensor_health": "ok",
        "permission_state": "granted",
        "freshness_limit_s": 30,
        "integrity_status": "verified",
        "lineage": ["watch-1.accelerometer"],
    }
    raw.update(overrides)
    return raw


def event(eid: str = "evt-1", *, detector: str = "platform-fall-detection", category: str = "device_fall_event",
          priority: str = "WARNING", at: float = 0, ttl: float = 120, observations: tuple = ("obs-1",),
          **overrides) -> dict:
    raw = {
        "event_id": eid, "detector_id": detector, "category": category, "priority": priority,
        "created_at": t(at), "expires_at": t(at + ttl), "observation_ids": list(observations),
        "observed_facts": ["The watch platform reported a fall event."],
        "inferences": [], "unknowns": ["Whether the user is hurt."],
        "alternatives": ["The watch was dropped."], "limitations": ["Synthetic test input."],
    }
    raw.update(overrides)
    return raw


def validated_contract(base: dict) -> dict:
    """A copy of ``base`` with every review field filled, for tests of the
    validated path. These numbers are test fixtures, not proposed targets."""
    c = copy.deepcopy(base)
    c["implementation"] = "host_platform" if c["implementation"] == "not_implemented" else c["implementation"]
    c["quality_limits"] = c["quality_limits"] or {"fixture": "test"}
    c["operating_envelope"] = c["operating_envelope"] or {"fixture": "test"}
    for key in ("trigger_rule", "clearing_rule"):
        if str(c[key]).startswith("["):
            c[key] = "test fixture rule"
    c["max_event_age_s"] = 60
    c["timing_budget_ms"] = 1000
    c["acceptance_criteria"] = {"missed_event_rate_max": 0.01, "false_alerts_per_hour_max": 0.1, "basis": "test fixture"}
    c["test_evidence"] = [{"kind": "controlled_exercise", "reference": "fixture", "sample_size": 10, "date": "2026-11-16"}]
    c["owner"] = "test owner"
    c["review"] = {"reviewer": "test reviewer", "date": "2026-11-16", "decision": "approved"}
    return c
