"""Minimal tamper-evident audit records (SPEC section 12).

Each record is chained to the previous one by SHA-256 (or HMAC-SHA256 when a
key is given). Location, raw media and recipient identifiers are refused, so
they cannot reach the log by accident. A hash chain detects edits, deletions
and reordering inside the log; it cannot detect removal of the newest records
or replacement of the whole log. With a key, only the key holder can extend
or rewrite the chain consistently.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from .errors import AuditError

GENESIS = "0" * 64
FORBIDDEN_KEYS = {
    "location", "latitude", "longitude", "lat", "lon", "coordinates", "address",
    "raw_audio", "raw_image", "raw_video", "raw_media", "recipient_ref", "phone_number", "email",
}


def _canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def _check_keys(obj: Any, path: str = "data") -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).lower() in FORBIDDEN_KEYS:
                raise AuditError(f"{path}.{k} is not allowed in the audit log")
            _check_keys(v, f"{path}.{k}")
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            _check_keys(v, f"{path}[{i}]")


class AuditLog:
    def __init__(self, key: bytes | None = None) -> None:
        self._key = key
        self.records: list[dict] = []

    def _tag(self, body: dict) -> str:
        data = _canonical(body)
        if self._key is not None:
            return hmac.new(self._key, data, hashlib.sha256).hexdigest()
        return hashlib.sha256(data).hexdigest()

    def record(self, rtype: str, data: dict, now: float) -> dict:
        _check_keys(data)
        body = {"seq": len(self.records), "ts": now, "type": rtype, "data": data,
                "prev": self.records[-1]["tag"] if self.records else GENESIS}
        rec = dict(body, tag=self._tag(body))
        self.records.append(rec)
        return rec

    def verify(self) -> None:
        prev = GENESIS
        for i, rec in enumerate(self.records):
            body = {k: rec[k] for k in ("seq", "ts", "type", "data", "prev")}
            if rec["seq"] != i or rec["prev"] != prev:
                raise AuditError(f"record {i}: sequence or chain link broken")
            if not hmac.compare_digest(rec["tag"], self._tag(body)):
                raise AuditError(f"record {i}: tag mismatch")
            prev = rec["tag"]
