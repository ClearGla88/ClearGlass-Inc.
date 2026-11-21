"""Append-only, hash-chained audit ledger.

Every material event (policy decision, tool call, approval, emergency stop,
configuration change) is appended as one row. Each row's hash covers its own
fields plus the previous row's hash, so editing or deleting any past row breaks
every link after it, and ``verify()`` reports the first broken sequence number.

Immutability is enforced twice: by the hash chain, and by SQLite triggers that
abort any UPDATE or DELETE on the table. The PostgreSQL schema in
``infra/db/postgres/001_init.sql`` carries the same triggers.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from audit_ledger.canonical import GENESIS_HASH, canonical_json, redact, sha256_hex

SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_events (
    seq            INTEGER PRIMARY KEY,
    event_id       TEXT NOT NULL UNIQUE,
    ts             TEXT NOT NULL,
    actor          TEXT NOT NULL,
    actor_type     TEXT NOT NULL CHECK (actor_type IN ('agent','human','system')),
    event_type     TEXT NOT NULL,
    subject        TEXT NOT NULL,
    payload        TEXT NOT NULL,
    risk_tier      TEXT,
    policy_version TEXT,
    prev_hash      TEXT NOT NULL,
    hash           TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS audit_events_subject ON audit_events(subject);
CREATE INDEX IF NOT EXISTS audit_events_type ON audit_events(event_type);
CREATE TRIGGER IF NOT EXISTS audit_events_no_update BEFORE UPDATE ON audit_events
BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_events_no_delete BEFORE DELETE ON audit_events
BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;
"""

HASHED_FIELDS = (
    "seq",
    "event_id",
    "ts",
    "actor",
    "actor_type",
    "event_type",
    "subject",
    "payload",
    "risk_tier",
    "policy_version",
    "prev_hash",
)


def _utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def compute_hash(row: dict[str, Any]) -> str:
    return sha256_hex(canonical_json({k: row[k] for k in HASHED_FIELDS}))


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    count: int
    head: str
    broken_at: int | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "count": self.count,
            "head": self.head,
            "broken_at": self.broken_at,
            "reason": self.reason,
        }


class AuditLedger:
    """Thread-safe ledger over a SQLite connection (shared with the store, or its own)."""

    def __init__(
        self,
        conn: sqlite3.Connection | None = None,
        *,
        clock: Callable[[], str] = _utcnow,
        lock: threading.RLock | None = None,
    ) -> None:
        self._conn = conn or sqlite3.connect(":memory:", check_same_thread=False)
        self._clock = clock
        self._lock = lock or threading.RLock()
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    # -- writes ---------------------------------------------------------------

    def append(
        self,
        *,
        actor: str,
        actor_type: str,
        event_type: str,
        subject: str,
        payload: dict[str, Any] | None = None,
        risk_tier: str | None = None,
        policy_version: str | None = None,
    ) -> dict[str, Any]:
        clean, hits = redact(payload or {})
        if hits:
            clean = {**clean, "_redacted_rules": hits}
        with self._lock:
            prev = self._conn.execute("SELECT seq, hash FROM audit_events ORDER BY seq DESC LIMIT 1").fetchone()
            seq = (prev[0] + 1) if prev else 1
            row = {
                "seq": seq,
                "event_id": f"evt_{uuid.uuid4().hex[:16]}",
                "ts": self._clock(),
                "actor": actor,
                "actor_type": actor_type,
                "event_type": event_type,
                "subject": subject,
                "payload": canonical_json(clean),
                "risk_tier": risk_tier,
                "policy_version": policy_version,
                "prev_hash": prev[1] if prev else GENESIS_HASH,
            }
            row["hash"] = compute_hash(row)
            self._conn.execute(
                "INSERT INTO audit_events (seq, event_id, ts, actor, actor_type, event_type, subject,"
                " payload, risk_tier, policy_version, prev_hash, hash)"
                " VALUES (:seq, :event_id, :ts, :actor, :actor_type, :event_type, :subject,"
                " :payload, :risk_tier, :policy_version, :prev_hash, :hash)",
                row,
            )
            self._conn.commit()
        return self._decode(row)

    # -- reads ----------------------------------------------------------------

    def events(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        subject: str | None = None,
        event_type: str | None = None,
        newest_first: bool = True,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 1000))
        clauses, args = [], []
        if subject:
            clauses.append("subject = ?")
            args.append(subject)
        if event_type:
            clauses.append("event_type = ?")
            args.append(event_type)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        order = "DESC" if newest_first else "ASC"
        with self._lock:
            cur = self._conn.execute(
                f"SELECT {', '.join(HASHED_FIELDS)}, hash FROM audit_events {where}"
                f" ORDER BY seq {order} LIMIT ? OFFSET ?",
                [*args, limit, max(0, int(offset))],
            )
            cols = [d[0] for d in cur.description]
            return [self._decode(dict(zip(cols, r, strict=True))) for r in cur.fetchall()]

    def count(self, event_type: str | None = None) -> int:
        with self._lock:
            if event_type:
                return self._conn.execute(
                    "SELECT COUNT(*) FROM audit_events WHERE event_type = ?", (event_type,)
                ).fetchone()[0]
            return self._conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]

    def head(self) -> str:
        with self._lock:
            row = self._conn.execute("SELECT hash FROM audit_events ORDER BY seq DESC LIMIT 1").fetchone()
        return row[0] if row else GENESIS_HASH

    def verify(self) -> VerifyResult:
        """Replay the whole chain. O(n); fine for the MVP's volumes."""
        prev_hash = GENESIS_HASH
        expected_seq = 1
        count = 0
        with self._lock:
            cur = self._conn.execute(f"SELECT {', '.join(HASHED_FIELDS)}, hash FROM audit_events ORDER BY seq ASC")
            cols = [d[0] for d in cur.description]
            for raw in cur:
                row = dict(zip(cols, raw, strict=True))
                if row["seq"] != expected_seq:
                    return VerifyResult(False, count, prev_hash, row["seq"], "sequence gap")
                if row["prev_hash"] != prev_hash:
                    return VerifyResult(False, count, prev_hash, row["seq"], "prev_hash mismatch")
                if compute_hash(row) != row["hash"]:
                    return VerifyResult(False, count, prev_hash, row["seq"], "hash mismatch")
                prev_hash = row["hash"]
                expected_seq += 1
                count += 1
        return VerifyResult(True, count, prev_hash)

    @staticmethod
    def _decode(row: dict[str, Any]) -> dict[str, Any]:
        out = dict(row)
        out["payload"] = json.loads(out["payload"]) if isinstance(out["payload"], str) else out["payload"]
        return out
