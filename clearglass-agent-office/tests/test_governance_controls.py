"""Governance controls ported from agent-office/ (2026-11-08). One section per control."""

import copy
import json
import sqlite3
from datetime import timedelta

import pytest

from agent_core.approvals import ApprovalError, Principal
from agent_core.config import ConfigError, load_config
from agent_core.models import Approval, Mission, Report, Task
from agent_core.office import OfficeError
from agent_core.sandbox_runner import SandboxError, SandboxRunner
from agent_core.security_audit import run_security_audit
from policy_engine import ActionRequest, PolicyError, parse_policy
from tests.conftest import ROOT

PLANS = {"change_plan": "ship r2", "rollback_plan": "back to r1", "verification_plan": "check /ready"}
REASON = "Checked the payload against the brief."
SUITES = {
    "pass": {"argv": ["{python}", "-c", "print('ok')"], "timeout_s": 60},
    "fail": {"argv": ["{python}", "-c", "import sys; sys.exit(3)"], "timeout_s": 60},
    "env": {
        "argv": ["{python}", "-c", "import os; print(sorted(k for k in os.environ if 'SECRET' in k))"],
        "timeout_s": 60,
    },
}


def gate(office, agent, action, params=None, **kw):
    return office.evaluate(ActionRequest(agent_id=agent, action_type=action, params=params or {}, **kw))


def mission(tasks, **kw):
    return {
        "title": "Control test mission",
        "objective": "exercise one control",
        "department": "eng",
        "owner": "eng.software-architect",
        "tasks": tasks,
        **kw,
    }


# 1. Grant limits -------------------------------------------------------------------------


def _finance_analyst(office, operator, **grant_kw):
    office.update_agent(
        "revenue.pricing-analyst",
        {"tools": [*office.agent("revenue.pricing-analyst").tools, "finance.ledger"]},
        operator,
    )
    return office.grant("revenue.pricing-analyst", "finance", "execute", operator, **grant_kw)


def test_spend_cap_is_enforced(office, operator):
    _finance_analyst(office, operator, constraints={"spend_limit_cents": 10_000})
    ok = gate(office, "revenue.pricing-analyst", "finance.purchase", {"amount_cents": 5_000, **PLANS})
    over = gate(office, "revenue.pricing-analyst", "finance.purchase", {"amount_cents": 20_000, **PLANS})
    assert ok.outcome == "approval_required" and ok.tier == "critical"
    assert over.outcome == "deny" and any("spend limit" in r for r in over.reasons)


def test_allow_list_from_config(office):
    assert (
        gate(office, "growth.social-media", "content.publish", {"text": "x", "channel": "x"}).outcome
        == "approval_required"
    )
    bad = gate(office, "growth.social-media", "content.publish", {"text": "x", "channel": "tiktok"})
    missing = gate(office, "growth.social-media", "content.publish", {"text": "x"})
    assert bad.outcome == "deny" and any("allow-list" in r for r in bad.reasons)
    assert missing.outcome == "deny" and any("required by the grant" in r for r in missing.reasons)


def test_list_values_must_all_be_allowed(office, operator):
    office.grant(
        "revenue.sales-strategist",
        "outreach",
        "execute",
        operator,
        constraints={"payload_allowlist": {"recipients": ["ops@sample-clinic.example"]}},
    )
    one = gate(office, "revenue.sales-strategist", "outreach.send", {"recipients": ["ops@sample-clinic.example"]})
    two = gate(
        office,
        "revenue.sales-strategist",
        "outreach.send",
        {"recipients": ["ops@sample-clinic.example", "someone@else.example"]},
    )
    assert one.outcome == "approval_required" and two.outcome == "deny"


def test_grant_expiry(office, operator):
    soon = (office.clock.now() + timedelta(hours=1)).isoformat()
    _finance_analyst(office, operator, expires_at=soon)
    assert (
        gate(office, "revenue.pricing-analyst", "finance.purchase", {"amount_cents": 1, **PLANS}).outcome
        == "approval_required"
    )
    office.clock.advance(timedelta(hours=2))
    expired = gate(office, "revenue.pricing-analyst", "finance.purchase", {"amount_cents": 1, **PLANS})
    assert expired.outcome == "deny" and any("expired" in r for r in expired.reasons)


