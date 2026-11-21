"""Evidence manifests, custody, retention, and the hash-chained append-only audit log."""

from __future__ import annotations

import sqlite3
from datetime import timedelta

import pytest

from active_defense.evidence import apply_retention, case_manifest, verify_case


def test_audit_chain_verifies_and_records_every_decision(lab):
    case_id = lab.contain()
    lab.recover(case_id)
    result = lab.store.verify_audit()
    assert result["ok"] and result["records"] > 20
    actions = set(lab.audit_actions())
    for needed in ("ingest.accepted", "signal.raised", "correlation.fired", "proposal.created", "proposal.approved",
                   "action.queued", "action.claimed", "action.executing", "action.verified", "case.transition"):
        assert needed in actions, needed


def test_audit_tampering_is_detected(lab):
    lab.contain()
    conn = lab.store.connect()
    for op in ("UPDATE audit SET actor='x' WHERE seq=3", "DELETE FROM audit WHERE seq=3"):
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute(op)
    conn.execute("DROP TRIGGER audit_no_update")  # an attacker with file access can do this...
    conn.execute("UPDATE audit SET details_json='{}' WHERE seq=3")
    result = lab.store.verify_audit()  # ...but the chain no longer verifies
    assert result == {"ok": False, "records": 3, "first_bad_seq": 3}


def test_transitions_and_custody_are_append_only(lab):
    lab.contain()
    conn = lab.store.connect()
    for table in ("case_transitions", "custody"):
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute(f"DELETE FROM {table}")


def test_invalid_state_transition_is_refused(lab):
    from active_defense.store import StateError
    case_id = lab.decoy()["cases"][0]
    with lab.store.tx() as c, pytest.raises(StateError):
        lab.store.transition(c, case_id, "verified", at=lab.clock.now(), actor="test", reason="skip ahead")


def test_evidence_manifest_and_integrity(lab):
    case_id = lab.corroborate()
    c = lab.store.connect()
    m = case_manifest(c, case_id, at=lab.clock.now())
    assert len(m["artifacts"]) == 2 and len(m["manifest_sha256"]) == 64
    assert "do not prove custody" in m["limits"]
    assert verify_case(c, case_id)["ok"]
    art = m["artifacts"][0]["artifact_id"]
    c.execute("UPDATE artifacts SET content=? WHERE artifact_id=?", (b'{"tampered":true}', art))
    v = verify_case(c, case_id)
    assert not v["ok"] and v["problems"][0]["problem"] == "content does not match recorded hash"


def test_artifact_is_the_exact_signed_body(lab):
    ev = lab.event("sensor-tcp-01", category="tripwire.tcp.connect", src_ip="10.66.10.21")
    headers, body = lab.signed("sensor-tcp-01", ev)
    lab.engine.ingest(headers, body)
    assert bytes(lab.sql("SELECT content FROM artifacts")[0][0]) == body
    assert lab.sql("SELECT action FROM custody")[0][0] == "collected"


def test_retention_purges_content_but_keeps_hashes_and_open_cases(lab):
    closed = lab.decoy("192.0.2.5")["cases"][0]
    lab.ops.false_positive(lab.p["analyst-1"], closed, rationale="lab noise")
    open_case = lab.decoy("192.0.2.6")["cases"][0]
    lab.clock.advance(91 * 86400)
    n = apply_retention(lab.store, retention_days=90, at=lab.clock.now(), actor="test")
    assert n == 1
    c = lab.store.connect()
    assert verify_case(c, closed)["ok"]  # purge is recorded, so the gap is explained
    assert case_manifest(c, closed, at=lab.clock.now())["artifacts"][0]["purged"] is True
    assert case_manifest(c, open_case, at=lab.clock.now())["artifacts"][0]["purged"] is False
    assert lab.sql("SELECT COUNT(*) FROM custody WHERE action='purged'")[0][0] == 1


def test_metrics_are_labelled_with_their_limits(lab):
    case_id = lab.contain()
    lab.clock.advance(120)
    lab.recover(case_id)
    m = lab.ops.metrics(lab.p["analyst-1"])
    assert m["label"]["environment"] == "lab" and "say nothing about production" in m["label"]["limitations"]
    assert m["recoveries_verified"] == 1 and m["false_containment_count"] == 0
    assert m["active_containments"] == 0
    assert timedelta(seconds=m["approval_seconds_avg"] or 0) >= timedelta(0)
