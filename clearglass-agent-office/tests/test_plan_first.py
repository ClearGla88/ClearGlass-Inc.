"""Plan-first: the stored revenue plan, its contract, and the mission mode that limits its first cycle."""

import copy
import json

import pytest

import office as cli
from agent_core.office import OfficeError
from plan_contract import check_approvals, check_plan, load_json, readiness
from policy_engine import ActionRequest, PolicyError, parse_policy
from tests.conftest import ROOT

PLAN_PATH = ROOT / "plans" / "revenue" / "clearglassinc-plan-first.json"
APPROVALS_PATH = ROOT / "plans" / "revenue" / "clearglassinc-plan-first.approvals.json"
TEMPLATE_PATH = ROOT / "plans" / "revenue" / "market-validation-mission.json"
PLANS = {"change_plan": "c", "rollback_plan": "r", "verification_plan": "v"}


def gate(office, agent, action, params=None, **kw):
    return office.evaluate(ActionRequest(agent_id=agent, action_type=action, params=params or {}, **kw))


def plan_first_mission(office, tasks=None, **kw):
    spec = {
        "title": "Plan-first test mission",
        "objective": "research and drafts only",
        "department": "revenue",
        "owner": "revenue.sales-strategist",
        "mode": "plan_first",
        "tasks": tasks
        or [
            {
                "key": "note",
                "title": "Draft a note",
                "assignee": "revenue.proposal-writer",
                "action": {"type": "docs.draft", "params": {"title": "Note"}},
            }
        ],
        **kw,
    }
    return office.create_mission(spec, created_by="operator.founder")


@pytest.fixture
def plan():
    return load_json(PLAN_PATH)


@pytest.fixture
def approvals():
    return load_json(APPROVALS_PATH)


# -- the mission mode ---------------------------------------------------------------------------


def test_plan_first_mode_is_defined_by_policy(office):
    rules = office.policy.mission_modes["plan_first"]
    assert rules["allowed_levels"] == ("read", "propose")
    assert rules["deny_spend"] is True
    assert office.policy.version == "2026.11.13-1"


def test_plan_first_mission_allows_research_analysis_and_drafts(office):
    m = plan_first_mission(office)
    allowed = [
        ("revenue.proposal-writer", "docs.draft", {"title": "x"}),
        ("revenue.sales-strategist", "outreach.draft", {"prospect": "p", "channel": "email"}),
        ("revenue.pricing-analyst", "pricing.model", {}),
        ("exec.strategy", "analysis.run", {}),
    ]
    for agent, action, params in allowed:
        decision = gate(office, agent, action, params, mission_id=m.id)
        assert decision.outcome == "allow", (action, decision.reasons)


def test_plan_first_mission_refuses_send_publish_record_writes_and_deploys(office):
    m = plan_first_mission(office)
    refused = [
        ("revenue.sales-strategist", "outreach.send", {"recipients": ["a@example.org"]}),
        ("revenue.customer-success", "email.send", {"recipients": ["a@example.org"]}),
        ("content.social", "content.publish", {"channel": "linkedin"}),
        ("revenue.lead-research", "data.update_internal", {"record": "x"}),
        ("eng.devops", "deploy.staging", {"environment": "staging"}),
    ]
    for agent, action, params in refused:
        if office.agent(agent) is None:
            continue
        decision = gate(office, agent, action, params, mission_id=m.id)
        assert decision.outcome == "deny", action
        assert any("plan_first mission" in r for r in decision.reasons), (action, decision.reasons)


def test_an_approval_does_not_unlock_an_external_action_in_plan_first_mode(office, operator):
    """The mode denies; it does not queue for approval. There is nothing for an operator to approve."""
    m = plan_first_mission(office)
    request = ActionRequest(
        agent_id="revenue.sales-strategist",
        action_type="outreach.send",
        params={"recipients": ["a@example.org"], "channel": "email"},
        mission_id=m.id,
    )
    result = office.perform(request)
    assert result.status == "denied"
    assert office.desk.list("pending") == []