def test_grant_revocation_and_regrant(office, operator):
    office.revoke_grant("growth.social-media", "social", operator, "Pausing publishing during review.")
    d = gate(office, "growth.social-media", "content.publish", {"text": "x", "channel": "linkedin"})
    assert d.outcome == "deny" and any("revoked" in r for r in d.reasons)
    assert "social" not in office.agent("growth.social-media").permissions
    office.grant(
        "growth.social-media",
        "social",
        "execute",
        operator,
        constraints={"payload_allowlist": {"channel": ["linkedin"]}},
    )
    assert (
        gate(office, "growth.social-media", "content.publish", {"text": "x", "channel": "linkedin"}).outcome
        == "approval_required"
    )
    kinds = [e["event_type"] for e in office.audit.events(subject="growth.social-media", newest_first=False)]
    assert "grant.revoked" in kinds and "grant.issued" in kinds


def test_unrelated_edits_keep_grant_limits(office, operator):
    office.update_agent("growth.social-media", {"objective": "Schedule approved posts for LinkedIn."}, operator)
    grant = next(g for g in office.grants("growth.social-media") if g.domain == "social")
    assert grant.constraints == {"payload_allowlist": {"channel": ["linkedin", "x"]}}


def test_bad_grant_limits_are_refused(office, operator, tmp_path):
    with pytest.raises(OfficeError, match="unknown constraint"):
        office.grant("revenue.sales-strategist", "outreach", "execute", operator, constraints={"daily_cap": 3})
    with pytest.raises(OfficeError, match="ISO 8601"):
        office.grant("revenue.sales-strategist", "outreach", "execute", operator, expires_at="tomorrow")
    import shutil

    shutil.copytree(ROOT / "config", tmp_path / "config")
    org = json.loads((tmp_path / "config" / "org.json").read_text())
    org["agents"][0]["grant_constraints"] = {"finance": {"spend_limit_cents": 10}}
    (tmp_path / "config" / "org.json").write_text(json.dumps(org))
    with pytest.raises(ConfigError, match="not granted"):
        load_config(tmp_path / "config")


# 2. Risk escalation ---------------------------------------------------------------------


def test_sensitive_data_raises_to_high(office):
    for value in ("pii", "PII", "regulated"):
        d = gate(office, "exec.operations", "data.update_internal", {"data_classification": value})
        assert d.tier == "high" and d.outcome == "approval_required", value
    assert gate(office, "exec.operations", "data.update_internal", {"data_classification": "internal"}).tier == "medium"


def test_irreversible_raises_to_high_but_only_for_false(office):
    assert gate(office, "exec.operations", "data.update_internal", {"reversible": False}).tier == "high"
    assert gate(office, "exec.operations", "data.update_internal", {"reversible": 0}).tier == "medium"
    assert gate(office, "exec.operations", "data.update_internal", {"reversible": True}).tier == "medium"


def test_any_payment_is_critical(office):
    assert office.policy.spec("finance.purchase").tier == "critical"
    money = gate(office, "growth.content-writer", "content.draft", {"posts": [], "amount_cents": 100})
    assert money.tier == "critical" and money.outcome == "deny"  # content.studio is not cleared for critical
    junk = gate(office, "growth.content-writer", "content.draft", {"posts": [], "amount_cents": "100"})
    assert junk.outcome == "deny" and any("non-negative integer" in r for r in junk.reasons)


def test_policy_loader_refuses_weak_or_malformed_rules():
    raw = json.loads((ROOT / "config" / "policy.json").read_text())
    weak = copy.deepcopy(raw)
    weak["actions"]["finance.purchase"]["tier"] = "high"
    with pytest.raises(PolicyError, match="must be critical"):
        parse_policy(weak)
    bad = copy.deepcopy(raw)
    bad["escalation_modifiers"].append(
        {"id": "x", "param": "p", "op": "matches", "applies_to": "all", "min_tier": "high"}
    )
    with pytest.raises(PolicyError, match="op must be one of"):
        parse_policy(bad)
    no_gate = copy.deepcopy(raw)
    no_gate["actions"]["deploy.production"].pop("requires_test_evidence")
    with pytest.raises(PolicyError, match="test evidence"):
        parse_policy(no_gate)


