"""SQLite persistence for the MVP.

Records are stored as JSON documents keyed by (kind, id). There is deliberately
no delete method: agents are retired, missions cancelled, approvals expired, and
every one of those transitions is audited.

Approval integrity does not rest on the JSON documents. Three tables carry it,
and the database itself refuses to break their rules:

- ``approval_requests``: the original request (payload + digest), append-only.
- ``approval_decisions``: append-only, and a unique partial index allows one
  approve/reject/modify decision per approval (cancellations are extra rows).
- ``approval_executions``: one row per executed approval (primary key), append-only.

``idempotency_keys`` maps a caller's key to the request digest and its result,
so a retried request replays the stored result instead of acting twice.

The Revenue Floor adds four append-only tables with the same guarantees:

- ``revenue_offer_decisions``: each operator decision on an offer, with the digest
  of the exact content it approved.
- ``revenue_suppressions``: addresses and domains no message may be sent to.
- ``revenue_money_events``: every fact about money. A unique index on
  (provider, record type, external reference, kind) makes importing the same
  provider record twice a no-op instead of a double count.
- ``revenue_receipts``: one row per external reference a person recorded after
  executing a released ticket, so one message or invoice id cannot be claimed twice.

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

from agent_core.models import MoneyEvent, OfferDecision, Record, Suppression

R = TypeVar("R", bound=Record)

REVENUE_SCHEMA = """
CREATE TABLE IF NOT EXISTS revenue_offer_decisions (
    seq          INTEGER PRIMARY KEY AUTOINCREMENT,
    sku          TEXT NOT NULL,
    decision     TEXT NOT NULL CHECK (decision IN ('approve', 'reject', 'retire')),
    offer        TEXT NOT NULL,
    offer_digest TEXT NOT NULL,
    reason       TEXT NOT NULL,
    decided_by   TEXT NOT NULL,
    decided_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS revenue_offer_decisions_sku ON revenue_offer_decisions(sku);

CREATE TABLE IF NOT EXISTS revenue_suppressions (
    seq         INTEGER PRIMARY KEY AUTOINCREMENT,
    address     TEXT NOT NULL,
    reason      TEXT NOT NULL,
    source_ref  TEXT NOT NULL,
    recorded_by TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS revenue_suppressions_address ON revenue_suppressions(address);

CREATE TABLE IF NOT EXISTS revenue_money_events (
    seq             INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id        TEXT NOT NULL UNIQUE,
    opportunity_id  TEXT NOT NULL,
    kind            TEXT NOT NULL,
    amount_cents    INTEGER NOT NULL CHECK (amount_cents >= 0),
    currency        TEXT NOT NULL,
    provider        TEXT NOT NULL,
    record_type     TEXT NOT NULL,
    external_ref    TEXT NOT NULL CHECK (length(external_ref) > 0),
    provider_status TEXT NOT NULL,
    verification    TEXT NOT NULL,
    evidence        TEXT NOT NULL,
    raw_digest      TEXT,
    rehearsal       INTEGER NOT NULL,
    occurred_at     TEXT NOT NULL,
    recorded_by     TEXT NOT NULL,
    recorded_at     TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS revenue_money_events_once
    ON revenue_money_events(provider, record_type, external_ref, kind);
CREATE INDEX IF NOT EXISTS revenue_money_events_opportunity ON revenue_money_events(opportunity_id);

CREATE TABLE IF NOT EXISTS revenue_receipts (
    connector    TEXT NOT NULL,
    external_ref TEXT NOT NULL,
    action_id    TEXT NOT NULL,
    recorded_at  TEXT NOT NULL,
    PRIMARY KEY (connector, external_ref)
);
"""

for _t in ("revenue_offer_decisions", "revenue_suppressions", "revenue_money_events", "revenue_receipts"):
    REVENUE_SCHEMA += (
        f"CREATE TRIGGER IF NOT EXISTS {_t}_no_update BEFORE UPDATE ON {_t}"
        f" BEGIN SELECT RAISE(ABORT, '{_t} is append-only'); END;\n"
        f"CREATE TRIGGER IF NOT EXISTS {_t}_no_delete BEFORE DELETE ON {_t}"
        f" BEGIN SELECT RAISE(ABORT, '{_t} is append-only'); END;\n"
    )

MONEY_COLUMNS = (
    "seq",
    "event_id",
    "opportunity_id",
    "kind",
    "amount_cents",
    "currency",
    "provider",
    "record_type",
    "external_ref",
    "provider_status",
    "verification",
    "evidence",
    "raw_digest",
    "rehearsal",
    "occurred_at",
    "recorded_by",
    "recorded_at",
)

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

CREATE UNIQUE INDEX IF NOT EXISTS approval_decisions_once
    ON approval_decisions(approval_id) WHERE decision IN ('approve', 'reject', 'modify');

CREATE TABLE IF NOT EXISTS approval_requests (
    approval_id    TEXT PRIMARY KEY,
    action_digest  TEXT NOT NULL,
    action         TEXT NOT NULL,
    requested_by   TEXT NOT NULL,
    risk_tier      TEXT NOT NULL,
    requested_at   TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS approval_requests_no_update BEFORE UPDATE ON approval_requests
BEGIN SELECT RAISE(ABORT, 'approval_requests is append-only'); END;
CREATE TRIGGER IF NOT EXISTS approval_requests_no_delete BEFORE DELETE ON approval_requests
BEGIN SELECT RAISE(ABORT, 'approval_requests is append-only'); END;

CREATE TABLE IF NOT EXISTS approval_executions (
    approval_id     TEXT PRIMARY KEY,
    executed_digest TEXT NOT NULL,
    executed_at     TEXT NOT NULL,
    task_id         TEXT
);
CREATE TRIGGER IF NOT EXISTS approval_executions_no_update BEFORE UPDATE ON approval_executions
BEGIN SELECT RAISE(ABORT, 'approval_executions is append-only'); END;
CREATE TRIGGER IF NOT EXISTS approval_executions_no_delete BEFORE DELETE ON approval_executions
BEGIN SELECT RAISE(ABORT, 'approval_executions is append-only'); END;

CREATE TABLE IF NOT EXISTS idempotency_keys (
    key            TEXT PRIMARY KEY,
    request_digest TEXT NOT NULL,
    status         TEXT NOT NULL CHECK (status IN ('in_progress', 'completed', 'failed')),
    result         TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

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
        self.conn.executescript(REVENUE_SCHEMA)
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

    # -- approval request and execution records (append-only) ----------------------

    def record_approval_request(
        self,
        *,
        approval_id: str,
        action_digest: str,
        action: dict[str, Any],
        requested_by: str,
        risk_tier: str,
        requested_at: str,
    ) -> None:
        with self.lock:
            self.conn.execute(
                "INSERT INTO approval_requests (approval_id, action_digest, action, requested_by, risk_tier,"
                " requested_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    approval_id,
                    action_digest,
                    json.dumps(action, sort_keys=True, default=str),
                    requested_by,
                    risk_tier,
                    requested_at,
                ),
            )
            self.conn.commit()

    def approval_request(self, approval_id: str) -> dict[str, Any] | None:
        with self.lock:
            row = self.conn.execute(
                "SELECT action_digest, action, requested_by, risk_tier, requested_at FROM approval_requests"
                " WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "action_digest": row[0],
            "action": json.loads(row[1]),
            "requested_by": row[2],
            "risk_tier": row[3],
            "requested_at": row[4],
        }

    def record_execution(
        self, *, approval_id: str, executed_digest: str, executed_at: str, task_id: str | None
    ) -> None:
        """Raises sqlite3.IntegrityError if the approval was already used."""
        with self.lock:
            self.conn.execute(
                "INSERT INTO approval_executions (approval_id, executed_digest, executed_at, task_id)"
                " VALUES (?, ?, ?, ?)",
                (approval_id, executed_digest, executed_at, task_id),
            )
            self.conn.commit()

    def execution_of(self, approval_id: str) -> dict[str, Any] | None:
        with self.lock:
            row = self.conn.execute(
                "SELECT executed_digest, executed_at, task_id FROM approval_executions WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
        return {"executed_digest": row[0], "executed_at": row[1], "task_id": row[2]} if row else None

    # -- idempotency ------------------------------------------------------------------

    def idempotency_get(self, key: str) -> dict[str, Any] | None:
        with self.lock:
            row = self.conn.execute(
                "SELECT request_digest, status, result FROM idempotency_keys WHERE key = ?", (key,)
            ).fetchone()
        if row is None:
            return None
        return {"request_digest": row[0], "status": row[1], "result": json.loads(row[2]) if row[2] else None}

    def idempotency_claim(self, key: str, request_digest: str, now: str) -> bool:
        """Mark a key in progress. False if another request holds it in progress or already completed it."""
        with self.lock:
            existing = self.conn.execute("SELECT status FROM idempotency_keys WHERE key = ?", (key,)).fetchone()
            if existing is None:
                self.conn.execute(
                    "INSERT INTO idempotency_keys (key, request_digest, status, result, created_at, updated_at)"
                    " VALUES (?, ?, 'in_progress', NULL, ?, ?)",
                    (key, request_digest, now, now),
                )
            elif existing[0] == "failed":
                self.conn.execute(
                    "UPDATE idempotency_keys SET status = 'in_progress', request_digest = ?, updated_at = ?"
                    " WHERE key = ?",
                    (request_digest, now, key),
                )
            else:
                return False
            self.conn.commit()
            return True

    def idempotency_finish(self, key: str, status: str, result: dict[str, Any] | None, now: str) -> None:
        with self.lock:
            self.conn.execute(
                "UPDATE idempotency_keys SET status = ?, result = ?, updated_at = ? WHERE key = ?",
                (status, json.dumps(result, sort_keys=True, default=str) if result is not None else None, now, key),
            )
            self.conn.commit()

    # -- revenue (append-only) -------------------------------------------------------

    def append_offer_decision(
        self,
        *,
        sku: str,
        decision: str,
        offer: dict[str, Any],
        offer_digest: str,
        reason: str,
        decided_by: str,
        decided_at: str,
    ) -> OfferDecision:
        with self.lock:
            cur = self.conn.execute(
                "INSERT INTO revenue_offer_decisions (sku, decision, offer, offer_digest, reason, decided_by,"
                " decided_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (sku, decision, json.dumps(offer, sort_keys=True), offer_digest, reason, decided_by, decided_at),
            )
            self.conn.commit()
            seq = int(cur.lastrowid or 0)
        return OfferDecision(seq, sku, decision, offer, offer_digest, reason, decided_by, decided_at)

    def offer_decisions(self, sku: str | None = None) -> list[OfferDecision]:
        sql = (
            "SELECT seq, sku, decision, offer, offer_digest, reason, decided_by, decided_at"
            " FROM revenue_offer_decisions"
        )
        args: tuple[Any, ...] = ()
        if sku is not None:
            sql, args = sql + " WHERE sku = ?", (sku,)
        with self.lock:
            rows = self.conn.execute(sql + " ORDER BY seq", args).fetchall()
        return [OfferDecision(r[0], r[1], r[2], json.loads(r[3]), r[4], r[5], r[6], r[7]) for r in rows]

    def append_suppression(
        self, *, address: str, reason: str, source_ref: str, recorded_by: str, recorded_at: str
    ) -> Suppression:
        with self.lock:
            cur = self.conn.execute(
                "INSERT INTO revenue_suppressions (address, reason, source_ref, recorded_by, recorded_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (address, reason, source_ref, recorded_by, recorded_at),
            )
            self.conn.commit()
            seq = int(cur.lastrowid or 0)
        return Suppression(seq, address, reason, source_ref, recorded_by, recorded_at)

    def suppressions(self) -> list[Suppression]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT seq, address, reason, source_ref, recorded_by, recorded_at FROM revenue_suppressions"
                " ORDER BY seq"
            ).fetchall()
        return [Suppression(*r) for r in rows]

    def append_money_event(self, event: MoneyEvent) -> tuple[MoneyEvent, bool]:
        """Insert one money fact. Returns (event, created); a duplicate provider record returns the stored one."""
        row = event.to_dict()
        cols = [c for c in MONEY_COLUMNS if c != "seq"]
        values = [int(row[c]) if c == "rehearsal" else row[c] for c in cols]
        with self.lock:
            try:
                cur = self.conn.execute(
                    f"INSERT INTO revenue_money_events ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
                    values,
                )
                self.conn.commit()
                event.seq = int(cur.lastrowid or 0)
                return event, True
            except sqlite3.IntegrityError:
                self.conn.rollback()
                existing = self.conn.execute(
                    f"SELECT {', '.join(MONEY_COLUMNS)} FROM revenue_money_events"
                    " WHERE provider = ? AND record_type = ? AND external_ref = ? AND kind = ?",
                    (event.provider, event.record_type, event.external_ref, event.kind),
                ).fetchone()
        if existing is None:
            raise sqlite3.IntegrityError("money event rejected by the database")
        return self._money(existing), False

    def money_events(self, opportunity_id: str | None = None) -> list[MoneyEvent]:
        sql = f"SELECT {', '.join(MONEY_COLUMNS)} FROM revenue_money_events"
        args: tuple[Any, ...] = ()
        if opportunity_id is not None:
            sql, args = sql + " WHERE opportunity_id = ?", (opportunity_id,)
        with self.lock:
            rows = self.conn.execute(sql + " ORDER BY seq", args).fetchall()
        return [self._money(r) for r in rows]

    @staticmethod
    def _money(row: Iterable[Any]) -> MoneyEvent:
        data = dict(zip(MONEY_COLUMNS, row, strict=True))
        data["rehearsal"] = bool(data["rehearsal"])
        return MoneyEvent(**data)

    def record_receipt(self, *, connector: str, external_ref: str, action_id: str, recorded_at: str) -> None:
        """Raises sqlite3.IntegrityError if the reference was already recorded for any action."""
        with self.lock:
            try:
                self.conn.execute(
                    "INSERT INTO revenue_receipts (connector, external_ref, action_id, recorded_at)"
                    " VALUES (?, ?, ?, ?)",
                    (connector, external_ref, action_id, recorded_at),
                )
                self.conn.commit()
            except sqlite3.IntegrityError:
                self.conn.rollback()
                raise

    def receipt_owner(self, connector: str, external_ref: str) -> str | None:
        with self.lock:
            row = self.conn.execute(
                "SELECT action_id FROM revenue_receipts WHERE connector = ? AND external_ref = ?",
                (connector, external_ref),
            ).fetchone()
        return row[0] if row else None

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
