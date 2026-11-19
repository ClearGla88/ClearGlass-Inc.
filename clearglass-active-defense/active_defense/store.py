"""SQLite operational store: cases, evidence, proposals, actions, controls, audit.

SQLite is the lightweight local option. Each process opens its own connection
per thread; writes run under BEGIN IMMEDIATE so they serialize. Database
triggers make the audit, approval, custody and transition tables append-only:
an UPDATE or DELETE on them aborts.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from .util import canonical_json, iso, sha256_hex

SCHEMA_VERSION = "1"
GENESIS = "0" * 64

DDL = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS events (
  event_pk INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT NOT NULL,
  schema_version TEXT NOT NULL,
  sensor_id TEXT NOT NULL,
  sensor_auth TEXT NOT NULL,
  sensor_trusted INTEGER NOT NULL,
  occurred_at TEXT NOT NULL,
  ingested_at TEXT NOT NULL,
  late INTEGER NOT NULL,
  category TEXT NOT NULL,
  severity TEXT NOT NULL,
  environment TEXT NOT NULL,
  authorization_scope TEXT NOT NULL,
  src_ip TEXT, src_port INTEGER, dst_ip TEXT, dst_port INTEGER,
  asserted_asset_id TEXT,
  subject TEXT NOT NULL,
  identity_status TEXT NOT NULL,
  identity_reason TEXT NOT NULL,
  verified_asset_id TEXT,
  attributes_json TEXT NOT NULL,
  derived_json TEXT NOT NULL,
  artifact_id TEXT NOT NULL,
  correlation_id TEXT NOT NULL,
  UNIQUE (sensor_id, event_id)
);

CREATE TABLE IF NOT EXISTS nonces (
  sensor_id TEXT NOT NULL, nonce TEXT NOT NULL, seen_at TEXT NOT NULL,
  PRIMARY KEY (sensor_id, nonce)
);

CREATE TABLE IF NOT EXISTS ingest_failures (
  id INTEGER PRIMARY KEY AUTOINCREMENT, sensor_id TEXT NOT NULL, at TEXT NOT NULL,
  code INTEGER NOT NULL, reason TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ingest_failures_sensor ON ingest_failures (sensor_id, at);

CREATE TABLE IF NOT EXISTS sensor_trust (
  sensor_id TEXT PRIMARY KEY, trusted INTEGER NOT NULL, reason TEXT NOT NULL,
  updated_at TEXT NOT NULL, updated_by TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS honeytokens (
  fingerprint TEXT PRIMARY KEY, token_id TEXT NOT NULL UNIQUE, label TEXT NOT NULL,
  placement TEXT NOT NULL, created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS artifacts (
  artifact_id TEXT PRIMARY KEY, sha256 TEXT NOT NULL, size INTEGER NOT NULL,
  media_type TEXT NOT NULL, content BLOB, collected_at TEXT NOT NULL,
  collector TEXT NOT NULL, received_by TEXT NOT NULL,
  legal_hold INTEGER NOT NULL DEFAULT 0, purged_at TEXT
);

CREATE TABLE IF NOT EXISTS custody (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, artifact_id TEXT NOT NULL, action TEXT NOT NULL,
  actor TEXT NOT NULL, at TEXT NOT NULL, note TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cases (
  case_id TEXT PRIMARY KEY, subject TEXT NOT NULL, state TEXT NOT NULL, severity TEXT NOT NULL,
  opened_at TEXT NOT NULL, updated_at TEXT NOT NULL, playbook_id TEXT, playbook_version INTEGER,
  escalated INTEGER NOT NULL DEFAULT 0, false_positive INTEGER NOT NULL DEFAULT 0, finding TEXT,
  review_due_at TEXT, review_overdue INTEGER NOT NULL DEFAULT 0, correlation_id TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS cases_subject ON cases (subject, state);

CREATE TABLE IF NOT EXISTS case_events (
  case_id TEXT NOT NULL, event_pk INTEGER NOT NULL, PRIMARY KEY (case_id, event_pk)
);

CREATE TABLE IF NOT EXISTS case_transitions (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL, from_state TEXT, to_state TEXT NOT NULL,
  at TEXT NOT NULL, actor TEXT NOT NULL, reason TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS signals (
  signal_id TEXT PRIMARY KEY, case_id TEXT NOT NULL, event_pk INTEGER NOT NULL, rule_id TEXT NOT NULL,
  rule_version INTEGER NOT NULL, signal TEXT NOT NULL, sensor_id TEXT NOT NULL, occurred_at TEXT NOT NULL,
  identity_asserting INTEGER NOT NULL, explanation TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS signals_case ON signals (case_id, occurred_at);

CREATE TABLE IF NOT EXISTS case_playbooks (
  case_id TEXT NOT NULL, playbook_id TEXT NOT NULL, playbook_version INTEGER NOT NULL,
  started_at TEXT NOT NULL, trigger TEXT NOT NULL, PRIMARY KEY (case_id, playbook_id)
);

CREATE TABLE IF NOT EXISTS case_correlations (
  case_id TEXT NOT NULL, correlation_id TEXT NOT NULL, correlation_version INTEGER NOT NULL,
  fired_at TEXT NOT NULL, signal_ids_json TEXT NOT NULL, PRIMARY KEY (case_id, correlation_id)
);

CREATE TABLE IF NOT EXISTS proposals (
  proposal_id TEXT PRIMARY KEY, case_id TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('isolate', 'release')),
  target_asset_id TEXT NOT NULL, playbook_id TEXT NOT NULL, playbook_version INTEGER NOT NULL,
  plan_json TEXT NOT NULL, plan_hash TEXT NOT NULL, policy_version TEXT NOT NULL,
  decision_json TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
  requested_by TEXT NOT NULL, decided_by TEXT, decided_at TEXT, decision_reason TEXT
);
CREATE INDEX IF NOT EXISTS proposals_case ON proposals (case_id, status);

CREATE TABLE IF NOT EXISTS approvals (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, proposal_id TEXT NOT NULL UNIQUE,
  decision TEXT NOT NULL CHECK (decision IN ('approved', 'rejected')),
  principal TEXT NOT NULL, plan_hash TEXT NOT NULL, policy_version TEXT NOT NULL,
  at TEXT NOT NULL, reason TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS actions (
  action_id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL UNIQUE, case_id TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('isolate', 'release')), target_asset_id TEXT NOT NULL,
  idempotency_key TEXT NOT NULL UNIQUE, plan_hash TEXT NOT NULL, status TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at TEXT, lease_owner TEXT, lease_expires TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, execute_by TEXT NOT NULL,
  last_error TEXT, result_json TEXT
);
CREATE INDEX IF NOT EXISTS actions_status ON actions (status, created_at);

CREATE TABLE IF NOT EXISTS containments (
  containment_id INTEGER PRIMARY KEY AUTOINCREMENT, target_asset_id TEXT NOT NULL,
  action_id TEXT NOT NULL, idempotency_key TEXT NOT NULL, case_id TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('active', 'released')), partial INTEGER NOT NULL DEFAULT 0,
  applied_at TEXT NOT NULL, released_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS containments_one_active
  ON containments (target_asset_id) WHERE state = 'active';

CREATE TABLE IF NOT EXISTS controls (
  key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TEXT NOT NULL, updated_by TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit (
  seq INTEGER PRIMARY KEY, at TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL,
  subject TEXT NOT NULL, details_json TEXT NOT NULL, prev_hash TEXT NOT NULL, hash TEXT NOT NULL
);
"""