def test_plan_first_mission_cannot_spend(office):
    m = plan_first_mission(office)
    spend = gate(office, "revenue.pricing-analyst", "pricing.model", {"amount_cents": 500}, mission_id=m.id)
    assert spend.outcome == "deny" and any("no spending" in r for r in spend.reasons)
    bad = gate(office, "revenue.pricing-analyst", "pricing.model", {"amount_cents": "lots"}, mission_id=m.id)
    assert bad.outcome == "deny"


def test_internal_memory_and_messages_still_work(office):
    m = plan_first_mission(office)
    for action in ("memory.write_task", "message.internal"):
        spec = office.policy.spec(action)
        agent = next(
            a.id
            for a in office.agents()
            if a.permissions.get(spec.domain) in ("write", "execute")
            and any(action in office.tools.get(t).actions for t in a.tools)
        )
        decision = gate(office, agent, action, {"note": "x", "body": "x", "to": "exec.chief-of-staff"}, mission_id=m.id)
        assert not any("plan_first mission" in r for r in decision.reasons), (action, decision.reasons)


def test_same_actions_are_not_blocked_by_mode_in_a_production_mission(office):
    spec = {
        "title": "Production mission",
        "objective": "control",
        "department": "revenue",
        "owner": "revenue.sales-strategist",
        "tasks": [
            {
                "key": "n",
                "title": "n",
                "assignee": "revenue.proposal-writer",
                "action": {"type": "docs.draft", "params": {"title": "n"}},
            }
        ],
    }
    m = office.create_mission(spec, created_by="operator.founder")
    decision = gate(
        office, "revenue.sales-strategist", "outreach.send", {"recipients": ["a@example.org"]}, mission_id=m.id
    )
    assert not any("plan_first" in r for r in decision.reasons)


def test_unknown_mission_mode_is_refused(office):
    with pytest.raises(OfficeError, match="mode"):
        plan_first_mission(office, mode="growth_hack")


def test_policy_cannot_widen_a_restricted_mode(office):
    raw = copy.deepcopy(office.policy.raw)
    raw["mission_modes"]["plan_first"]["also_allowed_actions"] = ["outreach.send"]
    with pytest.raises(PolicyError, match="external or high risk"):
        parse_policy(raw)
    raw = copy.deepcopy(office.policy.raw)
    raw["mission_modes"]["production"] = raw["mission_modes"]["plan_first"]
    with pytest.raises(PolicyError, match="built in"):
        parse_policy(raw)
    raw = copy.deepcopy(office.policy.raw)
    raw["mission_modes"]["plan_first"]["reason"] = ""
    with pytest.raises(PolicyError, match="reason is required"):
        parse_policy(raw)
    raw = copy.deepcopy(office.policy.raw)
    raw["mission_modes"]["plan_first"]["allowed_levels"] = ["everything"]
    with pytest.raises(PolicyError, match="allowed_levels"):
        parse_policy(raw)


def test_a_mode_the_policy_no_longer_defines_fails_closed(office):
    m = plan_first_mission(office)
    raw = copy.deepcopy(office.policy.raw)
    del raw["mission_modes"]
    office.policy = parse_policy(raw)
    office.engine.policy = office.policy
    decision = gate(office, "revenue.proposal-writer", "docs.draft", {"title": "x"}, mission_id=m.id)
    assert decision.outcome == "deny" and any("not defined by this policy" in r for r in decision.reasons)


# -- the mission template -----------------------------------------------------------------------


def test_market_validation_template_runs_with_no_external_action(office):
    template = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))
    assert template["plan"] == PLAN_PATH.name
    spec = template["mission"]
    assert spec["mode"] == "plan_first"
    for task in spec["tasks"]:
        action = office.policy.spec(task["action"]["type"])
        assert action.level in ("read", "propose") and not action.external, task["key"]
    m = office.create_mission(spec, created_by="operator.founder")
    office.run_mission(m.id)
    detail = office.mission_detail(m.id)
    assert [t["status"] for t in detail["tasks"]] == ["completed"] * len(spec["tasks"])
    assert office.desk.list("pending") == []
    assert office.audit.verify().ok is True
    executed = [e for e in office.audit.events(newest_first=False, limit=5000) if e["event_type"] == "action.executed"]
    assert {e["payload"]["action_type"] for e in executed} == {"docs.draft"}


