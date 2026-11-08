import sqlite3
from datetime import timedelta

import pytest

from agent_core.approvals import ApprovalError, Principal
from agent_core.models import Task
from policy_engine import ActionRequest

REASON = "Read the full post text; it is accurate and on-brand."


def publish_request(text="Hello Ontario.\n\nCLEARGLASS: See Through Everything"):
    return ActionRequest(agent_id="growth.social-media", action_type="content.publish", params={"text": text})


def held(office):
    result = office.perform(publish_request())
    assert result.status == "waiting_approval"
    return result.approval


def test_agents_cannot_approve(office):
    approval = held(office)
    agent = Principal("growth.social-media", "agent", "agent")
    with pytest.raises(ApprovalError, match="human operator"):
        office.desk.decide(approval.id, agent, "approve", REASON)
    assert office.audit.events(event_type="approval.refused_principal")


def test_viewer_role_cannot_approve(office):
    approval = held(office)
    with pytest.raises(ApprovalError):
        office.desk.decide(approval.id, Principal("viewer", "human", "viewer"), "approve", REASON)


def test_reason_is_required(office, operator):
    approval = held(office)
    with pytest.raises(ApprovalError, match="reason"):
        office.desk.decide(approval.id, operator, "approve", "ok")


def test_approved_payload_executes_once_and_only_that_payload(office, operator):
    approval = held(office)
    office.desk.decide(approval.id, operator, "approve", REASON)
    # A different payload under the same approval id is refused.
    tampered = publish_request("Different text")
    tampered.approval_id = approval.id
    denied = office.perform(tampered)
    assert denied.status == "denied" and "differs" in denied.error
    # The exact payload executes, through the dry-run connector, bound to the digest.
    exact = publish_request()
    exact.approval_id = approval.id
    done = office.perform(exact)
    assert done.status == "completed"
    receipt = done.output["receipt"]
    assert receipt["mode"] == "dry_run" and receipt["action_digest"] == approval.action_digest
    assert office.desk.get(approval.id).status == "executed"
    # Replaying the approval is refused.
    again = office.perform(exact)
    assert again.status == "denied"


def test_modify_rebinds_the_digest_and_reevaluates(office, operator):
    approval = held(office)
    with pytest.raises(ApprovalError, match="existing parameters"):
        office.desk.decide(approval.id, operator, "modify", REASON, {"recipients": ["x@example.com"]})
    out = office.desk.decide(
        approval.id, operator, "modify", REASON, {"text": "Edited.\n\nCLEARGLASS: See Through Everything"}
    )
    assert out.status == "approved" and out.approved_digest != out.action_digest
    assert out.approved_action["params"]["text"].startswith("Edited.")
    assert out.decisions[-1]["modifications"] == {"text": "Edited.\n\nCLEARGLASS: See Through Everything"}


def test_double_decision_is_refused(office, operator):
    approval = held(office)
    office.desk.decide(approval.id, operator, "reject", REASON)
    with pytest.raises(ApprovalError, match="only pending"):
        office.desk.decide(approval.id, operator, "approve", REASON)


def test_decision_history_is_append_only(office, operator):
    approval = held(office)
    office.desk.decide(approval.id, operator, "approve", REASON)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        office.store.conn.execute("UPDATE approval_decisions SET reason = 'changed'")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        office.store.conn.execute("DELETE FROM approval_decisions")


def test_expired_approvals_cannot_be_decided_or_executed(office, operator):
    approval = held(office)
    office.clock.advance(timedelta(hours=office.policy.approval_ttl_hours + 1))
    assert office.desk.get(approval.id).status == "expired"
    with pytest.raises(ApprovalError):
        office.desk.decide(approval.id, operator, "approve", REASON)


def test_rejection_cancels_the_task_and_blocks_downstream(ran, operator):
    office, result = ran
    approval_id = result["approvals_pending"][0]
    office.decide_approval(approval_id, operator, "reject", "Not this week; revisit the opening line.")
    task = office.store.get(Task, office.desk.get(approval_id).task_id)
    assert task.status == "cancelled" and "rejected by operator" in task.error
    assert not office.audit.events(event_type="action.executed", subject=task.id)


def test_approval_resumes_the_workflow(ran, operator):
    office, result = ran
    approval_id = result["approvals_pending"][0]
    office.decide_approval(approval_id, operator, "approve", REASON)
    task = office.store.get(Task, office.desk.get(approval_id).task_id)
    assert task.status == "completed"
    trace = task.output["governance"]["trace"]
    assert [s["state"] for s in trace] == ["pass"] * 9