APPEND_ONLY_TABLES = ("audit", "approvals", "custody", "case_transitions")


def _triggers() -> str:
    parts = []
    for table in APPEND_ONLY_TABLES:
        for op in ("UPDATE", "DELETE"):
            parts.append(
                f"CREATE TRIGGER IF NOT EXISTS {table}_no_{op.lower()} BEFORE {op} ON {table} "
                f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END;"
            )
    return "\n".join(parts)


# Persisted case state machine. Anything not listed is refused.
CASE_TRANSITIONS: dict[str | None, frozenset[str]] = {
    None: frozenset({"received"}),
    "received": frozenset({"validated", "rejected"}),
    "validated": frozenset({"enriched", "rejected"}),
    "enriched": frozenset({"proposed", "closed"}),
    "proposed": frozenset({"awaiting_approval", "rejected", "executing"}),
    "awaiting_approval": frozenset({"executing", "rejected", "expired", "closed"}),
    "executing": frozenset({"verified", "failed", "partially_completed"}),
    "verified": frozenset({"recovery_pending"}),
    "recovery_pending": frozenset({"closed", "verified", "partially_completed"}),
    "partially_completed": frozenset({"recovery_pending", "proposed"}),
    "failed": frozenset({"proposed", "closed"}),
    "rejected": frozenset({"proposed", "closed"}),
    "expired": frozenset({"proposed", "closed"}),
    "closed": frozenset(),
}
CONTAINED_STATES = frozenset({"verified", "partially_completed", "recovery_pending"})