# 3. Sandbox runner and the production deploy gate ----------------------------------------


def test_runner_refuses_commands_outside_the_allow_list(tmp_path, monkeypatch):
    with pytest.raises(SandboxError, match="must start with"):
        SandboxRunner(tmp_path, {"bad": {"argv": ["bash", "-c", "true"]}})
    runner = SandboxRunner(ROOT, SUITES)
    with pytest.raises(SandboxError, match="unknown sandbox suite"):
        runner.run("rm -rf /")
    monkeypatch.setenv("OFFICE_SECRET_SOCIAL_LINKEDIN", "do-not-leak")
    out = runner.run("env")
    assert out["passed"] and "OFFICE_SECRET" not in out["output_tail"]
    assert runner.run("pass")["passed"] and not runner.run("fail")["passed"]


def _deploy_mission(office, suite):
    office.sandbox = SandboxRunner(ROOT, SUITES)
    return office.create_mission(
        mission(
            [
                {
                    "key": "tests",
                    "title": "Run the sandbox suite",
                    "assignee": "eng.qa",
                    "action": {"type": "tests.run_sandbox", "params": {"suite": suite}},
                },
                {
                    "key": "deploy",
                    "title": "Deploy to production",
                    "assignee": "eng.devops",
                    "depends_on": ["tests"],
                    "action": {
                        "type": "deploy.production",
                        "params": {
                            **PLANS,
                            "environment": "production",
                            "release": "r2",
                            "test_evidence": {"$from": "tests", "path": "artifact.run_id"},
                        },
                    },
                },
            ]
        ),
        created_by="operator.founder",
    )


def test_passing_run_unlocks_the_deploy_approval(office, operator):
    m = _deploy_mission(office, "pass")
    office.run_mission(m.id)
    tasks = {t.key: t for t in office.store.list(Task)}
    assert tasks["tests"].status == "completed" and tasks["tests"].output["artifact"]["passed"] is True
    assert tasks["deploy"].status == "waiting_approval"
    done = office.decide_approval(tasks["deploy"].approval_id, operator, "approve", REASON)
    assert done.status == "executed" and done.execution["receipt"]["mode"] == "dry_run"


def test_failing_run_blocks_the_deploy(office):
    m = _deploy_mission(office, "fail")
    office.run_mission(m.id)
    tasks = {t.key: t for t in office.store.list(Task)}
    assert tasks["tests"].status == "failed" and "failed" in tasks["tests"].error
    assert tasks["deploy"].status == "blocked"


def test_evidence_must_come_from_the_same_mission(office):
    m = _deploy_mission(office, "pass")
    office.run_mission(m.id)
    run_id = next(t.id for t in office.store.list(Task) if t.key == "tests")
    other = office.create_mission(
        mission(
            [
                {
                    "key": "noop",
                    "title": "noop",
                    "assignee": "eng.software-architect",
                    "action": {"type": "docs.draft", "params": {"title": "x"}},
                }
            ]
        ),
        created_by="operator.founder",
    )
    elsewhere = gate(
        office,
        "eng.devops",
        "deploy.production",
        {**PLANS, "environment": "production", "test_evidence": run_id},
        mission_id=other.id,
    )
    assert elsewhere.outcome == "deny" and any("not a sandbox test run in this mission" in r for r in elsewhere.reasons)
    no_mission = gate(
        office, "eng.devops", "deploy.production", {**PLANS, "environment": "production", "test_evidence": run_id}
    )
    assert no_mission.outcome == "deny"


# 4. Mission lifecycle ---------------------------------------------------------------------


def _simple_mission(office, **kw):
    return office.create_mission(
        mission(
            [
                {
                    "key": "a",
                    "title": "a",
                    "assignee": "eng.software-architect",
                    "action": {"type": "docs.draft", "params": {"title": "a"}},
                },
                {
                    "key": "b",
                    "title": "b",
                    "assignee": "eng.software-architect",
                    "depends_on": ["a"],
                    "action": {"type": "docs.draft", "params": {"title": "b"}},
                },
            ],
            **kw,
        ),
        created_by="operator.founder",
    )


