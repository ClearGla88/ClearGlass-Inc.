"""Authenticated security state (watch list, baseline, cursors, audit head).

``state.json`` is a JSON object whose ``data`` member is authenticated with the
same HMAC key as the audit log. Any edit to it without the key is detected on
the next load and treated as an integrity failure (exit code 3).
"""

from __future__ import annotations

import hmac
import json
import os
from typing import Any

from . import fsutil
from .audit import Keyring, canonical, compute_tag
from .errors import IntegrityFailure

STATE_NAME = "state.json"
STATE_FORMAT = "clearshield-state"
STATE_VERSION = 1
MAX_STATE_BYTES = 64 * 1024 * 1024


def state_path(state_dir: str) -> str:
    return os.path.join(state_dir, STATE_NAME)


def new_state_data(watch: list[str], audit_head: dict, created: str) -> dict[str, Any]:
    return {
        "created": created,
        "watch": sorted(set(watch)),
        "baseline": None,
        "previous_baseline": None,
        "audit_head": audit_head,
        "auth": {"cursors": {}, "recent": {}, "alerted": {}},
        "purged_segments": [],
    }


def _envelope(keyring: Keyring, data: dict) -> dict:
    body = {"format": STATE_FORMAT, "v": STATE_VERSION, "kid": keyring.active_kid, "data": data}
    body["tag"] = compute_tag(keyring.active, body)
    return body


def save_state(state_dir: str, keyring: Keyring, data: dict) -> None:
    fsutil.atomic_write(state_path(state_dir), canonical(_envelope(keyring, data)) + b"\n")


def load_state(state_dir: str, keyring: Keyring) -> dict:
    path = state_path(state_dir)
    try:
        raw = fsutil.read_private_file(path, MAX_STATE_BYTES)
    except FileNotFoundError:
        raise IntegrityFailure(f"{path} is missing (deleted, or never initialized).") from None
    try:
        envelope = json.loads(raw)
    except ValueError:
        raise IntegrityFailure(f"{path} is not valid JSON (corrupted or tampered).") from None
    if not isinstance(envelope, dict) or envelope.get("format") != STATE_FORMAT:
        raise IntegrityFailure(f"{path} is not a ClearShield state file.")
    if envelope.get("v") != STATE_VERSION:
        raise IntegrityFailure(f"{path} has unsupported version {envelope.get('v')!r}.")
    key = keyring.get(envelope.get("kid", ""))
    if key is None:
        raise IntegrityFailure(f"{path} was written with a key that is not available.")
    tag = envelope.get("tag")
    body = {k: v for k, v in envelope.items() if k != "tag"}
    if not isinstance(tag, str) or not hmac.compare_digest(compute_tag(key, body), tag):
        raise IntegrityFailure(f"{path} failed authentication (modified or wrong key).")
    data = envelope.get("data")
    if not isinstance(data, dict):
        raise IntegrityFailure(f"{path} has no data object.")
    return data
