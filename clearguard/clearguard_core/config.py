"""Trusted configuration (spec section 3).

Operational configuration is accepted only from a file that passes schema
validation AND carries a valid HMAC-SHA256 signature made with the owner's key.
Nothing a user says, and nothing a sensor observes, can change it: the command
interpreter has no code path that writes configuration.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import stat
from dataclasses import dataclass
from datetime import datetime

from .errors import ClearGuardError, ConfigError, IntegrityError
from .timeutil import parse_time

SCHEMA_ID = "clearguard.config/1"
SIGNATURE_ALG = "HMAC-SHA256"

REQUIRED_KEYS = (
    "schema", "policy_version", "approved_at", "approved_by", "principal_address", "mode",
    "devices", "sensor_scopes", "allowed_services", "contacts", "actions",
    "shared_fields_allowed", "consent", "alerting", "retention",
)
ALLOWED_KEYS = set(REQUIRED_KEYS) | {"signature", "_comment"}

# This build supports design mode only. A live mode needs host integrations
# (sensor adapters, audio output, emergency interface) that do not exist here.
SUPPORTED_MODES = {"design"}
DEVICE_KINDS = {"phone", "watch", "headphones", "wearable_camera"}
SENSORS = {
    "accelerometer", "gyroscope", "camera", "microphone", "location_coarse", "location_precise",
    "platform_fall_detection", "platform_emergency_alerts", "battery", "headphone_route",
}
# Triggers that may start an external action. Hazards inferred from sensors are
# deliberately absent unless a platform detector reports them.
ACTION_TRIGGERS = {"explicit_help_request", "missed_check_in", "device_fall_event"}
SHAREABLE_FIELDS = {
    "help_request", "event_time", "event_category", "coarse_location", "precise_location", "battery_level",
}
LOCATION_FIELDS = {"coarse_location", "precise_location"}
ALERT_CHANNELS = ("headphones", "watch_haptic", "phone_notification")
CONTACT_CHANNELS = {"sms", "phone_call", "app_push", "platform_emergency"}


def _is_placeholder(value: object) -> bool:
    return isinstance(value, str) and value.strip().startswith("[")


def _nonempty_str(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _pos_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def validate(data: object) -> list[str]:
    """Return every schema problem. An empty list means the structure is valid;
    it says nothing about authenticity (see verify_signature)."""
    if not isinstance(data, dict):
        return ["configuration must be a JSON object"]
    problems: list[str] = []
    for key in sorted(set(data) - ALLOWED_KEYS):
        problems.append(f"unknown key '{key}' (unknown keys are rejected, not ignored)")
    for key in REQUIRED_KEYS:
        if key not in data:
            problems.append(f"missing key '{key}'")
    if problems:
        return problems

    if data["schema"] != SCHEMA_ID:
        problems.append(f"schema must be '{SCHEMA_ID}'")
    for key in ("policy_version", "approved_by", "principal_address"):
        if not _nonempty_str(data[key]):
            problems.append(f"{key} must be a non-empty string")
    try:
        parse_time(data["approved_at"])
    except ValueError as exc:
        problems.append(f"approved_at: {exc}")
    if data["mode"] not in SUPPORTED_MODES:
        problems.append(
            f"mode '{data['mode']}' is not supported by this build; only 'design' is. "
            "Live mode needs host sensor, audio and emergency integrations that do not exist here"
        )

    device_ids: set[str] = set()
    if not isinstance(data["devices"], list):
        problems.append("devices must be a list")
    else:
        for i, dev in enumerate(data["devices"]):
            if not isinstance(dev, dict) or not _nonempty_str(dev.get("device_id")):
                problems.append(f"devices[{i}]: needs a device_id")
                continue
            if dev.get("kind") not in DEVICE_KINDS:
                problems.append(f"devices[{i}]: kind must be one of {sorted(DEVICE_KINDS)}")
            if dev["device_id"] in device_ids:
                problems.append(f"devices[{i}]: duplicate device_id")
            device_ids.add(dev["device_id"])

    if not isinstance(data["sensor_scopes"], list):
        problems.append("sensor_scopes must be a list")
    else:
        for i, scope in enumerate(data["sensor_scopes"]):
            if not isinstance(scope, dict):
                problems.append(f"sensor_scopes[{i}]: must be an object")
                continue
            if scope.get("device_id") not in device_ids:
                problems.append(f"sensor_scopes[{i}]: device is not enrolled")
            if scope.get("sensor") not in SENSORS:
                problems.append(f"sensor_scopes[{i}]: sensor must be one of {sorted(SENSORS)}")
            if not _nonempty_str(scope.get("purpose")):
                problems.append(f"sensor_scopes[{i}]: a stated purpose is required")

    if not isinstance(data["allowed_services"], list) or not all(_nonempty_str(s) for s in data["allowed_services"]):
        problems.append("allowed_services must be a list of service names")

    shared = data["shared_fields_allowed"]
    if not isinstance(shared, list) or not set(shared) <= SHAREABLE_FIELDS:
        problems.append(f"shared_fields_allowed must be a subset of {sorted(SHAREABLE_FIELDS)}")
        shared = []

    contact_ids: dict[str, dict] = {}
    if not isinstance(data["contacts"], list):
        problems.append("contacts must be a list")
    else:
        for i, contact in enumerate(data["contacts"]):
            if not isinstance(contact, dict) or not _nonempty_str(contact.get("contact_id")):
                problems.append(f"contacts[{i}]: needs a contact_id")
                continue
            if contact.get("channel") not in CONTACT_CHANNELS:
                problems.append(f"contacts[{i}]: channel must be one of {sorted(CONTACT_CHANNELS)}")
            if not _nonempty_str(contact.get("label")):
                problems.append(f"contacts[{i}]: needs a label")
            if not isinstance(contact.get("is_emergency_service"), bool):
                problems.append(f"contacts[{i}]: is_emergency_service must be true or false")
            elif contact["is_emergency_service"] and contact.get("channel") != "platform_emergency":
                problems.append(
                    f"contacts[{i}]: an emergency service is reached only through the platform's "
                    "emergency interface (channel 'platform_emergency')"
                )
            contact_ids[contact["contact_id"]] = contact

    action_ids: set[str] = set()
    if not isinstance(data["actions"], list):
        problems.append("actions must be a list")
    else:
        for i, action in enumerate(data["actions"]):
            where = f"actions[{i}]"
            if not isinstance(action, dict) or not _nonempty_str(action.get("action_id")):
                problems.append(f"{where}: needs an action_id")
                continue
            if action["action_id"] in action_ids:
                problems.append(f"{where}: duplicate action_id")
            action_ids.add(action["action_id"])
            if action.get("trigger") not in ACTION_TRIGGERS:
                problems.append(f"{where}: trigger must be one of {sorted(ACTION_TRIGGERS)}")
            if action.get("recipient") not in contact_ids:
                problems.append(f"{where}: recipient must be a configured contact_id")
            disclose = action.get("disclose")
            if not isinstance(disclose, list) or not disclose:
                problems.append(f"{where}: disclose must list the fields shared")
            elif not set(disclose) <= set(shared):
                problems.append(f"{where}: discloses fields not in shared_fields_allowed")
            elif set(disclose) & LOCATION_FIELDS and not _pos_int(action.get("location_share_s")):
                problems.append(f"{where}: location sharing must be time-limited (location_share_s)")
            for key in ("countdown_s", "max_retries"):
                value = action.get(key)
                if not (isinstance(value, int) and not isinstance(value, bool) and value >= 0):
                    problems.append(f"{where}: {key} must be a whole number of 0 or more")
            if not _pos_int(action.get("expires_after_s")):
                problems.append(f"{where}: expires_after_s must be a positive whole number")
            for key in ("cancellable", "requires_confirmation_at_execution"):
                if not isinstance(action.get(key), bool):
                    problems.append(f"{where}: {key} must be true or false")

    consent = data["consent"]
    if not isinstance(consent, dict):
        problems.append("consent must be an object")
    else:
        try:
            granted = parse_time(consent.get("granted_at"))
            expires = parse_time(consent.get("expires_at"))
            if expires <= granted:
                problems.append("consent.expires_at must be after consent.granted_at")
        except ValueError as exc:
            problems.append(f"consent: {exc}")
        if not isinstance(consent.get("revoked"), bool):
            problems.append("consent.revoked must be true or false")

    alerting = data["alerting"]
    if not isinstance(alerting, dict):
        problems.append("alerting must be an object")
    else:
        channels = alerting.get("channels")
        if not isinstance(channels, list) or not channels or not set(channels) <= set(ALERT_CHANNELS):
            problems.append(f"alerting.channels must be a non-empty subset of {list(ALERT_CHANNELS)}")
        volume = alerting.get("max_volume_pct")
        if not (isinstance(volume, int) and not isinstance(volume, bool) and 1 <= volume <= 100):
            problems.append("alerting.max_volume_pct must be a whole number from 1 to 100")
        if not isinstance(alerting.get("directional_audio"), bool):
            problems.append("alerting.directional_audio must be true or false")

    retention = data["retention"]
    if not isinstance(retention, dict):
        problems.append("retention must be an object")
    else:
        if not _pos_int(retention.get("event_hours")):
            problems.append("retention.event_hours must be a positive whole number")
        if retention.get("raw_media") != "none":
            problems.append("retention.raw_media must be 'none' (this build keeps no raw media)")
        if retention.get("location_in_logs") is not False:
            problems.append("retention.location_in_logs must be false")
        if retention.get("training_use") is not False:
            problems.append("retention.training_use must be false (training needs separate consent)")
    return problems


def placeholders(data: dict) -> list[str]:
    """Bracketed values such as "[CONFIRM]" that the owner still has to fill in."""
    found: list[str] = []

    def walk(node: object, path: str) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{path}.{k}" if path else k)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")
        elif _is_placeholder(node):
            found.append(path)

    walk({k: v for k, v in data.items() if k not in ("signature", "_comment")}, "")
    return found


def canonical_bytes(data: dict) -> bytes:
    body = {k: v for k, v in data.items() if k != "signature"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _mac(key: bytes, data: dict) -> str:
    return hmac.new(key, canonical_bytes(data), hashlib.sha256).hexdigest()


def key_id(key: bytes) -> str:
    return hashlib.sha256(b"clearguard-key-id" + key).hexdigest()[:16]


def sign(data: dict, key: bytes) -> dict:
    signed = {k: v for k, v in data.items() if k != "signature"}
    signed["signature"] = {"alg": SIGNATURE_ALG, "key_id": key_id(key), "value": _mac(key, signed)}
    return signed


def signature_status(data: dict, key: bytes | None) -> str:
    """'verified', 'unsigned', 'invalid', or 'no_key'."""
    sig = data.get("signature")
    if sig is None:
        return "unsigned"
    if key is None:
        return "no_key"
    if not isinstance(sig, dict) or sig.get("alg") != SIGNATURE_ALG or not isinstance(sig.get("value"), str):
        return "invalid"
    if sig.get("key_id") != key_id(key):
        return "invalid"
    return "verified" if hmac.compare_digest(sig["value"], _mac(key, data)) else "invalid"


def generate_key(path: str) -> str:
    """Write a new 32-byte key (hex) with mode 0600. Refuses to overwrite."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as handle:
        handle.write(secrets.token_hex(32) + "\n")
    return path


