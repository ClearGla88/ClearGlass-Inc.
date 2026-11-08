from datetime import timedelta

import pytest

from memory_vault import MemoryError_
from simulation import SCENARIOS, SimulationError, run_scenario


def test_secrets_never_enter_memory(office):
    agent = office.agent("intel.knowledge-curator")
    with pytest.raises(MemoryError_, match="credential"):
        office.memory.propose(agent, "company", "creds", "key AKIA" + "ABCDEFGHIJKLMNOP", "chat")


def test_long_term_memory_needs_operator_approval(office, operator):
    curator = office.agent("intel.knowledge-curator")
    reader = office.agent("growth.content-writer")
    rec = office.memory.propose(
        curator, "company", "Pricing note", "Advisory retainers start monthly.", "operator call"
    )
    assert rec.id not in {r.id for r in office.memory.read(reader)}
    with pytest.raises(MemoryError_, match="reason"):
        office.memory.decide(rec.id, operator.id, True, "ok")
    office.memory.decide(rec.id, operator.id, True, "Confirmed by the operator on the call.")
    assert rec.id in {r.id for r in office.memory.read(reader)}


def test_scope_and_clearance_filter_reads(office, operator):
    secret = office.memory.add_approved(operator.id, "company", "Board notes", "Restricted.", "operator", "restricted")
    eng = office.memory.add_approved(operator.id, "dept:eng", "Runbook", "Restart with care.", "operator")
    writer = office.agent("growth.content-writer")
    risk = office.agent("exec.risk-compliance")
    seen_writer = {r.id for r in office.memory.read(writer)}
    assert secret.id not in seen_writer and eng.id not in seen_writer
    assert secret.id in {r.id for r in office.memory.read(risk)}


def test_short_term_memory_expires(office):
    agent = office.agent("eng.backend")
    rec = office.memory.write_task(agent, "msn_x", "note", "draft is in progress", "task:1")
    assert office.memory.visible_to(office.agent("eng.qa"), rec)
    office.clock.advance(timedelta(hours=25))
    assert office.memory.expire() >= 1
    assert not office.memory.visible_to(office.agent("eng.qa"), office.store.get(type(rec), rec.id))


def test_knowledge_vault_is_seeded_from_reviewed_config(office):
    titles = {r.title for r in office.memory.all("long_term")}
    assert {"Company objectives", "Brand guidelines", "Governance policy summary"} <= titles
    assert all(r.status == "approved" and r.approved_by for r in office.memory.all("long_term"))


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_scenarios_are_deterministic_and_labelled(name):
    ex = SCENARIOS[name].example
    a = run_scenario(name, ex["assumptions"], ex["options"], seed=11, runs=500)
    b = run_scenario(name, ex["assumptions"], ex["options"], seed=11, runs=500)
    assert a == b
    assert "Not a forecast" in a["disclaimer"]
    assert a["recommendation"]["option"] in a["results"]


def test_simulation_input_validation():
    with pytest.raises(SimulationError, match="unknown scenario"):
        run_scenario("lottery", {}, [{"name": "x"}])
    with pytest.raises(SimulationError, match="low > high"):
        run_scenario(
            "pricing",
            {
                "reference_price": 1,
                "monthly_qualified_leads": {"low": 5, "high": 1},
                "conversion_at_reference_price": 0.1,
                "price_elasticity": -1,
            },
            [{"price": 1}],
        )
    with pytest.raises(SimulationError, match="runs"):
        run_scenario("pricing", {}, [{"price": 1}], runs=10)


def test_office_simulations_run_in_the_sandbox_only(office):
    ex = SCENARIOS["rollout"].example
    result = office.run_simulation("sim.scenario-designer", {"scenario_type": "rollout", **ex})
    assert result.status == "completed"
    assert result.output["artifact"]["after_action"]["decision"].startswith("Recommend")
    assert office.simulations()[0].disclaimer
    # A war-room agent cannot use the result to act outside the sandbox.
    from policy_engine import ActionRequest

    blocked = office.perform(
        ActionRequest(
            agent_id="sim.business-war-gamer",
            action_type="pricing.change_live",
            params={"change_plan": "a", "rollback_plan": "b", "verification_plan": "c"},
        )
    )
    assert blocked.status == "denied"
