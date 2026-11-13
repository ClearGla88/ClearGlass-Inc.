"""Operator configuration: conservative defaults and strict validation.

``config.json`` lives in the state directory and is meant to be edited by the
operator. Unknown keys are rejected so a typo cannot silently disable a check.
Its SHA-256 is recorded in each approved baseline; ``scan`` reports a change.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
from typing import Any

from . import fsutil
from .errors import ConfigError

CONFIG_NAME = "config.json"
MAX_CONFIG_BYTES = 1 << 20

DEFAULTS: dict[str, Any] = {
    "integrity": {
        "max_file_bytes": 64 * 1024 * 1024,
    },
    "auth": {
        "enabled": True,
        "sources": ["auto"],
        "failure_threshold": 10,
        "window_seconds": 600,
        "initial_lookback_seconds": 3600,
        "max_bytes_per_scan": 50 * 1024 * 1024,
        "journal_timeout_seconds": 30,
        "record_invalid_usernames": False,
        "max_tracked_sources": 10000,
    },
    "listeners": {
        "enabled": True,
        "attribute_processes": True,
        "attribution_time_budget_seconds": 5.0,
        "allow": [],
    },
    "audio": {
        "window_ms": 1000,
        "sustained_dbfs": -12.0,
        "sustained_seconds": 10.0,
        "clip_run_samples": 3,
        "max_bytes": 2 * 1024 * 1024 * 1024,
        "max_seconds": 7200,
        "live": {
            "enabled": False,
            "max_seconds": 600,
            "sample_rate": 48000,
            "channels": 1,
        },
    },
    "audit": {
        "max_log_bytes": 64 * 1024 * 1024,
        "max_findings_per_record": 200,
    },
}

# key path -> (type(s), minimum, maximum). Lists are validated separately.
_NUMERIC_RULES: dict[tuple[str, ...], tuple[type | tuple[type, ...], float, float]] = {
    ("integrity", "max_file_bytes"): (int, 1, 1 << 40),
    ("auth", "failure_threshold"): (int, 1, 1_000_000),
    ("auth", "window_seconds"): (int, 1, 7 * 86400),
    ("auth", "initial_lookback_seconds"): (int, 0, 30 * 86400),
    ("auth", "max_bytes_per_scan"): (int, 1024, 1 << 34),
    ("auth", "journal_timeout_seconds"): (int, 1, 3600),
    ("auth", "max_tracked_sources"): (int, 1, 1_000_000),
    ("listeners", "attribution_time_budget_seconds"): ((int, float), 0.1, 300),
    ("audio", "window_ms"): (int, 10, 60_000),
    ("audio", "sustained_dbfs"): ((int, float), -200, 0),
    ("audio", "sustained_seconds"): ((int, float), 0.01, 86400),
    ("audio", "clip_run_samples"): (int, 1, 1_000_000),
    ("audio", "max_bytes"): (int, 44, 1 << 40),
    ("audio", "max_seconds"): ((int, float), 1, 7 * 86400),
    ("audio", "live", "max_seconds"): ((int, float), 1, 86400),
    ("audio", "live", "sample_rate"): (int, 1000, 384_000),
    ("audio", "live", "channels"): (int, 1, 8),
    ("audit", "max_log_bytes"): (int, 4096, 1 << 40),
    ("audit", "max_findings_per_record"): (int, 1, 100_000),
}
_BOOL_KEYS = {
    ("auth", "enabled"),
    ("auth", "record_invalid_usernames"),
    ("listeners", "enabled"),
    ("listeners", "attribute_processes"),
    ("audio", "live", "enabled"),
}


def config_path(state_dir: str) -> str:
    return os.path.join(state_dir, CONFIG_NAME)


def default_config() -> dict[str, Any]:
    return copy.deepcopy(DEFAULTS)


def _merge(base: dict, override: dict, path: tuple[str, ...]) -> None:
    for key, value in override.items():
        here = path + (key,)
        if key not in base:
            raise ConfigError(f"unknown configuration key: {'.'.join(here)}")
        if isinstance(base[key], dict):
            if not isinstance(value, dict):
                raise ConfigError(f"{'.'.join(here)} must be an object")
            _merge(base[key], value, here)
        else:
            base[key] = value


def _get(cfg: dict, path: tuple[str, ...]) -> Any:
    node: Any = cfg
    for part in path:
        node = node[part]
    return node


def validate(cfg: dict) -> None:
    for path, (types, low, high) in _NUMERIC_RULES.items():
        value = _get(cfg, path)
        if isinstance(value, bool) or not isinstance(value, types):
            raise ConfigError(f"{'.'.join(path)} must be a number")
        if not low <= value <= high:
            raise ConfigError(f"{'.'.join(path)}={value} is outside {low}..{high}")
    for path in _BOOL_KEYS:
        if not isinstance(_get(cfg, path), bool):
            raise ConfigError(f"{'.'.join(path)} must be true or false")
    sources = cfg["auth"]["sources"]
    if not isinstance(sources, list) or not sources:
        raise ConfigError("auth.sources must be a non-empty list")
    for src in sources:
        if not isinstance(src, str) or not (
            src in ("auto", "journal") or (src.startswith("file:/") and len(src) > 6)
        ):
            raise ConfigError(
                f"auth.sources entry {src!r} must be 'auto', 'journal', or 'file:/absolute/path'"
            )
    allow = cfg["listeners"]["allow"]
    if not isinstance(allow, list) or not all(isinstance(a, str) for a in allow):
        raise ConfigError("listeners.allow must be a list of strings like '127.0.0.1:631'")


def load_config(state_dir: str) -> tuple[dict, str]:
    """Return (config, sha256 of the file bytes)."""
    path = config_path(state_dir)
    try:
        raw = fsutil.read_private_file(path, MAX_CONFIG_BYTES)
    except FileNotFoundError:
        raise ConfigError(f"{path} is missing. Re-create it from clearshield.example.json.") from None
    try:
        override = json.loads(raw)
    except ValueError as exc:
        raise ConfigError(f"{path} is not valid JSON: {exc}") from None
    if not isinstance(override, dict):
        raise ConfigError(f"{path} must contain a JSON object")
    override.pop("_comment", None)
    cfg = default_config()
    _merge(cfg, override, ())
    validate(cfg)
    return cfg, hashlib.sha256(raw).hexdigest()


def write_default_config(state_dir: str) -> None:
    body = {"_comment": "ClearShield configuration. See README.md for every key."}
    body.update(default_config())
    fsutil.create_exclusive(
        config_path(state_dir), (json.dumps(body, indent=2) + "\n").encode("utf-8"), 0o600
    )
