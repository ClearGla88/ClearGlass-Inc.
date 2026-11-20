"""Shared helpers: clock, timestamps, hashing, canonical JSON, identifiers."""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any


class Clock:
    """Wall clock. Tests pass a FixedClock so every time-dependent check is deterministic."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedClock(Clock):
    def __init__(self, start: datetime) -> None:
        if start.tzinfo is None:
            raise ValueError("FixedClock needs a timezone-aware datetime")
        self._now = start.astimezone(UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


def iso(dt: datetime) -> str:
    """Fixed-width UTC timestamp. Fixed width keeps string comparison in SQL chronological."""
    if dt.tzinfo is None:
        raise ValueError("refusing a naive datetime")
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timestamp has no timezone")
    return dt.astimezone(UTC)


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def new_id(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(8)}"
