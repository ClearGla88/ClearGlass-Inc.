"""Executor: idempotent, restart-safe, bounded, and never removes containment on its own."""

from __future__ import annotations

import pytest

from active_defense.errors import Conflict
from active_defense.executor import Executor

FAST = {"adapter_timeout_seconds": 0.2, "retry_backoff_seconds": 0, "lease_seconds": 30}


def approved(lab, asset="lab-ws-001", ip="10.66.10.21"):
    case_id = lab.corroborate(asset, ip)
    lab.decide(lab.proposal(case_id))
    return case_id


def test_full_lifecycle_isolate_verify_recover(lab):
    case_id = lab.contain()
    key = lab.case(case_id)["actions"][0]["idempotency_key"]
    assert lab.state(case_id) == "verified"
    assert lab.adapter.state("lab-ws-001", key) >= {"deny_inbound_except_management", "tag_quarantined",
                                                    "allow_management:10.66.0.10/32:22"}
    assert lab.sql("SELECT state FROM containments")[0][0] == "active"
    result = lab.recover(case_id)
    assert result[0]["status"] == "verified" and lab.state(case_id) == "closed"
    assert lab.adapter.state("lab-ws-001", key) == set()
    assert lab.sql("SELECT state FROM containments")[0][0] == "released"
    assert lab.adapter.baseline_rules() == 3  # unrelated policy untouched throughout
    states = [t["to_state"] for t in lab.case(case_id)["transitions"]]
    assert states == ["received", "validated", "enriched", "proposed", "awaiting_approval", "executing",
                      "verified", "recovery_pending", "closed"]


def test_recovery_requires_every_criterion(lab):
    case_id = lab.contain()
    crit = lab.criteria()
    crit.pop("credentials_rotated")
    from active_defense.errors import Invalid
    with pytest.raises(Invalid, match="credentials_rotated"):
        lab.ops.request_recovery(lab.p["analyst-1"], case_id, criteria=crit, reason="x")


def test_rejected_release_keeps_containment(lab):
    case_id = lab.contain()
    rel = lab.ops.request_recovery(lab.p["analyst-1"], case_id, criteria=lab.criteria(), reason="fixed")
    lab.decide(rel, who="approver-2", decision="rejected")
    assert lab.state(case_id) == "verified"
    assert lab.sql("SELECT state FROM containments")[0][0] == "active"


def test_review_deadline_flags_but_never_releases(lab):
    case_id = lab.contain()
    lab.clock.advance(25 * 3600)
    lab.executor.run_once()
    view = lab.case(case_id)
    assert view["case"]["review_overdue"] == 1 and view["case"]["state"] == "verified"
    assert lab.sql("SELECT state FROM containments")[0][0] == "active"
    assert "review.overdue" in lab.audit_actions()


def test_timeout_after_apply_is_reconciled_without_reapplying(make_lab):
    lab = make_lab(response=FAST)
    case_id = approved(lab)
    lab.adapter.inject_fault("lab-ws-001", "apply", "timeout", hang_seconds=0.6)
    result = lab.executor.run_once()
    assert result[0]["status"] == "verified" and lab.state(case_id) == "verified"
    assert lab.adapter.call_count("apply", "lab-ws-001") == 1


def test_timeout_without_apply_retries_then_succeeds(make_lab):
    lab = make_lab(response=FAST)
    case_id = approved(lab)
    lab.adapter.inject_fault("lab-ws-001", "apply", "timeout_noop", hang_seconds=0.4)
    assert lab.executor.run_once()[0]["status"] == "retry_scheduled"
    assert lab.executor.run_once()[0]["status"] == "verified"
    assert lab.state(case_id) == "verified"


def test_bounded_retries_then_failure_and_circuit_breaker(make_lab):
    lab = make_lab(response={**FAST, "circuit_breaker_threshold": 3, "max_attempts": 3})
    case_id = approved(lab)
    lab.adapter.inject_fault("lab-ws-001", "apply", "error", times=5)
    statuses = [lab.executor.run_once()[0]["status"] for _ in range(3)]
    assert statuses == ["retry_scheduled", "retry_scheduled", "failed"]
    assert lab.state(case_id) == "failed" and lab.case(case_id)["case"]["escalated"] == 1
    assert lab.executor.run_once()[0]["status"] == "circuit_open"
    assert "control.circuit_opened" in lab.audit_actions()
    lab.ops.reset_circuit(lab.p["admin-1"], reason="adapter fixed")
    assert lab.executor.run_once() == []


def test_partial_apply_is_left_in_place_and_escalated(make_lab):
    lab = make_lab(response=FAST)
    case_id = approved(lab)
    lab.adapter.inject_fault("lab-ws-001", "apply", "partial")
    result = lab.executor.run_once()
    assert result[0]["status"] == "partially_completed" and lab.state(case_id) == "partially_completed"
    key = lab.case(case_id)["actions"][0]["idempotency_key"]
    steps = lab.adapter.state("lab-ws-001", key)
    assert "allow_management:10.66.0.10/32:22" in steps  # management allowed before any deny
    assert "deny_inbound_except_management" in steps and "tag_quarantined" not in steps
    assert tuple(lab.sql("SELECT partial, state FROM containments")[0]) == (1, "active")
    assert lab.recover(case_id)[0]["status"] == "verified"  # compensating action: approved release
    assert lab.adapter.state("lab-ws-001", key) == set()


