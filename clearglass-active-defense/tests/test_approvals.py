"""Approvals bind to the exact plan, policy version and time window, once."""

from __future__ import annotations

import sqlite3

import pytest

from active_defense.config import Principal
from active_defense.errors import Conflict, Forbidden, Invalid


def test_approval_replay_is_refused(lab):
    p = lab.proposal(lab.corroborate())
    lab.decide(p)
    with pytest.raises(Conflict, match="one decision"):
        lab.decide(p)
    with pytest.raises(Conflict, match="one decision"):
        lab.decide(p, who="approver-2", decision="rejected")
    assert lab.sql("SELECT COUNT(*) FROM approvals")[0][0] == 1
    assert lab.sql("SELECT COUNT(*) FROM actions")[0][0] == 1
    assert "proposal.decision_refused" in lab.audit_actions()


def test_wrong_plan_hash_is_refused(lab):
    p = lab.proposal(lab.corroborate())
    with pytest.raises(Conflict, match="plan hash"):
        lab.decide(p, plan_hash="f" * 64)
    assert lab.proposal(p["case_id"])["status"] == "awaiting_approval"


def test_parameter_tampering_in_storage_is_detected_at_approval(lab):
    p = lab.proposal(lab.corroborate())
    row = lab.sql("SELECT plan_json FROM proposals WHERE proposal_id=?", p["proposal_id"])[0][0]
    lab.store.connect().execute("UPDATE proposals SET plan_json=? WHERE proposal_id=?",
                                (row.replace("lab-ws-001", "lab-dc-001"), p["proposal_id"]))
    with pytest.raises(Conflict, match="tampering"):
        lab.decide(p)
    assert lab.sql("SELECT COUNT(*) FROM actions")[0][0] == 0


def test_parameter_tampering_after_approval_is_blocked_at_execution(lab):
    case_id = lab.corroborate()
    p = lab.proposal(case_id)
    lab.decide(p)
    row = lab.sql("SELECT plan_json FROM proposals WHERE proposal_id=?", p["proposal_id"])[0][0]
    lab.store.connect().execute("UPDATE proposals SET plan_json=? WHERE proposal_id=?",
                                (row.replace("10.66.0.11/32:443", "0.0.0.0/0:443"), p["proposal_id"]))
    result = lab.executor.run_once()
    assert result[0]["status"] == "blocked" and "hash" in result[0]["reason"]
    assert lab.adapter.call_count("apply", "lab-ws-001") == 0
    assert lab.state(case_id) == "failed"


def test_expired_proposal_cannot_be_approved(lab):
    case_id = lab.corroborate()
    p = lab.proposal(case_id)
    lab.clock.advance(3601)
    with pytest.raises(Conflict, match="expired"):
        lab.decide(p)
    assert lab.proposal(case_id)["status"] == "expired" and lab.state(case_id) == "expired"


def test_worker_sweep_expires_undecided_proposals(lab):
    case_id = lab.corroborate()
    lab.clock.advance(3601)
    lab.executor.run_once()
    assert lab.state(case_id) == "expired"


def test_policy_version_change_invalidates_pending_approval(lab):
    p = lab.proposal(lab.corroborate())
    with pytest.raises(Conflict, match="policy version"):
        lab.decide(p, policy_version="pv-other")


def test_roles_are_enforced(lab):
    p = lab.proposal(lab.corroborate())
    for who in ("analyst-1", "admin-1"):
        with pytest.raises(Forbidden):
            lab.decide(p, who=who)
    with pytest.raises(Invalid):
        lab.decide(p, reason="   ")


def test_requester_cannot_approve_own_recovery(lab):
    case_id = lab.contain()
    rel = lab.ops.request_recovery(lab.p["analyst-1"], case_id, criteria=lab.criteria(), reason="fixed")
    rogue = Principal("analyst-1", "approver")  # same name, approver role: still the requester
    with pytest.raises(Forbidden, match="own request"):
        lab.ops.decide(rogue, rel["proposal_id"], decision="approved", plan_hash=rel["plan_hash"],
                       policy_version=lab.bundle.config.policy_version, reason="self")


def test_rejection_leaves_nothing_queued(lab):
    case_id = lab.corroborate()
    lab.decide(lab.proposal(case_id), decision="rejected")
    assert lab.state(case_id) == "rejected"
    assert lab.sql("SELECT COUNT(*) FROM actions")[0][0] == 0


def test_approval_refused_when_evidence_sensor_is_distrusted(lab):
    case_id = lab.corroborate()
    p = lab.proposal(case_id)
    lab.ops.set_sensor_trust(lab.p["admin-1"], "sensor-tcp-01", trusted=False, reason="rebuilt host")
    assert lab.proposal(case_id)["status"] == "invalidated" and lab.state(case_id) == "rejected"
    with pytest.raises(Conflict):
        lab.decide(p)


def test_integrity_monitor_report_distrusts_sensor_and_invalidates_queued_action(lab):
    case_id = lab.corroborate()
    lab.decide(lab.proposal(case_id))
    lab.send("sensor-integrity-01", category="sensor.health", severity="high",
             attributes={"status": "tamper_suspected", "subject_sensor_id": "sensor-edr-01"})
    assert lab.sql("SELECT trusted FROM sensor_trust WHERE sensor_id='sensor-edr-01'")[0][0] == 0
    assert lab.sql("SELECT status FROM actions")[0][0] == "cancelled"
    assert lab.state(case_id) == "failed"
    assert lab.executor.run_once() == []
    after = lab.edr()  # new events from the distrusted sensor are evidence only
    assert after["note"].startswith("sensor distrusted")


def test_approvals_table_is_append_only(lab):
    lab.decide(lab.proposal(lab.corroborate()))
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        lab.store.connect().execute("UPDATE approvals SET principal='someone-else'")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        lab.store.connect().execute("DELETE FROM approvals")
