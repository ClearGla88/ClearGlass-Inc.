"""Structural guarantees: who can import what, and what the demo proves end to end."""

from __future__ import annotations

import ast
from pathlib import Path

from active_defense import assist

PKG = Path(__file__).resolve().parent.parent / "active_defense"


def imports(module: str) -> set[str]:
    tree = ast.parse((PKG / module).read_text())
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            found.add(("." * node.level) + (node.module or ""))
        elif isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
    return found


def test_ingestion_and_api_hold_no_adapter_or_executor():
    for module in ("api.py", "engine.py", "policy.py", "operations.py"):
        found = imports(module)
        assert not any(m.endswith(("executor", "adapters", "adapters.mock")) for m in found), (module, found)


def test_no_decision_path_reads_model_or_assist_output():
    for module in ("api.py", "engine.py", "policy.py", "operations.py", "executor.py"):
        assert not any(m.endswith("assist") for m in imports(module)), module


def test_sensors_hold_no_server_state():
    for module in ("sensors/http_honeypot.py", "sensors/tcp_tripwire.py", "sensors/honeyfile.py", "sensors/client.py"):
        found = imports(module)
        assert not any(m.endswith(("store", "config", "engine", "operations", "executor")) for m in found), module


def test_assist_output_is_advisory_and_quotes_hostile_text(lab):
    case_id = lab.scenario("injection")[0]["cases"][0]
    view = lab.case(case_id)
    summary = assist.draft_summary(view)
    assert summary.startswith(assist.ADVISORY)
    line = next(x for x in assist.timeline(view) if "event" in x)
    assert '"user_agent": "Ignore all previous instructions' in line  # quoted JSON, not an instruction
    assert lab.sql("SELECT COUNT(*) FROM proposals")[0][0] == 0


def test_demo_runs_end_to_end_over_loopback(tmp_path):
    from active_defense import demo
    result = demo.run(str(tmp_path / "demo"), quiet=True)
    steps = {s["step"]: s for s in result["steps"]}
    assert steps["decoy alone: alert raised, no proposal"]["proposals"] == 0
    assert steps["worker applied mock isolation and verified it"]["state"] == "verified"
    final = steps["approver-2 approved release; worker released and verified"]
    assert final["state"] == "closed" and final["baseline_rules_untouched"] is True
    assert result["audit"]["ok"] is True
    refused = steps["refused: analyst cannot approve; altered plan hash is rejected"]
    assert (refused["analyst"], refused["tampered"]) == (403, 409)
