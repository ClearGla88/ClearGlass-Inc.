"""Load and cross-validate the office configuration (config/*.json).

The office refuses to start on an inconsistent org chart: an agent in a
department that does not exist, a reporting cycle, a grant of the human-only
``approve`` level, a tool that is not registered, or an unknown permission
domain. Fail closed at startup, not at 3 a.m. during an action.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_core.models import HUMAN_ONLY_LEVEL, LEVEL_ORDER, Agent, Company, Department, Tool
from policy_engine.policy import Policy, load_policy
from tool_registry.registry import load_tools


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class OfficeConfig:
    company: Company
    departments: list[Department]
    agents: list[Agent]
    rooms: list[dict[str, Any]]
    tools: list[Tool]
    policy: Policy
    base_grants: dict[str, Any]


def _read(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"missing config file {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path}: invalid JSON ({exc})") from exc


def build_agent(spec: dict[str, Any], base: dict[str, Any], departments: dict[str, Department]) -> Agent:
    dept = departments.get(spec.get("department", ""))
    if dept is None:
        raise ConfigError(f"agent {spec.get('id')}: unknown department {spec.get('department')!r}")
    permissions = {**base.get("permissions", {}), **spec.get("permissions", {})}
    tools = list(dict.fromkeys([*base.get("tools", []), *spec.get("tools", [])]))
    boundaries = [*base.get("boundaries", []), *dept.boundaries, *spec.get("boundaries", [])]
    return Agent(
        id=spec["id"],
        callsign=spec["callsign"],
        name=spec["name"],
        department=dept.id,
        reports_to=spec["reports_to"],
        objective=spec["objective"],
        room=spec.get("room", dept.room),
        success_criteria=list(spec.get("success_criteria", [])),
        skills=list(spec.get("skills", [])),
        tools=tools,
        permissions=permissions,
        memory_scopes=list(spec.get("memory_scopes", ["company"])),
        clearance=spec.get("clearance", "internal"),
        boundaries=boundaries,
    )


def validate_agents(
    agents: list[Agent], departments: dict[str, Department], tools: dict[str, Tool], rooms: set[str], policy: Policy
) -> list[str]:
    problems: list[str] = []
    ids = [a.id for a in agents]
    if len(ids) != len(set(ids)):
        problems.append("duplicate agent ids")
    callsigns = [a.callsign for a in agents]
    if len(callsigns) != len(set(callsigns)):
        problems.append("duplicate callsigns")
    known = set(ids)
    domains = {s.domain for s in policy.actions.values()}
    for a in agents:
        if a.reports_to != "operator" and a.reports_to not in known:
            problems.append(f"{a.id}: reports_to {a.reports_to!r} is not an agent or 'operator'")
        if a.room not in rooms:
            problems.append(f"{a.id}: unknown room {a.room!r}")
        for domain, level in a.permissions.items():
            if level == HUMAN_ONLY_LEVEL:
                problems.append(f"{a.id}: '{HUMAN_ONLY_LEVEL}' is a human-only level")
            elif level not in LEVEL_ORDER:
                problems.append(f"{a.id}: unknown level {level!r} on {domain}")
            if domain not in domains:
                problems.append(f"{a.id}: unknown permission domain {domain!r}")
        for t in a.tools:
            if t not in tools:
                problems.append(f"{a.id}: unknown tool {t!r}")
    # Reporting lines must reach the operator without a cycle.
    by_id = {a.id: a for a in agents}
    for a in agents:
        seen: set[str] = set()
        cur = a.id
        while cur != "operator":
            if cur in seen or cur not in by_id:
                problems.append(f"{a.id}: reporting line does not reach the operator")
                break
            seen.add(cur)
            cur = by_id[cur].reports_to
    for d in departments.values():
        head = by_id.get(d.head)
        if head is None or head.department != d.id:
            problems.append(f"department {d.id}: head {d.head!r} is not an agent of the department")
    return problems


def load_config(config_dir: str | Path) -> OfficeConfig:
    config_dir = Path(config_dir)
    company_raw = _read(config_dir / "company.json")
    org = _read(config_dir / "org.json")
    policy = load_policy(config_dir / "policy.json")
    tools = load_tools(config_dir / "tools.json")
    tool_map = {t.id: t for t in tools}

    unknown_actions = {a for t in tools for a in t.actions} - set(policy.actions)
    if unknown_actions:
        raise ConfigError(f"tools declare actions missing from policy: {sorted(unknown_actions)}")

    company = Company(
        id=company_raw["id"],
        name=company_raw["name"],
        tagline=company_raw["tagline"],
        brand_line=company_raw["brand_line"],
        region=company_raw["region"],
        mission=company_raw["mission"],
        operator=company_raw["operator"],
        objectives=company_raw.get("objectives", []),
        ideal_customer_profile=company_raw.get("ideal_customer_profile", {}),
        approved_sources=company_raw.get("approved_sources", []),
        brand_guidelines=company_raw.get("brand_guidelines", []),
    )
    rooms = org.get("rooms", [])
    room_ids = {r["id"] for r in rooms}
    departments = {
        d["id"]: Department(
            id=d["id"],
            name=d["name"],
            room=d["room"],
            head=d["head"],
            mission=d["mission"],
            responsibilities=list(d.get("responsibilities", [])),
            boundaries=list(d.get("boundaries", [])),
        )
        for d in org.get("departments", [])
    }
    for d in departments.values():
        if d.room not in room_ids:
            raise ConfigError(f"department {d.id}: unknown room {d.room!r}")
    base = org.get("base_grants", {})
    agents = [build_agent(spec, base, departments) for spec in org.get("agents", [])]
    problems = validate_agents(agents, departments, tool_map, room_ids, policy)
    if problems:
        raise ConfigError("; ".join(problems))
    return OfficeConfig(
        company=company,
        departments=list(departments.values()),
        agents=agents,
        rooms=rooms,
        tools=tools,
        policy=policy,
        base_grants=base,
    )
