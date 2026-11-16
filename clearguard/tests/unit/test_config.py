import copy
import json
import os

import pytest
from cg_testlib import PKG_ROOT
from clearguard_core import config as cfg
from clearguard_core.errors import ConfigError, IntegrityError

KEY = bytes(range(32))
OTHER_KEY = bytes(range(1, 33))


def mutate(data, fn):
    data = copy.deepcopy(data)
    fn(data)
    return cfg.validate(data)


def test_valid_config_has_no_problems(config_data):
    assert cfg.validate(config_data) == []


@pytest.mark.parametrize("change, expected", [
    (lambda d: d.update(extra=1), "unknown key 'extra'"),
    (lambda d: d.update(mode="live"), "only 'design' is"),
    (lambda d: d["actions"][0].update(recipient="nobody"), "recipient must be a configured contact_id"),
    (lambda d: d["actions"][0].update(disclose=["precise_location"]), "not in shared_fields_allowed"),
    (lambda d: d["actions"][0].update(disclose=["coarse_location"]), "location sharing must be time-limited"),
    (lambda d: d["actions"][0].update(trigger="obstacle_ahead"), "trigger must be one of"),
    (lambda d: d["contacts"][1].update(channel="sms"), "only through the platform's emergency interface"),
    (lambda d: d["retention"].update(raw_media="7d"), "raw_media must be 'none'"),
    (lambda d: d["retention"].update(location_in_logs=True), "location_in_logs must be false"),
    (lambda d: d["retention"].update(training_use=True), "training needs separate consent"),
    (lambda d: d["consent"].update(expires_at=d["consent"]["granted_at"]), "must be after"),
    (lambda d: d["sensor_scopes"][0].update(device_id="ghost"), "device is not enrolled"),
    (lambda d: d["alerting"].update(max_volume_pct=150), "from 1 to 100"),
    (lambda d: d.update(approved_at="2026-11-16T00:00:00"), "no UTC offset"),
])
def test_schema_rejects(config_data, change, expected):
    problems = mutate(config_data, change)
    assert any(expected in p for p in problems), problems


def test_time_limited_location_sharing_is_accepted(config_data):
    def change(d):
        d["actions"][0]["disclose"] = ["coarse_location"]
        d["actions"][0]["location_share_s"] = 3600
    assert mutate(config_data, change) == []


def test_sign_and_verify(config_data):
    signed = cfg.sign(config_data, KEY)
    assert cfg.signature_status(signed, KEY) == "verified"
    assert cfg.signature_status(signed, OTHER_KEY) == "invalid"
    assert cfg.signature_status(config_data, KEY) == "unsigned"
    assert cfg.signature_status(signed, None) == "no_key"
    tampered = copy.deepcopy(signed)
    tampered["contacts"][0]["label"] = "Someone else"
    assert cfg.signature_status(tampered, KEY) == "invalid"
    assert cfg.load_trusted(signed, KEY).principal == "SIR"


def test_load_trusted_refuses_unsigned_and_invalid(config_data):
    with pytest.raises(IntegrityError, match="unsigned"):
        cfg.load_trusted(config_data, KEY)
    bad = copy.deepcopy(config_data)
    bad["mode"] = "live"
    with pytest.raises(ConfigError):
        cfg.load_trusted(cfg.sign(bad, KEY), KEY)


def test_example_config_is_valid_unsigned_and_flags_placeholders():
    with open(os.path.join(PKG_ROOT, "clearguard.example.json"), encoding="utf-8") as handle:
        data = json.load(handle)
    assert cfg.validate(data) == []
    assert cfg.signature_status(data, KEY) == "unsigned"
    assert "policy_version" in cfg.placeholders(data)
    assert "contacts[0].recipient_ref" in cfg.placeholders(data)


def test_consent_window(trusted, later):
    assert trusted.consent_active(later(0))
    assert not trusted.consent_active(later(86400))
    assert not trusted.consent_active(later(-7200))


def test_keys(tmp_path):
    path = tmp_path / "test.key"
    cfg.generate_key(str(path))
    assert len(cfg.read_key(str(path))) == 32
    assert (os.stat(path).st_mode & 0o777) == 0o600
    with pytest.raises(FileExistsError):
        cfg.generate_key(str(path))
    os.chmod(path, 0o640)
    with pytest.raises(IntegrityError, match="readable by other users"):
        cfg.read_key(str(path))
