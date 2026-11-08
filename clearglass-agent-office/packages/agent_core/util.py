"""Clock and identifier helpers. Both are injectable so tests and demos are deterministic."""

from __future__ import annotations

import itertools
import secrets
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta


class Clock:
    """Real UTC clock."""

    def now(self) -> datetime:
        return datetime.now(UTC)

    def iso(self) -> str:
        return self.now().isoformat(timespec="seconds")


class SteppingClock(Clock):
    """Deterministic clock: starts at ``start`` and advances ``step`` per call."""

    def __init__(self, start: datetime, step: timedelta = timedelta(seconds=1)) -> None:
        self._t = start
        self._step = step
        self._lock = threading.Lock()

    def now(self) -> datetime:
        with self._lock:
            t = self._t
            self._t = t + self._step
            return t

    def advance(self, delta: timedelta) -> None:
        with self._lock:
            self._t += delta


def parse_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


IdFactory = Callable[[str], str]


def random_ids(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(6)}"


def sequential_ids() -> IdFactory:
    counter = itertools.count(1)
    lock = threading.Lock()

    def make(prefix: str) -> str:
        with lock:
            return f"{prefix}_{next(counter):04d}"

    return make
