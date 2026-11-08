import copy
import json
import shutil

import pytest

from agent_core.config import ConfigError, load_config
from agent_core.office import OfficeError
from tests.conftest import ROOT

REQUIRED = {
    "exec": {"Chief of Staff", "Strategy Agent", "Operations Agent", "Risk & Compliance Agent"},
    "eng": {
        "Software Architect",
        "Frontend Engineer",
        "Backend Engineer",
        "DevOps Agent",
        "QA Engineer",
        "Code Review Agent",
    },
    "cyber": {
        "Threat Analyst",
        "Security Auditor",
        "Incident Response Agent",
        "OSINT Research Agent",
        "Compliance Monitor",
    },
    "growth": {
        "Brand Strategist",
        "Content Writer",
        "SEO Agent",
        "Social Media Agent",
        "Video Concept Agent",
        "Campaign Analyst",
    },
    "revenue": {
        "Lead Research Agent",
        "Sales Strategist",
        "Proposal Writer",
        "Customer Success Agent",
        "Pricing Analyst",
    },
    "intel": {"Research Agent", "Market Analyst", "Competitive Intelligence Agent", "Knowledge Curator"},
    "sim": {"Scenario Designer", "Red Team Agent", "Blue Team Agent", "Business War-Gamer", "Outcome Analyst"},
}


def test_org_matches_the_brief():
    cfg = load_config(ROOT / "config")
    by_dept: dict[str, set[str]] = {}
    for a in cfg.agents:
        by_dept.setdefault(a.department, set()).add(a.name)
    assert by_dept == REQUIRED
    assert len({r["id"] for r in cfg.rooms}) == 12


def test_every_agent_has_identity_objective_tools_permissions_boundaries():
    for a in load_config(ROOT / "config").agents:
        assert a.callsign and a.reports_to and a.objective and a.success_criteria
        assert a.tools and a.permissions and a.memory_scopes and a.boundaries


def _with_org(tmp_path, mutate):
    shutil.copytree(ROOT / "config", tmp_path / "config")
    org = json.loads((tmp_path / "config" / "org.json").read_text())
    mutate(org)
    (tmp_path / "config" / "org.json").write_text(json.dumps(org))
    return tmp_path / "config"


@pytest.mark.parametrize(
    "mutate,match",
    [
        (lambda o: o["agents"][1]["permissions"].update(social="approve"), "human-only"),
        (lambda o: o["agents"][0].update(reports_to="exec.strategy"), "does not reach the operator"),
        (lambda o: o["agents"][2]["tools"].append("rocket.launcher"), "unknown tool"),
        (lambda o: o["agents"][2]["permissions"].update(teleport="read"), "unknown permission domain"),
        (lambda o: o["agents"][3].update(department="moon"), "unknown department"),
    ],
)
def test_bad_org_refuses_to_load(tmp_path, mutate, match):
    with pytest.raises(ConfigError, match=match):
        load_config(_with_org(tmp_path, mutate))


def test_hiring_validates_grants(office, operator):
    spec = {
        "id": "growth.newsletter",
        "callsign": "CG-GM-07",
        "name": "Newsletter Agent",
        "department": "growth",
        "reports_to": "growth.brand-strategist",
        "objective": "Draft the monthly newsletter.",
        "permissions": {"content": "propose"},
        "tools": ["content.studio"],
    }
    agent = office.hire_agent(copy.deepcopy(spec), operator)
    assert agent.permissions["memory"] == "write"  # base grants applied
    bad = {**spec, "id": "growth.rogue", "callsign": "CG-GM-08", "permissions": {"social": "approve"}}
    with pytest.raises(OfficeError):
        office.hire_agent(bad, operator)
    clone = office.clone_agent("growth.newsletter", "growth.newsletter-2", "CG-GM-09", operator)
    assert clone.permissions == agent.permissions
    updated = office.update_agent("growth.newsletter", {"objective": "Draft the weekly newsletter."}, operator)
    assert updated.version == 2
    with pytest.raises(OfficeError):
        office.update_agent("growth.newsletter", {"permissions": {"social": "approve"}}, operator)
    office.set_agent_lifecycle("growth.newsletter", "retire", operator, "replaced")
    with pytest.raises(OfficeError):
        office.update_agent("growth.newsletter", {"objective": "x is not allowed"}, operator)
    assert office.audit.events(event_type="agent.hired")
