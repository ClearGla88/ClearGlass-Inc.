"""Apply the production schema to a real PostgreSQL server.

Runs when OFFICE_TEST_PG_URL points at a server where the role may create
databases (CI provides PostgreSQL 16). Skipped otherwise, and the skip is
reported by pytest -rs, never silent.
"""

import os
import uuid

import pytest

from tests.conftest import ROOT

URL = os.environ.get("OFFICE_TEST_PG_URL")
pytestmark = pytest.mark.skipif(not URL, reason="OFFICE_TEST_PG_URL not set")

DIGEST = "a" * 64


@pytest.fixture
def db():
    psycopg = pytest.importorskip("psycopg")
    name = f"office_test_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    base, _, _ = URL.rpartition("/")
    conn = psycopg.connect(f"{base}/{name}", autocommit=True)
    conn.execute((ROOT / "infra" / "db" / "postgres" / "001_init.sql").read_text())
    try:
        yield conn
    finally:
        conn.close()
        with psycopg.connect(URL, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE "{name}"')


def seed(conn):
    with conn.transaction():
        conn.execute(
            "INSERT INTO departments (id, name, room, head, mission) VALUES ('eng','Eng','lab','eng.lead','m')"
        )
        conn.execute(
            "INSERT INTO agents (id, callsign, name, department, reports_to, objective, room)"
            " VALUES ('eng.lead','CG-EN-01','Lead','eng','operator','o','lab')"
        )


def test_schema_applies_and_core_rows_insert(db):
    seed(db)
    count = db.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'").fetchone()[0]
    assert count >= 20


def test_append_only_tables_reject_update_delete_truncate(db):
    import psycopg

    db.execute(
        "INSERT INTO audit_events (seq, event_id, ts, actor, actor_type, event_type, subject, payload,"
        " prev_hash, hash) VALUES (1, 'e1', now(), 'a', 'agent', 't', 's', '{}', %s, %s)",
        ("0" * 64, DIGEST),
    )
    for stmt in ("UPDATE audit_events SET subject='x'", "DELETE FROM audit_events", "TRUNCATE audit_events"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db.execute(stmt)


def test_permissions_cannot_grant_approve(db):
    import psycopg

    seed(db)
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "INSERT INTO permissions (id, agent_id, domain, level, granted_by)"
            " VALUES ('p', 'eng.lead', 'social', 'approve', 'x')"
        )


def test_reports_to_must_exist(db):
    import psycopg

    seed(db)
    with pytest.raises(psycopg.errors.RaiseException):
        db.execute(
            "INSERT INTO agents (id, callsign, name, department, reports_to, objective, room)"
            " VALUES ('eng.b','CG-EN-02','B','eng','eng.ghost','o','lab')"
        )


def test_critical_approval_needs_plans_and_approved_needs_digest(db):
    import psycopg

    seed(db)
    base = (
        "INSERT INTO approvals (id, action_type, action, action_digest, requested_by, risk_tier, status,"
        " change_plan, rollback_plan, verification_plan, approved_digest, expires_at)"
        " VALUES (%s, 'deploy.production', '{}', %s, 'eng.lead', %s, %s, %s, %s, %s, %s, now())"
    )
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(base, ("a1", DIGEST, "critical", "pending", "", "", "", None))
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(base, ("a2", DIGEST, "high", "approved", None, None, None, None))
    db.execute(base, ("a3", DIGEST, "critical", "approved", "c", "r", "v", DIGEST))


def test_decision_reasons_must_be_substantive(db):
    import psycopg

    seed(db)
    db.execute(
        "INSERT INTO approvals (id, action_type, action, action_digest, requested_by, risk_tier, expires_at)"
        " VALUES ('a1','content.publish','{}',%s,'eng.lead','high',now())",
        (DIGEST,),
    )
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "INSERT INTO approval_decisions (approval_id, decision, reason, decided_by)"
            " VALUES ('a1','approve','ok','operator.founder')"
        )