def test_template_with_a_send_step_does_not_send(office):
    spec = copy.deepcopy(json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))["mission"])
    spec["tasks"] = [
        {
            "key": "send",
            "title": "Send the sequence",
            "assignee": "revenue.sales-strategist",
            "action": {"type": "outreach.send", "params": {"recipients": ["a@example.org"], "channel": "email"}},
        }
    ]
    m = office.create_mission(spec, created_by="operator.founder")
    office.run_mission(m.id)
    detail = office.mission_detail(m.id)
    assert detail["tasks"][0]["status"] != "completed"
    assert office.desk.list("pending") == []
    events = office.audit.events(newest_first=False, limit=5000)
    assert not [e for e in events if e["event_type"] == "action.executed"]


# -- the stored plan and its contract -----------------------------------------------------------


def test_stored_plan_meets_the_contract_and_is_not_ready(plan, approvals):
    assert check_plan(plan) == []
    assert check_approvals(approvals, PLAN_PATH.name) == []
    blockers = readiness(plan, approvals)
    assert len(blockers) == 5
    assert blockers[0].startswith("plan approval is PENDING")
    assert plan["audit"]["approval_status"] == "PENDING"
    assert plan["meta"]["overall_confidence"] == "INSUFFICIENT"
    assert plan["source_register"] == [] and plan["audit"]["spend_to_date"] == "$0"


def _findings(plan, mutate):
    changed = copy.deepcopy(plan)
    mutate(changed)
    return check_plan(changed)


def test_contract_fails_closed_on_shape(plan):
    assert any("unknown field" in f for f in _findings(plan, lambda p: p.update(auto_execute=True)))
    assert any("missing field" in f for f in _findings(plan, lambda p: p.pop("red_team")))
    assert any("unknown field" in f for f in _findings(plan, lambda p: p["audit"].update(approved_by_agent="x")))
    assert any("must be one of" in f for f in _findings(plan, lambda p: p["audit"].update(approval_status="AUTO")))
    assert any("must be a date" in f for f in _findings(plan, lambda p: p["meta"].update(analysis_date="soon")))
    assert any(
        "must be true or false" in f for f in _findings(plan, lambda p: p["audit"].update(human_review_required="yes"))
    )


def test_confidence_cannot_outrun_evidence(plan):
    assert any(
        "must be INSUFFICIENT while source_register is empty" in f
        for f in _findings(plan, lambda p: p["meta"].update(overall_confidence="HIGH"))
    )
    assert any(
        "evidence_quality_score must be 0" in f
        for f in _findings(plan, lambda p: p["meta"].update(evidence_quality_score=80))
    )
    assert any(
        "higher than meta.overall_confidence" in f
        for f in _findings(plan, lambda p: p["executive_brief"].update(confidence="MEDIUM"))
    )
    assert any(
        "states a figure" in f
        for f in _findings(plan, lambda p: p["market_state"]["market_sizing"].update(estimate="$4.2B"))
    )
    assert any(
        "must be UNKNOWN" in f for f in _findings(plan, lambda p: p["market_state"].update(demand_direction="GROWING"))
    )
    assert any(
        "confidence above LOW needs evidence" in f
        for f in _findings(plan, lambda p: p["strategic_options"][0].update(confidence="HIGH"))
    )
    assert any(
        "needs at least one source" in f
        for f in _findings(plan, lambda p: p["competitive_landscape"].append({"name": "Some Glass Co"}))
    )


def test_verified_claims_need_two_registered_sources(plan):
    def verify_without_sources(p):
        p["evidence_ledger"][0].update(classification="VERIFIED", confidence="HIGH")

    assert any("at least two independent sources" in f for f in _findings(plan, verify_without_sources))

    def cite_unknown_source(p):
        p["evidence_ledger"][0].update(source_ids=["S1", "S2"])

    assert any("not in source_register" in f for f in _findings(plan, cite_unknown_source))
    assert any(
        "cannot carry confidence above LOW" in f
        for f in _findings(plan, lambda p: p["evidence_ledger"][1].update(confidence="MEDIUM"))
    )


