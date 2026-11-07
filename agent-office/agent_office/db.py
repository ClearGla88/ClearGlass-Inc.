"""SQLite system of record.

The schema mirrors the PostgreSQL design in the blueprint, with the governance
invariants pushed into the database where SQLite can hold them:

* ``audit_events`` refuses UPDATE and DELETE, and ``prev_hash`` is UNIQUE, so the
  chain cannot be edited or forked.
* An approval's request (agent, tool, payload, hash) can never change after it
  is filed, and a decided approval cannot be decided again.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    mission_statement TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS departments (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies(id),
    key TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    floor_index INTEGER NOT NULL DEFAULT 0,
    UNIQUE (company_id, key)
);

CREATE TABLE IF NOT EXISTS agents (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies(id),
    department_id TEXT NOT NULL REFERENCES departments(id),
    reporting_to TEXT REFERENCES agents(id),
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    objective TEXT NOT NULL,
    success_criteria TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'idle' CHECK (status IN (
        'idle','working','waiting_for_approval','blocked','completed',
        'failed','paused','suspended','retired')),
    risk_level TEXT NOT NULL DEFAULT 'low' CHECK (risk_level IN ('low','medium','high','critical')),
    memory_scope TEXT NOT NULL DEFAULT '{}',
    identity_ref TEXT NOT NULL UNIQUE,
    owner_id TEXT NOT NULL,
    approver_id TEXT,
    can_request_critical INTEGER NOT NULL DEFAULT 0 CHECK (can_request_critical IN (0,1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (company_id, name)
);

CREATE TABLE IF NOT EXISTS tools (
    id TEXT PRIMARY KEY,
    key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL,
    environment TEXT NOT NULL CHECK (environment IN ('internal','sandbox','production')),
    capability_surface TEXT NOT NULL,
    requires_secret INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS agent_tool_grants (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL REFERENCES agents(id),
    tool_id TEXT NOT NULL REFERENCES tools(id),
    action TEXT NOT NULL CHECK (action IN ('read','write','propose','execute','approve')),
    constraints TEXT NOT NULL DEFAULT '{}',
    granted_by TEXT NOT NULL,
    granted_at TEXT NOT NULL,
    expires_at TEXT,
    revoked_at TEXT,
    revoked_by TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_active_grant
    ON agent_tool_grants (agent_id, tool_id, action) WHERE revoked_at IS NULL;

CREATE TABLE IF NOT EXISTS missions (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies(id),
    department_id TEXT REFERENCES departments(id),
    code TEXT NOT NULL,
    title TEXT NOT NULL,
    objective TEXT NOT NULL,
    deliverables TEXT NOT NULL DEFAULT '[]',
    mode TEXT NOT NULL DEFAULT 'production' CHECK (mode IN ('production','simulation')),
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN (
        'draft','active','paused','waiting_for_approval','blocked','completed','failed','cancelled')),
    priority INTEGER NOT NULL DEFAULT 3,
    deadline TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (company_id, code)
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL REFERENCES missions(id),
    key TEXT NOT NULL,
    assigned_agent_id TEXT REFERENCES agents(id),
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN (
        'pending','in_progress','waiting_for_approval','blocked','completed','failed','cancelled')),
    depends_on TEXT NOT NULL DEFAULT '[]',
    tool_key TEXT NOT NULL,
    action TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    risk_level TEXT,
    approval_id TEXT,
    actual_output TEXT,
    block_reason TEXT,
    started_at TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (mission_id, key)
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    mission_id TEXT REFERENCES missions(id),
    task_id TEXT REFERENCES tasks(id),
    sender_agent_id TEXT REFERENCES agents(id),
    recipient_agent_id TEXT REFERENCES agents(id),
    kind TEXT NOT NULL CHECK (kind IN (
        'message','handoff','escalation','decision_record','meeting_summary')),
    body TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    mission_id TEXT REFERENCES missions(id),
    task_id TEXT REFERENCES tasks(id),
    agent_id TEXT NOT NULL REFERENCES agents(id),
    tool_key TEXT NOT NULL,
    action TEXT NOT NULL,
    action_summary TEXT NOT NULL,
    risk_level TEXT NOT NULL CHECK (risk_level IN ('low','medium','high','critical')),
    request_payload TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    policy_rationale TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN (
        'pending','approved','rejected','modified','expired','cancelled')),
    requested_at TEXT NOT NULL,
    expires_at TEXT,
    decided_by TEXT,
    decider_type TEXT CHECK (decider_type IN ('human','agent','system')),
    decided_at TEXT,
    decision_reason TEXT,
    modified_payload TEXT,
    consumed_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_pending_approval
    ON approvals (request_hash) WHERE status = 'pending';

CREATE TRIGGER IF NOT EXISTS approvals_request_immutable
BEFORE UPDATE OF agent_id, tool_key, action, risk_level, request_payload, request_hash, requested_at
ON approvals
BEGIN
    SELECT RAISE(ABORT, 'approval requests are immutable');
END;

CREATE TRIGGER IF NOT EXISTS approvals_decide_once
BEFORE UPDATE OF status ON approvals
WHEN OLD.status <> 'pending'
BEGIN
    SELECT RAISE(ABORT, 'approval already decided');
END;

CREATE TRIGGER IF NOT EXISTS approvals_consume_once
BEFORE UPDATE OF consumed_at ON approvals
WHEN OLD.consumed_at IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'approval already consumed');
END;

CREATE TABLE IF NOT EXISTS audit_events (
    seq INTEGER PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    company_id TEXT NOT NULL,
    actor_type TEXT NOT NULL CHECK (actor_type IN ('agent','human','system')),
    actor_id TEXT NOT NULL,
    action TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT,
    risk_level TEXT,
    policy_decision TEXT,
    policy_ids TEXT NOT NULL DEFAULT '[]',
    approval_id TEXT,
    correlation_id TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    outcome TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    prev_hash TEXT NOT NULL UNIQUE,
    event_hash TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_audit_correlation ON audit_events (correlation_id);
CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_events (actor_type, actor_id);
CREATE INDEX IF NOT EXISTS idx_audit_approval ON audit_events (approval_id);

CREATE TRIGGER IF NOT EXISTS audit_events_no_update
BEFORE UPDATE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit_events is append-only');
END;

CREATE TRIGGER IF NOT EXISTS audit_events_no_delete
BEFORE DELETE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit_events is append-only');
END;

CREATE TABLE IF NOT EXISTS policy_shadow_divergences (
    id INTEGER PRIMARY KEY,
    correlation_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    tool_key TEXT NOT NULL,
    action TEXT NOT NULL,
    enforced_effect TEXT NOT NULL,
    shadow_effect TEXT NOT NULL,
    shadow_policy_ids TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS knowledge_documents (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies(id),
    title TEXT NOT NULL,
    doc_type TEXT NOT NULL,
    content TEXT NOT NULL,
    source TEXT NOT NULL,
    checksum TEXT NOT NULL,
    approved INTEGER NOT NULL DEFAULT 0,
    approved_by TEXT,
    created_by_agent_id TEXT REFERENCES agents(id),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_records (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies(id),
    scope TEXT NOT NULL CHECK (scope IN ('agent_short_term','department','company_approved')),
    namespace TEXT NOT NULL,
    content TEXT NOT NULL,
    source TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.5,
    approved INTEGER NOT NULL DEFAULT 0,
    approved_by TEXT,
    approved_at TEXT,
    created_by_agent_id TEXT REFERENCES agents(id),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reports (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies(id),
    report_type TEXT NOT NULL,
    content_json TEXT NOT NULL,
    rendered_markdown TEXT NOT NULL,
    generated_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS incidents (
    id TEXT PRIMARY KEY,
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    triggered_by TEXT NOT NULL,
    reason TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    resolved_by TEXT
);

CREATE TABLE IF NOT EXISTS emergency_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    halted INTEGER NOT NULL DEFAULT 0 CHECK (halted IN (0,1)),
    incident_id TEXT REFERENCES incidents(id),
    resume_requested_by TEXT,
    resume_requested_at TEXT,
    resume_reason TEXT
);
INSERT OR IGNORE INTO emergency_state (id, halted) VALUES (1, 0);

CREATE TABLE IF NOT EXISTS idempotency_keys (
    operator_id TEXT NOT NULL,
    key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    status_code INTEGER NOT NULL,
    response_body TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (operator_id, key)
);
"""

JSON_COLUMNS = frozenset(
    {
        "success_criteria",
        "memory_scope",
        "capability_surface",
        "constraints",
        "deliverables",
        "depends_on",
        "payload",
        "actual_output",
        "metadata",
        "request_payload",
        "modified_payload",
        "policy_ids",
        "shadow_policy_ids",
        "content_json",
    }
)


def new_id() -> str:
    return str(uuid.uuid4())


def connect(path: str = ":memory:") -> sqlite3.Connection:
    """Open the store. ``isolation_level=None`` means transactions are explicit."""
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if path != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA)
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """``BEGIN IMMEDIATE`` at the outermost level, a savepoint when nested."""
    if conn.in_transaction:
        name = f"sp_{uuid.uuid4().hex}"
        conn.execute(f"SAVEPOINT {name}")
        try:
            yield conn
        except BaseException:
            conn.execute(f"ROLLBACK TO {name}")
            conn.execute(f"RELEASE {name}")
            raise
        conn.execute(f"RELEASE {name}")
    else:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    out: dict[str, Any] = {}
    for key in row.keys():
        value = row[key]
        if key in JSON_COLUMNS and isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                pass
        out[key] = value
    return out


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [row_to_dict(r) for r in rows]  # type: ignore[misc]


def dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