class StateError(Exception):
    pass


class Store:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._local = threading.local()
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, isolation_level=None, timeout=10.0, check_same_thread=True)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=10000")
            self._local.conn = conn
        return conn

    def init(self) -> None:
        conn = self.connect()
        conn.executescript(DDL + _triggers())
        with self.tx() as c:
            row = c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            if row is None:
                c.execute("INSERT INTO meta (key, value) VALUES ('schema_version', ?)", (SCHEMA_VERSION,))
            elif row["value"] != SCHEMA_VERSION:
                raise StateError(f"database schema {row['value']} does not match code schema {SCHEMA_VERSION}")

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        else:
            conn.execute("COMMIT")

    # ------------------------------------------------------------------ audit

    @staticmethod
    def audit(c: sqlite3.Connection, *, at: datetime, actor: str, action: str, subject: str, details: dict) -> str:
        last = c.execute("SELECT seq, hash FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
        seq = 1 if last is None else last["seq"] + 1
        prev = GENESIS if last is None else last["hash"]
        stamp = iso(at)
        details_json = canonical_json(details)
        body = canonical_json(
            {"seq": seq, "at": stamp, "actor": actor, "action": action, "subject": subject, "details": details_json}
        )
        digest = sha256_hex(prev + body)
        c.execute(
            "INSERT INTO audit (seq, at, actor, action, subject, details_json, prev_hash, hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (seq, stamp, actor, action, subject, details_json, prev, digest),
        )
        return digest

    def verify_audit(self) -> dict[str, Any]:
        conn = self.connect()
        prev = GENESIS
        count = 0
        for row in conn.execute("SELECT * FROM audit ORDER BY seq"):
            count += 1
            body = canonical_json(
                {
                    "seq": row["seq"],
                    "at": row["at"],
                    "actor": row["actor"],
                    "action": row["action"],
                    "subject": row["subject"],
                    "details": row["details_json"],
                }
            )
            if row["seq"] != count or row["prev_hash"] != prev or sha256_hex(prev + body) != row["hash"]:
                return {"ok": False, "records": count, "first_bad_seq": row["seq"]}
            prev = row["hash"]
        return {"ok": True, "records": count, "head": prev}

    # ------------------------------------------------------------------ cases

    def transition(
        self, c: sqlite3.Connection, case_id: str, to_state: str, *, at: datetime, actor: str, reason: str
    ) -> None:
        row = c.execute("SELECT state FROM cases WHERE case_id=?", (case_id,)).fetchone()
        current = None if row is None else row["state"]
        if to_state not in CASE_TRANSITIONS.get(current, frozenset()):
            raise StateError(f"case {case_id}: transition {current} -> {to_state} is not allowed")
        c.execute("UPDATE cases SET state=?, updated_at=? WHERE case_id=?", (to_state, iso(at), case_id))
        c.execute(
            "INSERT INTO case_transitions (case_id, from_state, to_state, at, actor, reason) VALUES (?,?,?,?,?,?)",
            (case_id, current, to_state, iso(at), actor, reason),
        )
        self.audit(
            c, at=at, actor=actor, action="case.transition", subject=case_id,
            details={"from": current, "to": to_state, "reason": reason},
        )

    # ------------------------------------------------------------------ controls

    @staticmethod
    def get_control(c: sqlite3.Connection, key: str, default: Any) -> Any:
        row = c.execute("SELECT value_json FROM controls WHERE key=?", (key,)).fetchone()
        return default if row is None else json.loads(row["value_json"])

    @staticmethod
    def set_control(c: sqlite3.Connection, key: str, value: Any, *, at: datetime, by: str) -> None:
        c.execute(
            "INSERT INTO controls (key, value_json, updated_at, updated_by) VALUES (?,?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at, "
            "updated_by=excluded.updated_by",
            (key, canonical_json(value), iso(at), by),
        )

    @staticmethod
    def sensor_trusted(c: sqlite3.Connection, sensor_id: str) -> bool:
        row = c.execute("SELECT trusted FROM sensor_trust WHERE sensor_id=?", (sensor_id,)).fetchone()
        return True if row is None else bool(row["trusted"])