def test_restart_after_apply_reconciles_without_duplicate_action(make_lab):
    lab = make_lab(response=FAST)
    case_id = approved(lab)
    job = lab.executor._claim()  # worker A claims, applies, then "crashes" before recording
    plan = lab.proposal(case_id)["plan"]["parameters"]
    lab.adapter.apply_isolation("lab-ws-001", job["idempotency_key"], plan["steps"], plan["preserve"])
    lab.clock.advance(31)
    worker_b = Executor(lab.store, lab.bundle, lab.adapter, lab.clock, worker_id="worker-b")
    result = worker_b.run_once()
    assert result[0]["status"] == "verified" and lab.state(case_id) == "verified"
    assert lab.adapter.call_count("apply", "lab-ws-001") == 1
    assert "action.reconciling" in lab.audit_actions()


def test_restart_before_apply_retries_cleanly(make_lab):
    lab = make_lab(response=FAST)
    case_id = approved(lab)
    lab.executor._claim()  # crashed before calling the adapter
    lab.clock.advance(31)
    first = Executor(lab.store, lab.bundle, lab.adapter, lab.clock, worker_id="worker-b").run_once()
    assert first[0]["status"] == "retry_scheduled"
    assert lab.executor.run_once()[0]["status"] == "verified" and lab.state(case_id) == "verified"


def test_live_lease_is_not_stolen(make_lab):
    lab = make_lab(response=FAST)
    approved(lab)
    lab.executor._claim()
    other = Executor(lab.store, lab.bundle, lab.adapter, lab.clock, worker_id="worker-b")
    assert other.run_once() == []
    assert lab.adapter.call_count("apply", "lab-ws-001") == 0


def test_emergency_stop_halts_worker_cancels_queue_and_keeps_containment(lab):
    contained = lab.contain()
    lab.ops.set_emergency_stop(lab.p["admin-1"], engaged=True, reason="drill")
    assert lab.executor.run_once()[0]["status"] == "halted"
    with pytest.raises(Conflict, match="emergency stop"):
        lab.ops.request_recovery(lab.p["analyst-1"], contained, criteria=lab.criteria(), reason="x")
    assert lab.sql("SELECT state FROM containments")[0][0] == "active"


def test_emergency_stop_cancels_queued_isolation(make_lab):
    lab = make_lab(response={"max_concurrent_isolations": 5})
    case_id = approved(lab)
    out = lab.ops.set_emergency_stop(lab.p["admin-1"], engaged=True, reason="drill")
    assert len(out["cancelled_actions"]) == 1 and lab.state(case_id) == "failed"
    lab.ops.set_emergency_stop(lab.p["admin-1"], engaged=False, reason="drill over")
    assert lab.executor.run_once() == []
    assert lab.adapter.call_count("apply", "lab-ws-001") == 0


def test_kill_switch_file_halts_worker_and_blocks_proposals(lab):
    case_id = approved(lab)
    lab.bundle.emergency_stop_file.parent.mkdir(parents=True, exist_ok=True)
    lab.bundle.emergency_stop_file.write_text("on")
    assert lab.executor.run_once()[0]["status"] == "halted"
    assert lab.adapter.call_count("apply", "lab-ws-001") == 0
    other = lab.corroborate(asset="lab-ws-002", ip="10.66.10.40")
    failed = {c["name"] for c in lab.proposal(other)["decision"]["checks"] if not c["passed"]}
    assert "no_emergency_stop" in failed
    lab.bundle.emergency_stop_file.unlink()
    assert lab.executor.run_once()[0]["status"] == "verified" and lab.state(case_id) == "verified"


def test_approved_action_past_deadline_expires(lab):
    case_id = approved(lab)
    lab.clock.advance(901)
    assert lab.executor.run_once() == []
    assert lab.sql("SELECT status FROM actions")[0][0] == "expired" and lab.state(case_id) == "failed"


def test_concurrent_incidents_second_approval_refused(make_lab):
    lab = make_lab()
    a = lab.corroborate()
    b = lab.corroborate(asset="lab-ws-002", ip="10.66.10.40")
    lab.decide(lab.proposal(a))
    with pytest.raises(Conflict, match="limit"):
        lab.decide(lab.proposal(b))
    assert lab.executor.run_once()[0]["status"] == "verified"
    assert lab.sql("SELECT COUNT(*) FROM containments WHERE state='active'")[0][0] == 1


def test_false_positive_cancels_pending_and_closes(lab):
    case_id = lab.corroborate()
    out = lab.ops.false_positive(lab.p["analyst-1"], case_id, rationale="authorized red-team exercise")
    assert out["result"] == "closed" and lab.state(case_id) == "closed"
    assert lab.proposal(case_id)["status"] == "cancelled"
    assert lab.executor.run_once() == []


def test_false_positive_on_contained_case_needs_approved_release(lab):
    case_id = lab.contain()
    out = lab.ops.false_positive(lab.p["analyst-1"], case_id, rationale="benign admin script")
    assert "containment remains" in out["result"] and lab.state(case_id) == "verified"
    assert lab.ops.metrics(lab.p["analyst-1"])["false_containment_count"] == 1
    assert lab.recover(case_id)[0]["status"] == "verified" and lab.state(case_id) == "closed"
