"""Configuration, inventory, rules and playbooks fail closed."""

from __future__ import annotations

import os
import shutil

import pytest
import yaml

from active_defense.config import ConfigError, load_bundle
from active_defense.lab import EXAMPLE_CONFIG, PACKAGE_ROOT, init_secrets, make_lab_deployment
from active_defense.models import ResponseConfig


def _edit(dep, fn):
    data = yaml.safe_load(dep.config_path.read_text())
    fn(data)
    dep.config_path.write_text(yaml.safe_dump(data))
    return dep.config_path


def test_lab_deployment_loads_all_eight_playbooks(tmp_path):
    b = load_bundle(make_lab_deployment(tmp_path).config_path)
    assert len(b.playbooks) == 8 and b.config.response.adapter == "mock"


@pytest.mark.parametrize("edit, message", [
    (lambda d: d.update(unknown_setting=True), "Extra inputs"),
    (lambda d: d["response"].update(adapter="vendor-firewall"), "not implemented"),
    (lambda d: d.update(mode="enforce"), "enforce_acknowledged"),
    (lambda d: (d.update(mode="enforce"), d["response"].update(enforce_acknowledged=True)), "preauthorized"),
    (lambda d: d["response"].update(enforce_preauthorized_playbooks=["PB-03-isolate-corroborated-host"]),
     "only valid in mode"),
    (lambda d: d["ingest"].update(nonce_ttl_seconds=300, clock_skew_seconds=300), "twice"),
    (lambda d: d["sensors"][0].update(asserts_asset_identity=True), "only an endpoint sensor"),
    (lambda d: d["sensors"][0]["allowed_categories"].append("sensor.health"), "integrity monitor"),
])
def test_invalid_configuration_is_refused(tmp_path, edit, message):
    path = _edit(make_lab_deployment(tmp_path), edit)
    with pytest.raises(ConfigError, match=message):
        load_bundle(path)


def test_missing_or_weak_secret_fails_closed(tmp_path):
    dep = make_lab_deployment(tmp_path)
    (tmp_path / "secrets" / "sensor-tcp-01.key").unlink()
    with pytest.raises(ConfigError, match="not found"):
        load_bundle(dep.config_path)
    (tmp_path / "secrets" / "sensor-tcp-01.key").write_text("short")
    with pytest.raises(ConfigError, match="shorter than"):
        load_bundle(dep.config_path)


def test_shared_principal_token_is_refused(tmp_path):
    dep = make_lab_deployment(tmp_path)
    shutil.copy(tmp_path / "secrets" / "analyst-1.token", tmp_path / "secrets" / "approver-1.token")
    with pytest.raises(ConfigError, match="shared"):
        load_bundle(dep.config_path)


def _copy_package(tmp_path):
    root = tmp_path / "pkg"
    for d in ("config", "rules", "playbooks"):
        shutil.copytree(PACKAGE_ROOT / d, root / d)
    init_secrets(root / "config" / "defense.example.yaml")
    return root


def test_example_config_validates_after_init_secrets(tmp_path):
    root = _copy_package(tmp_path)
    b = load_bundle(root / "config" / "defense.example.yaml")
    assert b.config.mode == "observe"  # conservative default
    assert oct(os.stat(root / "secrets" / "admin-1.token").st_mode & 0o777) == "0o600"
    assert init_secrets(root / "config" / "defense.example.yaml") == []  # never overwrites


def test_isolation_playbook_without_approval_is_refused(tmp_path):
    root = _copy_package(tmp_path)
    path = root / "playbooks" / "PB-03-isolate-corroborated-host.yaml"
    data = yaml.safe_load(path.read_text())
    data["approval"]["required"] = False
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ConfigError, match="must require approval"):
        load_bundle(root / "config" / "defense.example.yaml")


def test_isolation_playbook_must_exclude_every_protected_class(tmp_path):
    root = _copy_package(tmp_path)
    path = root / "playbooks" / "PB-05-ransomware-containment.yaml"
    data = yaml.safe_load(path.read_text())
    data["asset_exclusions"].remove("backup")
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ConfigError, match="backup"):
        load_bundle(root / "config" / "defense.example.yaml")


def test_signal_playbook_may_not_propose_containment(tmp_path):
    root = _copy_package(tmp_path)
    path = root / "rules" / "detections.yaml"
    data = yaml.safe_load(path.read_text())
    data["signal_playbooks"]["decoy_interaction"] = "PB-03-isolate-corroborated-host"
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ConfigError, match="single signal never may"):
        load_bundle(root / "config" / "defense.example.yaml")


def test_missing_required_playbook_is_refused(tmp_path):
    root = _copy_package(tmp_path)
    (root / "playbooks" / "PB-08-sensor-distrust.yaml").unlink()
    with pytest.raises(ConfigError, match="PB-08"):
        load_bundle(root / "config" / "defense.example.yaml")


def test_protected_asset_cannot_be_authorized(tmp_path):
    root = _copy_package(tmp_path)
    path = root / "config" / "assets.example.yaml"
    data = yaml.safe_load(path.read_text())
    dc = next(a for a in data["assets"] if a["asset_id"] == "lab-dc-001")
    dc.update(authorized_for_containment=True, adapter="mock", management_paths=["10.66.0.10/32:22"])
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ConfigError, match="protected asset cannot be authorized"):
        load_bundle(root / "config" / "defense.example.yaml")


def test_only_mock_adapter_exists():
    with pytest.raises(ValueError, match="not implemented"):
        ResponseConfig(adapter="edr")
    assert EXAMPLE_CONFIG.is_file()