def test_pause_resume_cancel(office, operator):
    m = _simple_mission(office)
    office.set_mission_lifecycle(m.id, "pause", operator, "Waiting on the client's answer.")
    with pytest.raises(OfficeError, match="paused"):
        office.run_mission(m.id)
    d = gate(office, "eng.software-architect", "docs.draft", {"title": "x"}, mission_id=m.id)
    assert d.outcome == "deny" and any("is paused" in r for r in d.reasons)
    office.set_mission_lifecycle(m.id, "resume", operator, "Client answered; continue.")
    assert office.run_mission(m.id)["completed"] == 2
    m2 = _simple_mission(office)
    office.set_mission_lifecycle(m2.id, "cancel", operator, "Scope moved to next quarter.")
    statuses = {t.status for t in office.store.list(Task, lambda t: t.mission_id == m2.id)}
    assert statuses == {"cancelled"}
    assert office.store.get(Mission, m2.id).status == "cancelled"
    with pytest.raises(OfficeError, match="cannot resume"):
        office.set_mission_lifecycle(m2.id, "resume", operator, "Changed my mind again.")


def test_lifecycle_needs_a_human_and_a_reason(office, operator):
    m = _simple_mission(office)
    with pytest.raises(ApprovalError):
        office.set_mission_lifecycle(m.id, "pause", Principal("eng.devops", "agent", "agent"), REASON)
    with pytest.raises(ApprovalError):
        office.set_mission_lifecycle(m.id, "pause", operator, "no")


def test_cancel_cancels_pending_approvals(office, operator):
    m = office.create_mission(
        {
            **mission(
                [
                    {
                        "key": "pub",
                        "title": "publish",
                        "assignee": "growth.social-media",
                        "action": {"type": "content.publish", "params": {"text": "x", "channel": "linkedin"}},
                    }
                ]
            ),
            "department": "growth",
            "owner": "growth.social-media",
        },
        created_by="operator.founder",
    )
    office.run_mission(m.id)
    approval = office.desk.list("pending")[0]
    office.set_mission_lifecycle(m.id, "cancel", operator, "Campaign withdrawn by the client.")
    assert office.desk.get(approval.id).status == "cancelled"


def test_paused_mission_approval_cannot_be_decided(office, operator):
    m = office.create_mission(
        {
            **mission(
                [
                    {
                        "key": "pub",
                        "title": "publish",
                        "assignee": "growth.social-media",
                        "action": {"type": "content.publish", "params": {"text": "x", "channel": "linkedin"}},
                    }
                ]
            ),
            "department": "growth",
            "owner": "growth.social-media",
        },
        created_by="operator.founder",
    )
    office.run_mission(m.id)
    approval = office.desk.list("pending")[0]
    office.set_mission_lifecycle(m.id, "pause", operator, "Hold until the client confirms.")
    with pytest.raises(ApprovalError, match="is paused"):
        office.decide_approval(approval.id, operator, "approve", REASON)
    assert office.desk.get(approval.id).status == "pending"
    assert office.store.get(Task, approval.task_id).status == "waiting_approval"
    assert not office.audit.events(event_type="action.executed", subject=approval.task_id)
    office.set_mission_lifecycle(m.id, "resume", operator, "Client confirmed in writing.")
    done = office.decide_approval(approval.id, operator, "approve", REASON)
    assert done.status == "executed" and done.execution["receipt"]["mode"] == "dry_run"
    assert office.audit.verify().ok


def test_simulation_missions_cannot_touch_production(office):
    sim = _simple_mission(office, mode="simulation")
    staging = gate(office, "eng.devops", "deploy.staging", {"environment": "staging"}, mission_id=sim.id)
    assert staging.outcome == "deny" and any("simulation mission" in r for r in staging.reasons)
    commit = gate(office, "eng.backend", "code.commit_branch", {"target_environment": "production"}, mission_id=sim.id)
    assert commit.outcome == "deny"
    assert gate(office, "eng.software-architect", "docs.draft", {"title": "x"}, mission_id=sim.id).outcome == "allow"
    with pytest.raises(OfficeError, match="mode"):
        _simple_mission(office, mode="chaos")


