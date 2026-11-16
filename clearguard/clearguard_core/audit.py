"""Minimal tamper-evident audit trail (spec section 12).

Each record holds the SHA-256 of the previous one, so editing or removing a
past record breaks every later link. Records refuse location and raw-media
fields. This makes changes detectable, not impossible: anyone who can rewrite
the whole file can rebuild the chain.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime

GENESIS = "0" * 64
FORBIDDEN_KEYS = {
    "lat", "lon", "lng", "latitude", "longitude", "location", "coarse_location", "precise_location",
    "audio", "image", "video", "frame", "raw", "raw_media", "transcript", "recording",
}


def _forbidden(node: object, path: str = "") -> str | None:
    if isinstance(node, dict):
        for key, value in node.items():
            if str(key).lower() in FORBIDDEN_KEYS:
                return f"{path}{key}"
            hit = _forbidden(value, f"{path}{key}.")
            if hit:
                return hit
    elif isinstance(node, list):
        for i, value in enumerate(node):
            hit = _forbidden(value, f"{path}{i}.")
            if hit:
                return hit
    return None


def _digest(record: dict) -> str:
    body = {k: v for k, v in record.items() if k != "hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class AuditLog:
    """Append-only. With ``path`` the records are also written as JSON lines."""

    def __init__(self, path: str | None = None):
        self.path = path
        self.records: list[dict] = []
        if path and os.path.exists(path):
            with open(path, encoding="utf-8") as handle:
                self.records = [json.loads(line) for line in handle if line.strip()]

    def append(self, kind: str, payload: dict, at: datetime) -> dict:
        hit = _forbidden(payload)
        if hit:
            raise ValueError(f"audit records may not contain location or raw media (field '{hit}')")
        record = {
            "seq": len(self.records),
            "at": at.isoformat(),
            "kind": kind,
            "payload": payload,
            "prev": self.records[-1]["hash"] if self.records else GENESIS,
        }
        record["hash"] = _digest(record)
        self.records.append(record)
        if self.path:
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")
        return record


def verify(records: list[dict]) -> list[str]:
    problems: list[str] = []
    prev = GENESIS
    for i, record in enumerate(records):
        if record.get("seq") != i:
            problems.append(f"record {i}: sequence number {record.get('seq')!r}")
        if record.get("prev") != prev:
            problems.append(f"record {i}: does not link to the previous record")
        if record.get("hash") != _digest(record):
            problems.append(f"record {i}: content does not match its hash")
        prev = record.get("hash")
    return problems
