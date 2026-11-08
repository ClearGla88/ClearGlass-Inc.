import pytest

from agent_core.approvals import ApprovalError, Principal
from agent_core.models import Task
from apps.worker.daily_loop import run_daily_loop
from policy_engine import ActionRequest
from tests.conftest import DEMO

REASON = "Drill: confirm the stop halts everything"


def test_stop_pauses_cancels_preserves_and_records(ran, operator):
    office, result = ran
    tasks_before = {t.id: t.status for t in office.store.list(Task)}
    memory_before = len(office.memory.all())
    state = office.emergency_stop(operator, REASON)

    assert state["halted"] and state["incident_id"]
    assert all(a.status in ("paused", "retired") for a in office.agents())
    approval = office.desk.get(result["approvals_pending"][0])
    assert approval.status == "cancelled" and approval.decisions[-1]["decision"] == "cancelled"
    held = office.store.get(Task, approval.task_id)
    assert held.status == "blocked" and "emergency stop" in held.error
    # State preserved: nothing deleted, only the held task changed.
    after = {t.id: t.status for t in office.store.list(Task)}
    assert set(after) == set(tasks_before)
    assert [k for k in after if after[k] != tasks_before[k]] == [held.id]
    assert len(office.memory.all()) == memory_before
    incident = office.store.get(type(office.latest_report("incident")), state["incident_id"])
    assert incident.kind == "incident" and incident.sections["approvals_cancelled"] == [approval.id]
    assert any(m.subject == "EMERGENCY STOP ENGAGED" for m in office.messages())
    assert office.audit.events(event_type="emergency.engaged")
    assert office.audit.verify().ok


def test_nothing_runs_while_halted(ran, operator):
    office, _ = ran
    office.emergency_stop(operator, REASON)
    r = office.perform(ActionRequest(agent_id="growth.content-writer", action_type="content.draft", params={}))
    assert r.status == "denied" and "emergency stop" in r.error
    assert run_daily_loop(office, DEMO)["skipped"]
    approval = office.perform(
        ActionRequest(agent_id="growth.social-media", action_type="content.publish", params={"text": "x"})
    )
    assert approval.status == "denied"


def test_stop_requires_a_human_and_a_reason(office, operator):
    with pytest.raises(ApprovalError):
        office.emergency_stop(Principal("eng.devops", "agent", "agent"), REASON)
    with pytest.raises(ApprovalError):
        office.emergency_stop(operator, "stop")


def test_release_restores_agents(ran, operator):
    office, _ = ran
    office.emergency_stop(operator, REASON)
    with pytest.raises(ApprovalError):
        office.release_emergency_stop(operator, "ok")
    state = office.release_emergency_stop(operator, "Drill complete; no findings.")
    assert not state["halted"]
    assert all(a.status == "idle" for a in office.agents())
    assert office.audit.events(event_type="emergency.released")