# 5. Execution intent and audit-failure incidents ----------------------------------------------


def test_intent_is_sealed_before_execution(office):
    r = office.perform(
        ActionRequest(agent_id="eng.software-architect", action_type="docs.draft", params={"title": "x"})
    )
    assert r.status == "completed"
    events = office.audit.events(newest_first=False, limit=1000)
    intent = next(e for e in events if e["event_type"] == "action.intent")
    executed = next(e for e in events if e["event_type"] == "action.executed")
    assert intent["seq"] < executed["seq"] and intent["payload"]["digest"] == executed["payload"]["digest"]


def test_no_intent_record_means_nothing_runs(office, monkeypatch):
    calls = []
    office.tools.register("docs.draft", lambda ctx: calls.append(1) or {"summary": "x", "artifact": {"a": 1}})
    real = office.audit.append

    def flaky(**kw):
        if kw["event_type"] == "action.intent":
            raise sqlite3.OperationalError("disk full")
        return real(**kw)

    monkeypatch.setattr(office.audit, "append", flaky)
    r = office.perform(
        ActionRequest(agent_id="eng.software-architect", action_type="docs.draft", params={"title": "x"})
    )
    assert r.status == "failed" and "nothing ran" in r.error and calls == []


def test_lost_outcome_opens_an_incident_and_the_review_flags_it(office, monkeypatch):
    real = office.audit.append

    def flaky(**kw):
        if kw["event_type"] == "action.executed":
            raise sqlite3.OperationalError("disk full")
        return real(**kw)

    monkeypatch.setattr(office.audit, "append", flaky)
    r = office.perform(
        ActionRequest(agent_id="eng.software-architect", action_type="docs.draft", params={"title": "x"})
    )
    monkeypatch.setattr(office.audit, "append", real)
    assert r.status == "completed" and r.incident_id
    incident = office.store.get(Report, r.incident_id)
    assert incident.kind == "incident" and incident.metrics["severity"] == "critical"
    assert any(m.subject.startswith("INCIDENT") for m in office.messages())
    review = run_security_audit(office, include_control_tests=False)
    assert any(f["title"] == "Execution started without a recorded outcome" for f in review["findings"])


# 6. Approval integrity -------------------------------------------------------------------------


def _publish(task_id=None, text="Hello.", channel="linkedin"):
    return ActionRequest(
        agent_id="growth.social-media",
        action_type="content.publish",
        params={"text": text, "channel": channel},
        task_id=task_id,
    )


def test_identical_pending_requests_are_merged(office):
    first = office.perform(_publish()).approval
    again = office.perform(_publish()).approval
    other_task = office.perform(_publish(task_id="task_other")).approval
    assert first.id == again.id and other_task.id != first.id
    assert office.audit.events(event_type="approval.reused")


def test_edited_approval_document_is_refused(office, operator):
    approval = office.perform(_publish()).approval
    doc = office.store.get(Approval, approval.id)
    doc.action["params"]["text"] = "Something the operator never saw."
    office.store.put(doc, office.clock.iso())
    with pytest.raises(ApprovalError, match="integrity"):
        office.desk.decide(approval.id, operator, "approve", REASON)
    assert office.audit.events(event_type="approval.integrity_failure")


def test_request_record_is_append_only(office):
    office.perform(_publish())
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        office.store.conn.execute("UPDATE approval_requests SET action = '{}'")


def test_database_allows_one_decision(office, operator):
    approval = office.perform(_publish()).approval
    office.desk.decide(approval.id, operator, "approve", REASON)
    with pytest.raises(sqlite3.IntegrityError):
        office.store.append_decision(
            approval_id=approval.id,
            decision="reject",
            reason=REASON,
            decided_by=operator.id,
            decided_at=office.clock.iso(),
            modifications=None,
            resulting_digest=None,
        )


