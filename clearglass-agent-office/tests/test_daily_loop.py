"""The first demo, as specified: 8 agents across 4 departments, one engineering
mission, one marketing mission, one security review, one revenue research task,
one approval request, one executive briefing, and one end-of-day report."""

from agent_core.models import Mission, Report, Task
from agent_core.reports import compute_kpis
from apps.worker.daily_loop import run_daily_loop
from tests.conftest import DEMO


def test_demo_shape(ran):
    office, result = ran
    assert len(result["agents_involved"]) == 8
    assert result["departments_involved"] == ["eng", "exec", "growth", "revenue"]
    missions = {m.key: m for m in office.store.list(Mission)}
    assert set(missions) == {
        "eng-readiness-probe",
        "growth-authority-week",
        "sec-governance-review",
        "rev-lead-research",
    }
    assert len(result["approvals_pending"]) == 1
    assert office.desk.get(result["approvals_pending"][0]).action_type == "content.publish"
    kinds = [r.kind for r in office.store.list(Report)]
    assert kinds.count("briefing") == 1 and kinds.count("eod") == 1 and kinds.count("security_review") == 1
    assert result["audit"]["ok"]


def test_every_task_went_through_the_gate(ran):
    office, _ = ran
    for task in office.store.list(Task):
        trace = task.output["governance"]["trace"]
        assert [s["step"] for s in trace] == list(range(1, 10)), task.key
    statuses = {t.key: t.status for t in office.store.list(Task)}
    assert statuses.pop("publish") == "waiting_approval"
    assert set(statuses.values()) == {"completed"}


def test_untrusted_input_is_quarantined_not_obeyed(ran):
    office, _ = ran
    collect = next(t for t in office.store.list(Task) if t.key == "collect")
    quarantined = collect.output["artifact"]["quarantined"]
    assert [q["id"] for q in quarantined] == ["p-005"]
    score = next(t for t in office.store.list(Task) if t.key == "score")
    assert "p-005" not in {s["id"] for s in score.output["artifact"]["scored"]}
    assert any(m.kind == "escalation" and m.recipient == "exec.risk-compliance" for m in office.messages())
    # No email was sent and no outreach action ran.
    executed = office.audit.events(event_type="action.executed", limit=1000)
    assert not [e for e in executed if e["payload"]["action_type"] in ("outreach.send", "email.send")]


def test_scoring_is_transparent_and_gated(ran):
    office, _ = ran
    score = next(t for t in office.store.list(Task) if t.key == "score").output["artifact"]
    names = {s["id"] for s in score["shortlist"]}
    assert names == {"p-001", "p-002", "p-003", "p-004"}  # Alberta and the 410-employee record are out
    for s in score["scored"]:
        assert sum(r["points"] for r in s["rubric"]) == s["score"]


def test_security_review_passes_every_control_test(ran):
    office, _ = ran
    review = office.latest_report("security_review")
    assert review.metrics["control_tests"] == review.metrics["control_tests_passed"] >= 18
    assert not [f for f in review.sections["findings"] if f["severity"] in ("critical", "high")]


def test_kpis_are_measured_not_invented(ran):
    office, _ = ran
    k = compute_kpis(office)
    assert k["risk"]["external_actions_without_approval"] == 0
    assert k["pipeline"]["qualified_leads"] == 4 and k["pipeline"]["is_sample_data"] is True
    assert k["deployments"]["executed"] == 0 and k["deployments"]["success_rate"] is None  # no data, not 100%
    assert k["approvals"]["median_decision_minutes"] is None


def test_loop_is_idempotent_for_missions(ran):
    office, _ = ran
    before = office.store.count(Mission)
    second = run_daily_loop(office, DEMO)
    assert office.store.count(Mission) == before
    assert second["audit"]["ok"]
    assert len(second["approvals_pending"]) == 1


def test_briefing_names_the_pending_decision(ran):
    office, result = ran
    eod = office.latest_report("eod")
    assert [a["id"] for a in eod.sections["approvals"]["pending"]] == result["approvals_pending"]
    assert eod.sections["audit"]["ok"]
