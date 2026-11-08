"""SQLite persistence for the MVP.

Records are stored as JSON documents keyed by (kind, id). There is deliberately
no delete method: agents are retired, missions cancelled, approvals expired, and
every one of those transitions is audited. Approval decisions live in their own
append-only table with triggers that abort UPDATE and DELETE.

The normalized production schema is ``infra/db/postgres/001_init.sql``. The
document store keeps the MVP dependency-free; the PostgreSQL adapter is on the
roadmap (docs/ROADMAP.md, week 2).
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, TypeVar

from agent_core.models import Record

R = TypeVar("R", bound=Record)

SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    kind       TEXT NOT NULL,
    id         TEXT NOT NULL,
    data       TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (kind, id)
);
CREATE INDEX IF NOT EXISTS records_kind_updated ON records(kind, updated_at);

CREATE TABLE IF NOT EXISTS approval_decisions (
    seq              INTEGER PRIMARY KEY AUTOINCREMENT,
    approval_id      TEXT NOT NULL,
    decision         TEXT NOT NULL,
    reason           TEXT NOT NULL,
    decided_by       TEXT NOT NULL,
    decided_at       TEXT NOT NULL,
    modifications    TEXT,
    resulting_digest TEXT
);
CREATE INDEX IF NOT EXISTS approval_decisions_approval ON approval_decisions(approval_id);
CREATE TRIGGER IF NOT EXISTS approval_decisions_no_update BEFORE UPDATE ON approval_decisions
BEGIN SELECT RAISE(ABORT, 'approval_decisions is append-only'); END;
CREATE TRIGGER IF NOT EXISTS approval_decisions_no_delete BEFORE DELETE ON approval_decisions
BEGIN SELECT RAISE(ABORT, 'approval_decisions is append-only'); END;

CREATE TABLE IF NOT EXISTS office_state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class Store:
    def __init__(self, path: str | Path = ":memory:") -> None:
        path = str(path)
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False, timeout=10)
        if path != ":memory:":
            self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # -- records --------------------------------------------------------------

    def put(self, record: Record, now: str) -> None:
        data = json.dumps(record.to_dict(), sort_keys=True, default=str)
        rid = getattr(record, "id", None) or str(record.seq)
        with self.lock:
            self.conn.execute(
                "INSERT INTO records (kind, id, data, created_at, updated_at) VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT(kind, id) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at",
                (record.KIND, rid, data, now, now),
            )
            self.conn.commit()

    def get(self, cls: type[R], rid: str) -> R | None:
        with self.lock:
            row = self.conn.execute("SELECT data FROM records WHERE kind = ? AND id = ?", (cls.KIND, rid)).fetchone()
        return cls.from_dict(json.loads(row[0])) if row else None

    def list(
        self,
        cls: type[R],
        where: Callable[[R], bool] | None = None,
        *,
        newest_first: bool = False,
    ) -> list[R]:
        order = "DESC" if newest_first else "ASC"
        with self.lock:
            rows = self.conn.execute(
                f"SELECT data FROM records WHERE kind = ? ORDER BY created_at {order}, id {order}",
                (cls.KIND,),
            ).fetchall()
        items = [cls.from_dict(json.loads(r[0])) for r in rows]
        return [i for i in items if where(i)] if where else items

    def count(self, cls: type[Record]) -> int:
        with self.lock:
            return self.conn.execute("SELECT COUNT(*) FROM records WHERE kind = ?", (cls.KIND,)).fetchone()[0]

    # -- approval decision history (append-only) --------------------------------

    def append_decision(
        self,
        *,
        approval_id: str,
        decision: str,
        reason: str,
        decided_by: str,
        decided_at: str,
        modifications: dict[str, Any] | None,
        resulting_digest: str | None,
    ) -> None:
        with self.lock:
            self.conn.execute(
                "INSERT INTO approval_decisions (approval_id, decision, reason, decided_by, decided_at,"
                " modifications, resulting_digest) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    approval_id,
                    decision,
                    reason,
                    decided_by,
                    decided_at,
                    json.dumps(modifications, sort_keys=True) if modifications is not None else None,
                    resulting_digest,
                ),
            )
            self.conn.commit()

    def decisions_for(self, approval_ids: Iterable[str]) -> dict[str, list[dict[str, Any]]]:
        ids = list(approval_ids)
        out: dict[str, list[dict[str, Any]]] = {i: [] for i in ids}
        if not ids:
            return out
        marks = ",".join("?" for _ in ids)
        with self.lock:
            rows = self.conn.execute(
                "SELECT approval_id, seq, decision, reason, decided_by, decided_at, modifications,"
                f" resulting_digest FROM approval_decisions WHERE approval_id IN ({marks}) ORDER BY seq",
                ids,
            ).fetchall()
        for aid, seq, decision, reason, by, at, mods, dig in rows:
            out[aid].append(
                {
                    "seq": seq,
                    "decision": decision,
                    "reason": reason,
                    "decided_by": by,
                    "decided_at": at,
                    "modifications": json.loads(mods) if mods else None,
                    "resulting_digest": dig,
                }
            )
        return out

    # -- office state -------------------------------------------------------------

    def get_state(self, key: str, default: Any = None) -> Any:
        with self.lock:
            row = self.conn.execute("SELECT value FROM office_state WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_state(self, key: str, value: Any) -> None:
        with self.lock:
            self.conn.execute(
                "INSERT INTO office_state (key, value) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(value, sort_keys=True, default=str)),
            )
            self.conn.commit()

    def ping(self) -> bool:
        with self.lock:
            return self.conn.execute("SELECT 1").fetchone() == (1,)

    def close(self) -> None:
        with self.lock:
            self.conn.close()
