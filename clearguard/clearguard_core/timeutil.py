"""Timestamps: ISO 8601 with an explicit UTC offset, compared in UTC."""

from __future__ import annotations

from datetime import datetime, timezone


def parse_time(value: object) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timestamp must be an ISO 8601 string")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp {value!r} has no UTC offset")
    return parsed.astimezone(timezone.utc)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


def clock(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%H:%M:%S UTC")