def test_approval_is_consumed_before_the_tool_runs(office, operator):
    approval = office.perform(_publish()).approval
    office.desk.decide(approval.id, operator, "approve", REASON)
    calls = []

    def boom(ctx):
        calls.append(1)
        raise RuntimeError("connector down")

    office.tools.register("content.publish", boom)
    req = _publish()
    req.approval_id = approval.id
    assert office.perform(req).status == "failed" and calls == [1]
    retry = office.perform(req)  # the approval was used, even though the tool failed
    assert retry.status == "denied" and calls == [1]
    assert office.store.execution_of(approval.id) is not None
    with pytest.raises(ApprovalError, match="already been used"):
        office.desk.consume(office.desk.get(approval.id), approval.action_digest, None)


# 7. Shadow policies ------------------------------------------------------------------------------


def test_shadow_rules_are_reported_not_enforced(office):
    r = office.perform(
        ActionRequest(
            agent_id="intel.knowledge-curator",
            action_type="memory.propose_long_term",
            params={
                "scope": "company",
                "title": "Note",
                "content": "Retainers are monthly.",
                "source": "operator call",
            },
        )
    )
    assert r.status == "completed"  # enforced outcome stands
    assert r.decision.shadow_outcome == "approval_required" and r.decision.shadow_diverged
    report = office.shadow_report()
    assert report["enforced"] is False and report["total"] == 1
    assert report["by_rule"][0]["rule_id"] == "shadow.long-term-memory-proposals-need-approval"
    assert office.audit.events(event_type="policy.shadow_divergence")


def test_shadow_rules_do_not_fire_without_divergence(office):
    office.perform(ActionRequest(agent_id="eng.software-architect", action_type="docs.draft", params={"title": "x"}))
    assert office.shadow_report()["total"] == 0


def test_shadow_file_is_validated():
    raw = json.loads((ROOT / "config" / "policy.json").read_text())
    with pytest.raises(PolicyError, match="unknown conditions"):
        parse_policy(raw, {"rules": [{"id": "r", "effect": "deny", "when": {"time_of_day": "night"}}]})
    with pytest.raises(PolicyError, match="effect"):
        parse_policy(raw, {"rules": [{"id": "r", "effect": "allow", "when": {"action_types": ["x"]}}]})


# 8. Idempotency ---------------------------------------------------------------------------------


def test_same_key_replays_instead_of_acting_twice(office):
    calls = []
    office.tools.register("docs.draft", lambda ctx: calls.append(1) or {"summary": "draft", "artifact": {"n": 1}})
    req = ActionRequest(
        agent_id="eng.software-architect", action_type="docs.draft", params={"title": "x"}, idempotency_key="req-123"
    )
    first, second = office.perform(req), office.perform(req)
    assert first.status == second.status == "completed" and second.replayed and calls == [1]
    assert second.output == first.output
    assert len(office.audit.events(event_type="action.executed")) == 1
    assert office.audit.events(event_type="action.replayed")


def test_reusing_a_key_for_a_different_request_is_refused(office):
    office.perform(
        ActionRequest(
            agent_id="eng.software-architect", action_type="docs.draft", params={"title": "x"}, idempotency_key="req-9"
        )
    )
    other = office.perform(
        ActionRequest(
            agent_id="eng.software-architect", action_type="docs.draft", params={"title": "y"}, idempotency_key="req-9"
        )
    )
    assert other.status == "denied" and "different request" in other.error


def test_a_failed_attempt_can_be_retried_with_its_key(office):
    calls = []

    def flaky(ctx):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("transient")
        return {"summary": "ok", "artifact": {"n": 2}}

    office.tools.register("docs.draft", flaky)
    req = ActionRequest(
        agent_id="eng.software-architect", action_type="docs.draft", params={"title": "x"}, idempotency_key="req-7"
    )
    assert office.perform(req).status == "failed"
    assert office.perform(req).status == "completed" and calls == [1, 1]


def test_workflow_tasks_carry_keys(ran):
    office, _ = ran
    with office.store.lock:
        keys = [r[0] for r in office.store.conn.execute("SELECT key FROM idempotency_keys")]
    assert keys and all(k.startswith("task:") for k in keys)
