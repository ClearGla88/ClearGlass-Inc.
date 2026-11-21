"""Lab helpers: secret generation and throwaway deployments for tests and the demo.

Everything here is synthetic. ``make_lab_deployment`` writes a configuration
that points at this package's example inventory, rules and playbooks, plus
freshly generated keys and tokens, into a directory you choose.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_CONFIG = PACKAGE_ROOT / "config" / "defense.example.yaml"

SENSORS: list[dict[str, Any]] = [
    {"id": "sensor-http-01", "kind": "http_honeypot", "allowed_categories": ["honeypot.http.request"]},
    {"id": "sensor-tcp-01", "kind": "tcp_tripwire", "allowed_categories": ["tripwire.tcp.connect"]},
    {"id": "sensor-file-01", "kind": "honeyfile", "host_asset_id": "lab-ws-002",
     "allowed_categories": ["honeyfile.access", "honeyfile.modify"]},
    {"id": "sensor-edr-01", "kind": "edr_mock", "asserts_asset_identity": True, "allowed_categories": ["endpoint.alert"]},
    {"id": "sensor-flow-01", "kind": "flow_monitor", "allowed_categories": ["network.flow"]},
    {"id": "sensor-integrity-01", "kind": "integrity_monitor", "allowed_categories": ["sensor.health"]},
]
PRINCIPALS: list[tuple[str, str]] = [
    ("analyst-1", "analyst"), ("approver-1", "approver"), ("approver-2", "approver"), ("admin-1", "admin"),
]


def write_secret(path: Path, *, overwrite: bool = False) -> str:
    """Create a 0600 file holding a fresh 256-bit secret. Refuses to overwrite."""
    path.parent.mkdir(parents=True, exist_ok=True)
    value = secrets.token_urlsafe(32)
    flags = os.O_WRONLY | os.O_CREAT | (os.O_TRUNC if overwrite else os.O_EXCL)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(value + "\n")
    return value


def init_secrets(config_path: str | Path) -> list[Path]:
    """Create every key_file and token_file a configuration names that does not exist yet."""
    cfg_path = Path(config_path).resolve()
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    created = []
    wanted = [s.get("key_file") for s in data.get("sensors", [])] + [
        p.get("token_file") for p in data.get("principals", [])
    ]
    for rel in filter(None, wanted):
        path = Path(rel) if Path(rel).is_absolute() else cfg_path.parent / rel
        if not path.exists():
            write_secret(path)
            created.append(path.resolve())
    return created


@dataclass
class LabDeployment:
    config_path: Path
    root: Path
    sensor_keys: dict[str, bytes]
    tokens: dict[str, str]


def make_lab_deployment(root: str | Path, *, mode: str = "recommend", response: dict | None = None,
                        ingest: dict | None = None, environment: str = "lab") -> LabDeployment:
    root = Path(root).resolve()
    sec = root / "secrets"
    keys: dict[str, bytes] = {}
    sensors = []
    for s in SENSORS:
        keys[s["id"]] = write_secret(sec / f"{s['id']}.key").encode()
        sensors.append({**s, "key_file": str(sec / f"{s['id']}.key")})
    tokens: dict[str, str] = {}
    principals = []
    for name, role in PRINCIPALS:
        tokens[name] = write_secret(sec / f"{name}.token")
        principals.append({"principal": name, "role": role, "token_file": str(sec / f"{name}.token")})
    cfg = {
        "schema_version": 1,
        "environment": environment,
        "mode": mode,
        "policy_version": "pv-lab-1",
        "authorization_scope": "clearglass-lab-01",
        "database": str(root / "var" / "active_defense.db"),
        "state_dir": str(root / "var"),
        "assets_file": str(PACKAGE_ROOT / "config" / "assets.example.yaml"),
        "rules_file": str(PACKAGE_ROOT / "rules" / "detections.yaml"),
        "playbooks_dir": str(PACKAGE_ROOT / "playbooks"),
        "ingest": ingest or {},
        "response": response or {},
        "sensors": sensors,
        "principals": principals,
    }
    path = root / "defense.yaml"
    path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    return LabDeployment(path, root, keys, tokens)
