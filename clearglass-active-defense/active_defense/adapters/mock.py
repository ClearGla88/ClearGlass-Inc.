"""Mock network-isolation adapter.

It keeps its own SQLite file, standing in for a firewall or EDR console whose
state outlives the controller. That separation is what makes the reconciliation
and restart tests meaningful: after a crash the controller asks the "device"
what is actually applied.

It changes nothing outside that file. It supports fault injection (error,
partial, timeout after applying, timeout without applying) for tests.

Ordering rule it demonstrates: management allow rules go in before any deny
rule, so a partial apply never cuts the management path.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .base import AdapterResult

_DDL = """
CREATE TABLE IF NOT EXISTS rules (
  rule_id INTEGER PRIMARY KEY AUTOINCREMENT, asset_id TEXT NOT NULL, owner_key TEXT NOT NULL,
  step TEXT NOT NULL, created_at REAL NOT NULL, UNIQUE (asset_id, owner_key, step)
);
CREATE TABLE IF NOT EXISTS faults (
  asset_id TEXT NOT NULL, op TEXT NOT NULL, mode TEXT NOT NULL, remaining INTEGER NOT NULL,
  hang_seconds REAL NOT NULL, PRIMARY KEY (asset_id, op)
);
CREATE TABLE IF NOT EXISTS calls (
  id INTEGER PRIMARY KEY AUTOINCREMENT, op TEXT NOT NULL, asset_id TEXT NOT NULL, owner_key TEXT NOT NULL,
  at REAL NOT NULL
);
"""
BASELINE_KEY = "baseline-policy"
FAULT_MODES = ("error", "partial", "timeout", "timeout_noop")


class MockNetworkAdapter:
    name = "mock"

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(_DDL)
            if c.execute("SELECT COUNT(*) FROM rules WHERE owner_key=?", (BASELINE_KEY,)).fetchone()[0] == 0:
                for step in ("allow_dns_to_resolvers", "allow_ntp", "deny_smb_from_guest_vlan"):
                    c.execute(
                        "INSERT INTO rules (asset_id, owner_key, step, created_at) VALUES ('*', ?, ?, ?)",
                        (BASELINE_KEY, step, time.time()),
                    )

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10.0, isolation_level=None)
        try:
            conn.execute("PRAGMA busy_timeout=10000")
            yield conn
        finally:
            conn.close()

    # ---------------------------------------------------------------- test hooks

    def inject_fault(self, asset_id: str, op: str, mode: str, *, times: int = 1, hang_seconds: float = 0.5) -> None:
        if mode not in FAULT_MODES or op not in ("apply", "release"):
            raise ValueError("unknown fault")
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO faults (asset_id, op, mode, remaining, hang_seconds) VALUES (?,?,?,?,?)",
                (asset_id, op, mode, times, hang_seconds),
            )

    def _take_fault(self, c: sqlite3.Connection, asset_id: str, op: str) -> tuple[str, float] | None:
        row = c.execute(
            "SELECT mode, remaining, hang_seconds FROM faults WHERE asset_id=? AND op=?", (asset_id, op)
        ).fetchone()
        if row is None or row[1] <= 0:
            return None
        c.execute("UPDATE faults SET remaining=remaining-1 WHERE asset_id=? AND op=?", (asset_id, op))
        return row[0], row[2]

    def call_count(self, op: str, asset_id: str) -> int:
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM calls WHERE op=? AND asset_id=?", (op, asset_id)).fetchone()[0]

    def baseline_rules(self) -> int:
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM rules WHERE owner_key=?", (BASELINE_KEY,)).fetchone()[0]

    def all_rules(self) -> list[tuple[str, str, str]]:
        with self._conn() as c:
            return [tuple(r) for r in c.execute("SELECT asset_id, owner_key, step FROM rules ORDER BY rule_id")]

    # ---------------------------------------------------------------- contract

    def _insert(self, c: sqlite3.Connection, asset_id: str, key: str, step: str) -> None:
        c.execute(
            "INSERT OR IGNORE INTO rules (asset_id, owner_key, step, created_at) VALUES (?,?,?,?)",
            (asset_id, key, step, time.time()),
        )

    def apply_isolation(self, asset_id: str, key: str, steps: list[str], preserve: list[str]) -> AdapterResult:
        if key == BASELINE_KEY:
            raise ValueError("reserved key")
        with self._conn() as c:
            c.execute(
                "INSERT INTO calls (op, asset_id, owner_key, at) VALUES ('apply', ?, ?, ?)", (asset_id, key, time.time())
            )
            fault = self._take_fault(c, asset_id, "apply")
            mode, hang = fault if fault else (None, 0.0)
            if mode == "error":
                return AdapterResult("error", detail="injected adapter error")
            if mode == "timeout_noop":
                time.sleep(hang)
                return AdapterResult("error", detail="injected hang without applying")
            allow = [f"allow_management:{p}" for p in preserve]
            for step in allow:
                self._insert(c, asset_id, key, step)
            deny = steps[:1] if mode == "partial" else steps
            for step in deny:
                self._insert(c, asset_id, key, step)
            if mode == "partial":
                return AdapterResult("partial", tuple(allow + deny), "injected partial apply")
        if mode == "timeout":
            time.sleep(hang)
        return AdapterResult("applied", tuple(allow + list(steps)))

    def release_isolation(self, asset_id: str, key: str) -> AdapterResult:
        if key == BASELINE_KEY:
            raise ValueError("reserved key")
        with self._conn() as c:
            c.execute(
                "INSERT INTO calls (op, asset_id, owner_key, at) VALUES ('release', ?, ?, ?)",
                (asset_id, key, time.time()),
            )
            fault = self._take_fault(c, asset_id, "release")
            mode, hang = fault if fault else (None, 0.0)
            if mode == "error":
                return AdapterResult("error", detail="injected adapter error")
            if mode == "timeout_noop":
                time.sleep(hang)
                return AdapterResult("error", detail="injected hang without releasing")
            # Only rules this action created. Never a flush, never another owner's rule.
            c.execute("DELETE FROM rules WHERE asset_id=? AND owner_key=?", (asset_id, key))
        if mode == "timeout":
            time.sleep(hang)
        return AdapterResult("applied", (), "released rules owned by this key")

    def state(self, asset_id: str, key: str) -> set[str]:
        with self._conn() as c:
            return {
                r[0] for r in c.execute("SELECT step FROM rules WHERE asset_id=? AND owner_key=?", (asset_id, key))
            }

    def verify_isolation(self, asset_id: str, key: str, steps: list[str], preserve: list[str]) -> tuple[bool, str]:
        present = self.state(asset_id, key)
        required = set(steps) | {f"allow_management:{p}" for p in preserve}
        missing = sorted(required - present)
        if missing:
            return False, f"missing {missing}"
        return True, f"{len(required)} rules present, management paths preserved: {sorted(preserve)}"

    def verify_released(self, asset_id: str, key: str) -> tuple[bool, str]:
        left = sorted(self.state(asset_id, key))
        return (not left, "no rules remain for this key" if not left else f"rules remain: {left}")