def test_every_proposed_action_waits_for_a_named_human(plan):
    assert any(
        "approval_required must be true" in f
        for f in _findings(plan, lambda p: p["proposed_actions"][1].update(approval_required=False))
    )
    assert any(
        "approver is required" in f for f in _findings(plan, lambda p: p["proposed_actions"][0].update(approver=" "))
    )
    assert any(
        "rollback_plan is required" in f
        for f in _findings(plan, lambda p: p["proposed_actions"][0].update(rollback_plan=""))
    )
    assert any(
        "cannot propose spending" in f
        for f in _findings(plan, lambda p: p["proposed_actions"][0].update(estimated_cost="$250.00"))
    )
    assert any(
        "must be a dollar amount" in f
        for f in _findings(plan, lambda p: p["proposed_actions"][0].update(estimated_cost="cheap"))
    )


def test_nothing_may_have_run_before_approval(plan):
    assert any(
        "spend_to_date must be $0" in f for f in _findings(plan, lambda p: p["audit"].update(spend_to_date="$120"))
    )
    assert any(
        "tools_used must be empty" in f for f in _findings(plan, lambda p: p["audit"].update(tools_used=["hubspot"]))
    )
    assert any(
        "human_review_required must be true" in f
        for f in _findings(plan, lambda p: p["audit"].update(human_review_required=False))
    )


def test_plan_cannot_carry_a_credential(plan):
    fake = "sk" + "_live_" + "A1b2C3d4E5f6G7h8"
    findings = _findings(plan, lambda p: p["proposed_actions"][0].update(draft_content=f"use {fake}"))
    assert any("credential-shaped" in f for f in findings)
    assert not any(fake in f for f in findings)


def test_approvals_record_rules(approvals):
    assert any("is for" in f for f in check_approvals(approvals, "another-plan.json"))
    half = copy.deepcopy(approvals)
    half["required_before_first_cycle"][0]["status"] = "DECIDED"
    assert any("needs decision, decided_by and decided_at" in f for f in check_approvals(half))
    early = copy.deepcopy(approvals)
    early["required_before_first_cycle"][0]["decision"] = "facilities"
    assert any("must leave decision" in f for f in check_approvals(early))
    extra = copy.deepcopy(approvals)
    extra["auto_approve"] = True
    assert any("unknown field" in f for f in check_approvals(extra))


def _decided(plan, approvals):
    plan, approvals = copy.deepcopy(plan), copy.deepcopy(approvals)
    plan["audit"]["approval_status"] = "APPROVED"
    for item in approvals["required_before_first_cycle"]:
        item.update(status="DECIDED", decision="recorded", decided_by="operator.founder", decided_at="2026-11-13")
    return plan, approvals


def test_ready_only_when_approved_and_every_decision_is_made(plan, approvals):
    ready_plan, ready_approvals = _decided(plan, approvals)
    assert check_plan(ready_plan) == [] and check_approvals(ready_approvals) == []
    assert readiness(ready_plan, ready_approvals) == []
    assert len(readiness(ready_plan, approvals)) == 4
    assert len(readiness(plan, ready_approvals)) == 1
    assert any("no approvals record" in b for b in readiness(ready_plan, None))


def test_plan_check_command(plan, approvals, tmp_path, capsys):
    assert cli.main(["plan-check", str(PLAN_PATH)]) == 2
    assert "NOT READY" in capsys.readouterr().out

    ready_plan, ready_approvals = _decided(plan, approvals)
    ok = tmp_path / "clearglassinc-plan-first.json"
    ok.write_text(json.dumps(ready_plan), encoding="utf-8")
    (tmp_path / "clearglassinc-plan-first.approvals.json").write_text(json.dumps(ready_approvals), encoding="utf-8")
    assert cli.main(["plan-check", str(ok)]) == 0
    assert "authorizes nothing" in capsys.readouterr().out

    bad = tmp_path / "bad.json"
    broken = copy.deepcopy(plan)
    broken["proposed_actions"][0]["approval_required"] = False
    bad.write_text(json.dumps(broken), encoding="utf-8")
    assert cli.main(["plan-check", str(bad)]) == 1
    assert "INVALID" in capsys.readouterr().out
    assert cli.main(["plan-check", str(tmp_path / "missing.json")]) == 1
