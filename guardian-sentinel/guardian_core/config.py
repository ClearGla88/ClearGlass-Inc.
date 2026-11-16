"""Trusted configuration (SPEC section 3).

Operational configuration is accepted only from a file authenticated with an
HMAC-SHA256 tag under the enrollment key, and only if every field passes the
schema. Unknown fields are refused at every level, so no permission can be
added except by a new, re-authenticated file. Natural-language requests have
no path into this module.

An HMAC tag is a shared-secret authenticator: whoever holds the key can sign.
Keep the key out of the repository and off shared storage.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .errors import ConfigError
from .hazards import HazardKind
from .states import Priority

KEY_BYTES = 32
DEVICE_KINDS = {"phone", "watch", "headphones", "camera"}
SENSORS = {"camera", "microphone", "accelerometer", "location", "official_alerts"}
CHANNELS = {"sms", "call", "push"}
ACTION_KINDS = {"notify_contact", "share_location", "call_emergency_interface"}
DATA_FIELDS = {"display_name", "approximate_location", "hazard_kind", "event_time", "battery_level"}
CANCEL_METHODS = {"app_button", "voice_command", "both"}
NATIVE_EMERGENCY = "native_emergency_interface"

TOP_FIELDS = {
    "policy_version", "approved_at", "approved_by", "enrolled_devices", "sensor_scopes",
    "external_services", "contacts", "permitted_actions", "shared_data_fields",
    "consent_expires_at", "cancellation",
}


def canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def generate_key() -> bytes:
    return secrets.token_bytes(KEY_BYTES)


def key_id(key: bytes) -> str:
    return hashlib.sha256(b"guardian-kid:" + key).hexdigest()[:16]


def read_key(path: str) -> bytes:
    try:
        with open(path, "r", encoding="ascii") as fh:
            key = bytes.fromhex(fh.read().strip())
    except (OSError, ValueError) as exc:
        raise ConfigError(f"cannot read key file: {exc.__class__.__name__}") from None
    if len(key) != KEY_BYTES:
        raise ConfigError("key file must hold 32 bytes as hex")
    return key


def write_key(path: str, key: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as fh:
        fh.write(key.hex() + "\n")


def sign(config: dict, key: bytes) -> dict:
    """Return the authenticated envelope for ``config`` (validated first)."""
    validate(config)
    tag = hmac.new(key, canonical(config), hashlib.sha256).hexdigest()
    return {"config": config, "kid": key_id(key), "tag": tag}


def parse_time(value: Any, name: str) -> datetime:
    if not isinstance(value, str):
        raise ConfigError(f"{name} must be an ISO 8601 string")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        raise ConfigError(f"{name} is not a valid ISO 8601 time") from None
    if when.tzinfo is None:
        raise ConfigError(f"{name} must include a time zone")
    return when.astimezone(timezone.utc)


@dataclass(frozen=True)
class Action:
    action_id: str
    kind: str
    trigger_hazard: HazardKind
    min_priority: Priority
    recipient: str
    data_fields: tuple[str, ...]
    countdown_s: int
    retry_limit: int
    requires_host_confirmation: bool
    expires_after_s: int


@dataclass(frozen=True)
class TrustedConfig:
    policy_version: str
    approved_at: datetime
    approved_by: str
    devices: dict
    sensor_scopes: tuple
    external_services: tuple[str, ...]
    contacts: dict
    actions: dict
    shared_data_fields: frozenset
    consent_expires_at: datetime
    cancellation_method: str
    recovery: str

    def consent_valid(self, now: float) -> bool:
        return now < self.consent_expires_at.timestamp()

    def action(self, action_id: str) -> Action | None:
        return self.actions.get(action_id)

    def actions_for(self, hazard: HazardKind) -> list[Action]:
        return [a for a in self.actions.values() if a.trigger_hazard is hazard]


def _obj(value: Any, name: str, fields: set[str]) -> dict:
    if not isinstance(value, dict):
        raise ConfigError(f"{name} must be an object")
    unknown = set(value) - fields
    missing = fields - set(value)
    if unknown:
        raise ConfigError(f"{name}: unknown field(s) {sorted(unknown)}")
    if missing:
        raise ConfigError(f"{name}: missing field(s) {sorted(missing)}")
    return value


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise ConfigError(f"{name} must be a non-empty string of at most 200 characters")
    return value


def _choice(value: Any, name: str, allowed: set[str]) -> str:
    if value not in allowed:
        raise ConfigError(f"{name} must be one of {sorted(allowed)}")
    return value


def _int(value: Any, name: str, lo: int, hi: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise ConfigError(f"{name} must be an integer from {lo} to {hi}")
    return value


def _list(value: Any, name: str) -> list:
    if not isinstance(value, list):
        raise ConfigError(f"{name} must be a list")
    return value


def _unique(items: list[str], name: str) -> None:
    if len(items) != len(set(items)):
        raise ConfigError(f"{name} contains duplicates")


def validate(raw: Any) -> TrustedConfig:
    cfg = _obj(raw, "config", TOP_FIELDS)
    approved_at = parse_time(cfg["approved_at"], "approved_at")
    consent_expires = parse_time(cfg["consent_expires_at"], "consent_expires_at")
    if consent_expires <= approved_at:
        raise ConfigError("consent_expires_at must be after approved_at")

    devices = {}
    for i, d in enumerate(_list(cfg["enrolled_devices"], "enrolled_devices")):
        d = _obj(d, f"enrolled_devices[{i}]", {"device_id", "kind"})
        devices[_text(d["device_id"], "device_id")] = _choice(d["kind"], "kind", DEVICE_KINDS)
    if len(devices) != len(cfg["enrolled_devices"]):
        raise ConfigError("enrolled_devices contains duplicates")

    scopes = []
    for i, s in enumerate(_list(cfg["sensor_scopes"], "sensor_scopes")):
        s = _obj(s, f"sensor_scopes[{i}]", {"device_id", "sensor", "scope"})
        if s["device_id"] not in devices:
            raise ConfigError(f"sensor_scopes[{i}] names a device that is not enrolled")
        scopes.append((s["device_id"], _choice(s["sensor"], "sensor", SENSORS),
                       _text(s["scope"], "scope")))

    services = [_text(x, "external_services[]") for x in _list(cfg["external_services"], "external_services")]
    _unique(services, "external_services")

    contacts = {}
    for i, c in enumerate(_list(cfg["contacts"], "contacts")):
        c = _obj(c, f"contacts[{i}]", {"contact_id", "channel", "recipient_ref"})
        cid = _text(c["contact_id"], "contact_id")
        if cid in contacts or cid == NATIVE_EMERGENCY:
            raise ConfigError(f"contacts[{i}] has a duplicate or reserved contact_id")
        contacts[cid] = (_choice(c["channel"], "channel", CHANNELS), _text(c["recipient_ref"], "recipient_ref"))

    shared = [_choice(f, "shared_data_fields[]", DATA_FIELDS)
              for f in _list(cfg["shared_data_fields"], "shared_data_fields")]
    _unique(shared, "shared_data_fields")

    actions = {}
    action_fields = {"action_id", "kind", "trigger", "recipient", "data_fields", "countdown_s",
                     "retry_limit", "requires_host_confirmation", "expires_after_s"}
    for i, a in enumerate(_list(cfg["permitted_actions"], "permitted_actions")):
        a = _obj(a, f"permitted_actions[{i}]", action_fields)
        aid = _text(a["action_id"], "action_id")
        if aid in actions:
            raise ConfigError(f"permitted_actions[{i}] duplicates action_id {aid!r}")
        kind = _choice(a["kind"], "kind", ACTION_KINDS)
        trig = _obj(a["trigger"], f"permitted_actions[{i}].trigger", {"hazard", "min_priority"})
        try:
            hazard = HazardKind(trig["hazard"])
            min_priority = Priority(trig["min_priority"])
        except ValueError:
            raise ConfigError(f"permitted_actions[{i}].trigger names an unsupported hazard or priority") from None
        recipient = _text(a["recipient"], "recipient")
        if kind == "call_emergency_interface":
            if recipient != NATIVE_EMERGENCY:
                raise ConfigError(f"permitted_actions[{i}]: emergency calls go only to {NATIVE_EMERGENCY}")
        elif recipient not in contacts:
            raise ConfigError(f"permitted_actions[{i}] names a recipient that is not an approved contact")
        data = [_text(f, "data_fields[]") for f in _list(a["data_fields"], "data_fields")]
        _unique(data, "data_fields")
        if not set(data) <= set(shared):
            raise ConfigError(f"permitted_actions[{i}] shares fields outside shared_data_fields")
        if kind == "share_location" and "approximate_location" not in data:
            raise ConfigError(f"permitted_actions[{i}]: share_location must list approximate_location")
        if not isinstance(a["requires_host_confirmation"], bool):
            raise ConfigError("requires_host_confirmation must be true or false")
        actions[aid] = Action(
            aid, kind, hazard, min_priority, recipient, tuple(data),
            _int(a["countdown_s"], "countdown_s", 0, 600),
            _int(a["retry_limit"], "retry_limit", 0, 5),
            a["requires_host_confirmation"],
            _int(a["expires_after_s"], "expires_after_s", 1, 86_400),
        )

    cancel = _obj(cfg["cancellation"], "cancellation", {"method", "recovery"})
    return TrustedConfig(
        policy_version=_text(cfg["policy_version"], "policy_version"),
        approved_at=approved_at,
        approved_by=_text(cfg["approved_by"], "approved_by"),
        devices=devices,
        sensor_scopes=tuple(scopes),
        external_services=tuple(services),
        contacts=contacts,
        actions=actions,
        shared_data_fields=frozenset(shared),
        consent_expires_at=consent_expires,
        cancellation_method=_choice(cancel["method"], "cancellation.method", CANCEL_METHODS),
        recovery=_text(cancel["recovery"], "cancellation.recovery"),
    )


def verify_envelope(envelope: Any, key: bytes) -> TrustedConfig:
    """Authenticate first, then validate. Fails closed on any problem."""
    env = _obj(envelope, "envelope", {"config", "kid", "tag"})
    if not isinstance(env["tag"], str) or not isinstance(env["kid"], str):
        raise ConfigError("envelope tag and kid must be strings")
    if not hmac.compare_digest(env["kid"], key_id(key)):
        raise ConfigError("configuration was signed with a different key")
    expected = hmac.new(key, canonical(env["config"]), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(env["tag"], expected):
        raise ConfigError("configuration authentication failed (tag mismatch)")
    return validate(env["config"])


def load_config(path: str, key: bytes) -> TrustedConfig:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            envelope = json.load(fh)
    except (OSError, ValueError) as exc:
        raise ConfigError(f"cannot read configuration: {exc.__class__.__name__}") from None
    return verify_envelope(envelope, key)
