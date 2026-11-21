"""Append-only, hash-chained audit ledger.

Every event's hash covers every stored field plus the previous event's hash, so
changing any field of any past event breaks every link after it. Appends are
serialised (``BEGIN IMMEDIATE`` plus a monotonic ``seq``), and ``prev_hash`` is
UNIQUE, so two concurrent writers cannot fork the chain.

Observability traces are sampled and expire. This ledger is the durable record.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from .db import dumps, new_id, row_to_dict, rows_to_dicts, transaction
from .models import AuditFailure, Clock, canonical_json, iso, sha256_hex, utcnow

GENESIS_HASH = "0" * 64

HASHED_FIELDS = (
    "seq",
    "event_id",
    "company_id",
    "actor_type",
    "actor_id",
    "action",
    "resource_type",
    "resource_id",
    "risk_level",
    "policy_decision",
    "policy_ids",
    "approval_id",
    "correlation_id",
    "payload_hash",
    "outcome",
    "metadata",
    "created_at",
)

ACTOR_TYPES = frozenset({"agent", "human", "system"})


def compute_event_hash(prev_hash: str, record: dict[str, Any]) -> str:
    body = canonical_json({name: record.get(name) for name in HASHED_FIELDS})
    return sha256_hex(prev_hash + "\n" + body)


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    events: int
    head_hash: str
    first_bad_seq: int | None = None
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "events": self.events,
            "head_hash": self.head_hash,
            "first_bad_seq": self.first_bad_seq,
            "reason": self.reason,
        }


class AuditLedger:
    def __init__(self, conn: sqlite3.Connection, company_id: str, clock: Clock = utcnow):
        self.conn = conn
        self.company_id = company_id
        self.clock = clock

    def append(
        self,
        *,
        actor_type: str,
        actor_id: str,
        action: str,
        resource_type: str,
        outcome: str,
        correlation_id: str,
        resource_id: str | None = None,
        payload: Any = None,
        risk_level: str | None = None,
        policy_decision: str | None = None,
        policy_ids: list[str] | tuple[str, ...] = (),
        approval_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Write one event. Raises :class:`AuditFailure` if it cannot be recorded."""
        if actor_type not in ACTOR_TYPES:
            raise AuditFailure(f"unknown actor_type {actor_type!r}")
        try:
            with transaction(self.conn):
                head = self.conn.execute(
                    "SELECT seq, event_hash FROM audit_events ORDER BY seq DESC LIMIT 1"
                ).fetchone()
                seq = (head["seq"] + 1) if head else 1
                prev_hash = head["event_hash"] if head else GENESIS_HASH
                record: dict[str, Any] = {
                    "seq": seq,
                    "event_id": new_id(),
                    "company_id": self.company_id,
                    "actor_type": actor_type,
                    "actor_id": actor_id,
                    "action": action,
                    "resource_type": resource_type,
                    "resource_id": resource_id,
                    "risk_level": risk_level,
                    "policy_decision": policy_decision,
                    "policy_ids": sorted(policy_ids),
                    "approval_id": approval_id,
                    "correlation_id": correlation_id,
                    "payload_hash": sha256_hex(payload if payload is not None else {}),
                    "outcome": outcome,
                    "metadata": metadata or {},
                    "created_at": iso(self.clock()),
                }
                record["prev_hash"] = prev_hash
                record["event_hash"] = compute_event_hash(prev_hash, record)
                self.conn.execute(
                    """
                    INSERT INTO audit_events (
                        seq, event_id, company_id, actor_type, actor_id, action,
                        resource_type, resource_id, risk_level, policy_decision,
                        policy_ids, approval_id, correlation_id, payload_hash,
                        outcome, metadata, created_at, prev_hash, event_hash)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        record["seq"],
                        record["event_id"],
                        record["company_id"],
                        record["actor_type"],
                        record["actor_id"],
                        record["action"],
                        record["resource_type"],
                        record["resource_id"],
                        record["risk_level"],
                        record["policy_decision"],
                        dumps(record["policy_ids"]),
                        record["approval_id"],
                        record["correlation_id"],
                        record["payload_hash"],
                        record["outcome"],
                        dumps(record["metadata"]),
                        record["created_at"],
                        record["prev_hash"],
                        record["event_hash"],
                    ),
                )
        except sqlite3.Error as exc:
            raise AuditFailure(f"audit write failed: {exc}") from exc
        return record

    def verify(self) -> VerifyResult:
        """Replay the chain from genesis and report the first broken link."""
        prev_hash = GENESIS_HASH
        count = 0
        expected_seq = 1
        for row in self.conn.execute("SELECT * FROM audit_events ORDER BY seq"):
            record = row_to_dict(row)
            assert record is not None
            if record["seq"] != expected_seq:
                return VerifyResult(False, count, prev_hash, record["seq"], "sequence gap")
            if record["prev_hash"] != prev_hash:
                return VerifyResult(False, count, prev_hash, record["seq"], "prev_hash mismatch")
            if compute_event_hash(prev_hash, record) != record["event_hash"]:
                return VerifyResult(False, count, prev_hash, record["seq"], "event_hash mismatch")
            prev_hash = record["event_hash"]
            count += 1
            expected_seq += 1
        return VerifyResult(True, count, prev_hash)

    def events(
        self,
        *,
        actor_id: str | None = None,
        correlation_id: str | None = None,
        approval_id: str | None = None,
        action_prefix: str | None = None,
        outcome: str | None = None,
        after_seq: int = 0,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        clauses = ["seq > ?"]
        params: list[Any] = [after_seq]
        for column, value in (
            ("actor_id", actor_id),
            ("correlation_id", correlation_id),
            ("approval_id", approval_id),
            ("outcome", outcome),
        ):
            if value is not None:
                clauses.append(f"{column} = ?")
                params.append(value)
        if action_prefix:
            clauses.append("action LIKE ?")
            params.append(action_prefix.replace("%", "") + "%")
        params.append(max(1, min(limit, 1000)))
        rows = self.conn.execute(
            f"SELECT * FROM audit_events WHERE {' AND '.join(clauses)} ORDER BY seq DESC LIMIT ?",
            params,
        ).fetchall()
        return rows_to_dicts(rows)

    def count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0])

    def head_seq(self) -> int:
        row = self.conn.execute("SELECT MAX(seq) FROM audit_events").fetchone()
        return int(row[0] or 0)
