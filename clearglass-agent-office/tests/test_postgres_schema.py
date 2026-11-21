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
    for migration in sorted((ROOT / "infra" / "db" / "postgres").glob("*.sql")):
        conn.execute(migration.read_text())
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


def _approval(db, aid="a1", tier="high", status="pending"):
    db.execute(
        "INSERT INTO approvals (id, action_type, action, action_digest, requested_by, risk_tier, status,"
        " approved_digest, expires_at) VALUES (%s, 'content.publish', '{}', %s, 'eng.lead', %s, %s, %s, now())",
        (aid, DIGEST, tier, status, DIGEST if status in ("approved", "executed") else None),
    )


def test_approval_request_is_immutable_and_terminal_states_stick(db):
    import psycopg

    seed(db)
    _approval(db)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("UPDATE approvals SET action = '{\"edited\": true}' WHERE id = 'a1'")
    db.execute("UPDATE approvals SET status = 'approved', approved_digest = %s WHERE id = 'a1'", (DIGEST,))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("UPDATE approvals SET approved_digest = %s WHERE id = 'a1'", ("b" * 64,))
    db.execute("UPDATE approvals SET status = 'executed' WHERE id = 'a1'")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("UPDATE approvals SET status = 'approved' WHERE id = 'a1'")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("DELETE FROM approvals WHERE id = 'a1'")


def test_one_decision_and_one_execution_per_approval(db):
    import psycopg

    seed(db)
    _approval(db)
    insert = (
        "INSERT INTO approval_decisions (approval_id, decision, reason, decided_by)"
        " VALUES ('a1', %s, 'Checked the payload against the brief.', 'operator.founder')"
    )
    db.execute(insert, ("approve",))
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute(insert, ("reject",))
    db.execute(insert, ("cancelled",))  # a cancellation may still follow
    db.execute("INSERT INTO approval_executions (approval_id, executed_digest) VALUES ('a1', %s)", (DIGEST,))
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute("INSERT INTO approval_executions (approval_id, executed_digest) VALUES ('a1', %s)", (DIGEST,))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("DELETE FROM approval_executions")


def test_grant_limits_and_revocation_are_checked(db):
    import psycopg

    seed(db)
    base = "INSERT INTO permissions (id, agent_id, domain, level, granted_by, constraints, revoked_at, revoked_by)"
    db.execute(
        base + " VALUES ('p1','eng.lead','finance','execute','op', %s, NULL, NULL)", ('{"spend_limit_cents": 5000}',)
    )
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(base + " VALUES ('p2','eng.lead','social','execute','op', %s, NULL, NULL)", ('{"anything": 1}',))
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            base + " VALUES ('p3','eng.lead','email','execute','op', %s, NULL, NULL)", ('{"spend_limit_cents": -1}',)
        )
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(base + " VALUES ('p4','eng.lead','data','write','op', '{}', now(), NULL)")


def test_mission_mode_and_shadow_divergence_rules(db):
    import psycopg

    seed(db)
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        db.execute(
            "INSERT INTO workflows (id, mission_id) VALUES ('w1', 'm1');"
            "INSERT INTO missions (id, title, objective, department, owner, workflow_id, created_by, mode)"
            " VALUES ('m1','t','o','eng','eng.lead','w1','op','chaos')"
        )
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "INSERT INTO shadow_divergences (id, rule_ids, action_type, agent_id, enforced_outcome, shadow_outcome,"
            " digest, shadow_version) VALUES ('s1', '[\"r\"]', 'x', 'eng.lead', 'allow', 'allow', %s, 'v1')",
            (DIGEST,),
        )


def test_plan_first_mission_mode_is_accepted(db):
    """003_plan_first_mode.sql widens the mode check; it does not remove it."""
    import psycopg

    seed(db)
    with db.transaction():
        db.execute(
            "INSERT INTO workflows (id, mission_id) VALUES ('w2', 'm2');"
            "INSERT INTO missions (id, title, objective, department, owner, workflow_id, created_by, mode)"
            " VALUES ('m2','t','o','eng','eng.lead','w2','op','plan_first')"
        )
    stored = db.execute("SELECT count(*) FROM missions WHERE id = 'm2' AND mode = 'plan_first'").fetchone()[0]
    assert stored == 1
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        db.execute(
            "INSERT INTO workflows (id, mission_id) VALUES ('w3', 'm3');"
            "INSERT INTO missions (id, title, objective, department, owner, workflow_id, created_by, mode)"
            " VALUES ('m3','t','o','eng','eng.lead','w3','op','growth_hack')"
        )


def test_revenue_tables_hold_their_invariants(db):
    """004_revenue_operations.sql: money facts are append-only and counted once, and only a processor
    record makes money "received"; an offer decision is a human act; one approval drives one action."""
    import psycopg

    seed(db)
    money = (
        "INSERT INTO money_events (event_id, opportunity_id, kind, amount_cents, currency, provider, record_type,"
        " external_ref, provider_status, verification, evidence, occurred_at, recorded_by)"
        " VALUES (%s, 'opp_1', %s, 28137, 'CAD', 'paypal', 'invoice', 'INV-1', 'PAID', %s, 'e', now(),"
        " 'operator.founder')"
    )
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(money, ("m1", "payment_received", "operator_attested"))
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(money, ("m2", "payment_reported", "provider_record"))
    db.execute(money, ("m3", "payment_received", "provider_record"))
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute(money, ("m4", "payment_received", "provider_record"))
    for stmt in ("UPDATE money_events SET amount_cents = 1", "DELETE FROM money_events", "TRUNCATE money_events"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db.execute(stmt)

    decision = (
        "INSERT INTO offer_decisions (sku, decision, offer, offer_digest, reason, decided_by)"
        " VALUES ('quick-audit', 'approve', '{}', %s, %s, %s)"
    )
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute(decision, (DIGEST, "Approved by the owner for launch.", "eng.lead"))
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(decision, (DIGEST, "ok", "operator.founder"))
    db.execute(decision, (DIGEST, "Approved by the owner for launch.", "operator.founder"))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("DELETE FROM offer_decisions")

    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "INSERT INTO suppressions (address, reason, source_ref, recorded_by)"
            " VALUES ('Alex@Example.com', 'opt-out', 'msg-1', 'operator.founder')"
        )

    _approval(db, "a1", "high", "approved")
    db.execute(
        "INSERT INTO opportunities (id, stage, source, source_ref, contact, consent, created_by)"
        " VALUES ('opp_1', 'qualified', 'inbound_email', 't-1', '{}', '{}', 'operator.founder')"
    )
    action = (
        "INSERT INTO external_actions (id, opportunity_id, kind, action_type, agent_id, connector, payload,"
        " payload_digest, record_version, status, approval_id, ticket)"
        " VALUES (%s, 'opp_1', 'outreach_email', 'outreach.send', 'eng.lead', 'gmail', '{}', %s, 1, %s, 'a1', %s)"
    )
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(action, ("e1", DIGEST, "released", None))
    db.execute(action, ("e2", DIGEST, "released", '{"steps": []}'))
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute(action, ("e3", DIGEST, "approved", None))
