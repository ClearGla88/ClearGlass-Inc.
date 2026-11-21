import json

import pytest

from guardian_core.config import key_id, load_config, sign, validate, verify_envelope
from guardian_core.errors import ConfigError
from gs_testlib import KEY, NOW, config_dict


def test_valid_config_round_trips_through_signing():
    cfg = verify_envelope(sign(config_dict(), KEY), KEY)
    assert cfg.policy_version == "test-1"
    assert cfg.consent_valid(NOW)
    assert set(cfg.actions) == {"notify_partner_help", "notify_partner_fall", "share_location_help"}


def test_tampered_config_is_refused_even_if_valid():
    env = sign(config_dict(), KEY)
    env["config"]["permitted_actions"][0]["countdown_s"] = 0  # still schema-valid
    with pytest.raises(ConfigError, match="authentication failed"):
        verify_envelope(env, KEY)


def test_wrong_key_is_refused():
    env = sign(config_dict(), KEY)
    with pytest.raises(ConfigError, match="different key"):
        verify_envelope(env, bytes(32))
    env["kid"] = key_id(bytes(32))
    with pytest.raises(ConfigError):
        verify_envelope(env, bytes(32))


@pytest.mark.parametrize("mutate,message", [
    (lambda c: c.update(extra_permission=True), "unknown field"),
    (lambda c: c["permitted_actions"][0].update(also_call_police=True), "unknown field"),
    (lambda c: c.pop("consent_expires_at"), "missing field"),
    (lambda c: c.update(consent_expires_at="2026-10-01T00:00:00Z"), "after approved_at"),
    (lambda c: c.update(approved_at="2026-11-01T00:00:00"), "time zone"),
    (lambda c: c["permitted_actions"][0].update(recipient="stranger"), "not an approved contact"),
    (lambda c: c["permitted_actions"][0].update(data_fields=["battery_level"]), "outside shared_data_fields"),
    (lambda c: c["permitted_actions"][0]["trigger"].update(hazard="suspicious_person"), "unsupported hazard"),
    (lambda c: c["permitted_actions"][0].update(kind="call_emergency_interface"), "native_emergency_interface"),
    (lambda c: c["permitted_actions"][2].update(data_fields=[]), "approximate_location"),
    (lambda c: c["permitted_actions"][0].update(countdown_s=-1), "countdown_s"),
    (lambda c: c["permitted_actions"][0].update(retry_limit=True), "retry_limit"),
    (lambda c: c["sensor_scopes"][0].update(device_id="not-enrolled"), "not enrolled"),
    (lambda c: c["sensor_scopes"][0].update(sensor="thermal_camera"), "sensor must be one of"),
    (lambda c: c["permitted_actions"].append(dict(c["permitted_actions"][0])), "duplicates action_id"),
])
def test_schema_rejections(mutate, message):
    cfg = config_dict()
    mutate(cfg)
    with pytest.raises(ConfigError, match=message):
        validate(cfg)


def test_sign_refuses_an_invalid_config():
    with pytest.raises(ConfigError):
        sign(config_dict(extra=1), KEY)


def test_expired_consent_loads_but_reports_invalid():
    cfg = validate(config_dict(consent_expires_at="2026-12-01T00:00:00Z"))
    assert not cfg.consent_valid(NOW)


def test_load_config_from_file(tmp_path):
    path = tmp_path / "guardian.json"
    path.write_text(json.dumps(sign(config_dict(), KEY)))
    assert load_config(str(path), KEY).approved_by == "owner (test)"
    path.write_text("{not json")
    with pytest.raises(ConfigError, match="cannot read"):
        load_config(str(path), KEY)


def test_example_file_is_valid():
    import os
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, "guardian.example.json"), encoding="utf-8") as fh:
        validate(json.load(fh))
