import pytest

from agent_core.models import Mission, Task
from agent_core.office import OfficeError
from agent_core.workflow import WorkflowError, compute_waves, resolve_refs


def mission(tasks, **kw):
    return {
        "title": "Test mission",
        "objective": "exercise the engine",
        "department": "eng",
        "owner": "eng.software-architect",
        "tasks": tasks,
        **kw,
    }


def draft(key, assignee="eng.software-architect", deps=(), params=None):
    return {
        "key": key,
        "title": key,
        "assignee": assignee,
        "depends_on": list(deps),
        "action": {"type": "docs.draft", "params": params or {"title": key}},
    }


def test_waves_group_independent_tasks():
    waves = compute_waves(["a", "b", "c", "d"], {"b": ["a"], "c": ["a"], "d": ["b", "c"]})
    assert waves == {"a": 0, "b": 1, "c": 1, "d": 2}


def test_cycles_and_unknown_dependencies_are_rejected(office):
    with pytest.raises(WorkflowError, match="cycle"):
        compute_waves(["a", "b"], {"a": ["b"], "b": ["a"]})
    with pytest.raises(OfficeError, match="unknown task"):
        office.create_mission(mission([draft("a", deps=["zzz"])]), created_by="operator.founder")
    with pytest.raises(OfficeError, match="unknown assignee"):
        office.create_mission(mission([draft("a", assignee="eng.nobody")]), created_by="operator.founder")


def test_parallel_then_sequential_execution(office):
    m = office.create_mission(
        mission([draft("a"), draft("b", deps=["a"]), draft("c", deps=["a"]), draft("d", deps=["b", "c"])]),
        created_by="operator.founder",
    )
    counts = office.run_mission(m.id)
    assert counts["completed"] == 4 and counts["ran"] == 4
    tasks = {t.key: t for t in office.store.list(Task)}
    assert (tasks["b"].wave, tasks["c"].wave, tasks["d"].wave) == (1, 1, 2)
    assert office.store.get(Mission, m.id).status == "completed"


def test_denial_blocks_everything_downstream(office):
    tasks = [
        {
            "key": "a",
            "title": "a",
            "assignee": "eng.backend",
            "action": {"type": "deploy.production", "params": {"environment": "production"}},
        },
        draft("b", deps=["a"]),
        draft("c", deps=["b"]),
    ]
    m = office.create_mission(mission(tasks), created_by="operator.founder")
    office.run_mission(m.id)
    s = {t.key: t for t in office.store.list(Task)}
    assert s["a"].status == "failed" and s["a"].error.startswith("denied")
    assert s["b"].status == "blocked" and s["c"].status == "blocked"
    assert office.agent("eng.backend").metrics["policy_denials"] == 1


def test_unhandled_internal_action_fails_honestly_after_retries(office):
    tasks = [
        {
            "key": "a",
            "title": "a",
            "assignee": "eng.backend",
            "max_attempts": 2,
            "action": {"type": "code.commit_branch", "params": {}},
        }
    ]
    m = office.create_mission(mission(tasks), created_by="operator.founder")
    office.run_mission(m.id)
    t = office.store.list(Task)[0]
    assert t.status == "failed" and t.attempts == 2 and "no handler" in t.error


def test_refs_resolve_from_upstream_outputs():
    outputs = {"a": {"artifact": {"posts": [{"text": "hi"}]}}}
    assert resolve_refs({"x": {"$from": "a", "path": "artifact.posts.0.text"}}, outputs) == {"x": "hi"}
    with pytest.raises(WorkflowError):
        resolve_refs({"$from": "a", "path": "artifact.nope"}, outputs)
    with pytest.raises(WorkflowError):
        resolve_refs({"$from": "zzz", "path": "a"}, outputs)


def test_handoffs_are_posted_between_agents(ran):
    office, _ = ran
    handoffs = office.messages(kind="handoff")
    pairs = {(m.sender, m.recipient) for m in handoffs}
    assert ("eng.software-architect", "eng.backend") in pairs
    assert ("growth.content-writer", "growth.social-media") in pairs