def read_key(path: str) -> bytes:
    try:
        info = os.stat(path)
    except OSError as exc:
        raise ClearGuardError(f"cannot read key file: {exc.strerror}") from exc
    if os.name == "posix" and stat.S_IMODE(info.st_mode) & 0o077:
        raise IntegrityError("key file is readable by other users; set its mode to 0600")
    with open(path, encoding="ascii") as handle:
        text = handle.read().strip()
    try:
        key = bytes.fromhex(text)
    except ValueError as exc:
        raise IntegrityError("key file is not hex") from exc
    if len(key) < 32:
        raise IntegrityError("key must be at least 32 bytes")
    return key


def read_json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except OSError as exc:
        raise ClearGuardError(f"cannot read {path}: {exc.strerror}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError([f"{path} is not valid JSON: {exc.msg} at line {exc.lineno}"]) from exc
    if not isinstance(data, dict):
        raise ConfigError(["configuration must be a JSON object"])
    return data


@dataclass(frozen=True)
class TrustedConfig:
    """A configuration that passed both validation and signature verification."""

    data: dict

    @property
    def principal(self) -> str:
        return self.data["principal_address"]

    @property
    def mode(self) -> str:
        return self.data["mode"]

    def consent_active(self, now: datetime) -> bool:
        consent = self.data["consent"]
        if consent["revoked"]:
            return False
        return parse_time(consent["granted_at"]) <= now < parse_time(consent["expires_at"])

    def actions_for(self, trigger: str) -> list[dict]:
        return [a for a in self.data["actions"] if a["trigger"] == trigger]

    def contact(self, contact_id: str) -> dict:
        for contact in self.data["contacts"]:
            if contact["contact_id"] == contact_id:
                return contact
        raise KeyError(contact_id)

    def sensors(self) -> set[str]:
        return {s["sensor"] for s in self.data["sensor_scopes"]}


def load_trusted(data: dict, key: bytes) -> TrustedConfig:
    problems = validate(data)
    if problems:
        raise ConfigError(problems)
    status = signature_status(data, key)
    if status != "verified":
        raise IntegrityError(f"configuration signature {status}; it is not accepted for operation")
    return TrustedConfig(data=data)
