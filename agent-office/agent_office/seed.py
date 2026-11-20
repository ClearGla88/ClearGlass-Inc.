"""Seed data for the demo headquarters.

Everything seeded here describes the office itself: its departments, agents,
grants, governance documents and missions. Nothing describes customers,
leads, revenue or market facts, because the office has no verified source for
them. Where a mission needs such a source, the seed leaves it empty and the
agents report that it is empty.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from .audit import AuditLedger
from .db import dumps, new_id, transaction
from .missions import MissionService
from .models import Clock, iso, sha256_hex

OWNER = "operator-1"
SECOND_OPERATOR = "operator-2"

DEPARTMENTS = (
    ("executive", "Executive Suite", "Direction, briefings, risk and compliance.", 7),
    ("engineering", "Engineering Lab", "Architecture, QA and release readiness.", 6),
    ("cyber", "Cyber Operations Center", "Defensive security review on authorised telemetry.", 5),
    ("growth", "Growth & Marketing Studio", "Narrative and content drafts.", 4),
    ("revenue", "Revenue Floor", "Lead research and proposal drafts.", 3),
    ("intelligence", "Intelligence Library", "Sourced research and curated memory.", 2),
    ("simulation", "Simulation War Room", "Sandboxed drills. No production access.", 1),
)

# name, department, role, objective, reports_to, can_request_critical, grants[(tool, action)]
AGENTS: tuple[tuple[str, str, str, str, str | None, bool, tuple[tuple[str, str], ...]], ...] = (
    ("Avery", "executive", "Chief of Staff",
     "Run the daily operations loop and brief the operator.", None, False,
     (("vault.search", "read"), ("report.write", "write"), ("telemetry.read", "read"))),
    ("Sable", "executive", "Risk & Compliance",
     "Flag risks, blockers and policy conflicts before they reach production.", "Avery", False,
     (("vault.search", "read"), ("vault.draft", "write"), ("telemetry.read", "read"))),
    ("Kai", "engineering", "Software Architect",
     "Produce deployment plans with rollback paths.", "Avery", True,
     (("vault.search", "read"), ("vault.draft", "write"), ("deploy.production", "propose"))),
    ("Nova", "engineering", "QA Engineer",
     "Verify release artefacts in the sandbox.", "Kai", False,
     (("vault.search", "read"), ("vault.draft", "write"), ("sandbox.checks", "execute"))),
    ("Rook", "cyber", "Threat Analyst",
     "Review authorised telemetry and draft findings.", "Sable", False,
     (("vault.search", "read"), ("vault.draft", "write"), ("telemetry.read", "read"),
      ("security.config", "propose"))),
    ("Iris", "growth", "Content Writer",
     "Draft the launch narrative within brand guidelines.", "Avery", False,
     (("vault.search", "read"), ("vault.draft", "write"), ("content.publish", "propose"))),
    ("Miles", "revenue", "Lead Research Agent",
     "Prepare outreach only against verified, cited leads.", "Avery", False,
     (("vault.search", "read"), ("vault.draft", "write"), ("email.send", "propose"))),
    ("Juno", "intelligence", "Market Analyst",
     "Curate sourced context; never present assumptions as facts.", "Avery", False,
     (("vault.search", "read"), ("vault.draft", "write"), ("memory.propose", "write"))),
)

DOCUMENTS = (
    ("Company goals", "goal",
     "Operate ClearGlass as a governed, AI-native company. Agents propose and prepare; humans approve "
     "anything that touches money, contracts, production, customers or sensitive data. Every action is "
     "recorded in the audit ledger."),
    ("Brand guidelines", "brand_guideline",
     "Tagline: CLEARGLASS: See Through Everything. Write plainly. Make no claim the company cannot "
     "source. Never invent customers, results or urgency."),
    ("Release scope: demo-1", "technical_doc",
     "Release demo-1 exists to exercise the governance gate in the Daily Operations Loop. It is not a "
     "real software release, and no deployment connector is configured."),
    ("Governance policy summary", "policy",
     "Nine-stage gate: emergency halt, identity, permission, risk, Cedar policy, tool capability, human "
     "approval, execution with an audit intent record, verification, audit. High and critical actions "
     "need a human approval bound to the exact request."),
)

DEPLOYMENT_PLAN = """# Deployment plan: demo-1

## Scope
Release demo-1 of clearglass-web. Demo release used to exercise the governance gate.

## Rollback plan
Redeploy the previous release tag, then confirm the health check returns 200 within five minutes.

## Verification
Health check returns 200; error rate does not rise above the pre-release baseline for 15 minutes.

## Test evidence
Sandbox release checks (task t3 in this mission) must pass before the deployment step is proposed.
"""

MISSIONS: tuple[dict[str, Any], ...] = (
    {
        "code": "M-101", "title": "Platform Release Readiness", "department_key": "engineering", "priority": 1,
        "objective": "Prepare release demo-1 with a plan, sandbox evidence and a rollback path.",
        "deliverables": ["Deployment plan", "Sandbox test report", "Rollback plan"],
        "tasks": [
            {"key": "t1", "agent": "Kai", "title": "Load release scope", "tool": "vault.search",
             "action": "read", "payload": {"query": "Release scope"}},
            {"key": "t2", "agent": "Kai", "title": "Draft deployment plan", "tool": "vault.draft",
             "action": "write", "depends_on": ["t1"],
             "payload": {"title": "Deployment plan: demo-1", "content": DEPLOYMENT_PLAN}},
            {"key": "t3", "agent": "Nova", "title": "Run release checks in the sandbox", "tool": "sandbox.checks",
             "action": "execute", "depends_on": ["t2"],
             "payload": {"document_id": {"$output": "t2.document_id"},
                         "required_sections": ["Scope", "Rollback plan", "Verification", "Test evidence"]}},
            {"key": "t4", "agent": "Kai", "title": "Deploy demo-1 to production", "tool": "deploy.production",
             "action": "execute", "depends_on": ["t3"],
             "payload": {"summary": "Deploy release demo-1 of clearglass-web to production",
                         "service": "clearglass-web", "version": "demo-1",
                         "rollback_plan": "Redeploy the previous release tag, then confirm the health "
                                          "check returns 200 within five minutes.",
                         "test_evidence": {"$task": "t3"}}},
        ],
    },
    {
        "code": "M-102", "title": "Q3 Security Review", "department_key": "cyber", "priority": 2,
        "objective": "Review governance telemetry and draft findings. Internal work only.",
        "deliverables": ["Telemetry snapshot", "Findings draft"],
        "tasks": [
            {"key": "t1", "agent": "Rook", "title": "Read governance telemetry", "tool": "telemetry.read",
             "action": "read", "payload": {"window": "24h"}},
            {"key": "t2", "agent": "Sable", "title": "Load governance policy summary", "tool": "vault.search",
             "action": "read", "payload": {"query": "Governance"}},
            {"key": "t3", "agent": "Rook", "title": "Draft security findings", "tool": "vault.draft",
             "action": "write", "depends_on": ["t1", "t2"],
             "payload": {"title": "Security review findings (draft)",
                         "content": "Draft. Findings are limited to the office's own governance telemetry; "
                                    "no external systems are monitored."}},
        ],
    },
    {
        "code": "M-103", "title": "Launch Narrative", "department_key": "growth", "priority": 3,
        "objective": "Draft the launch narrative and ask to publish it.",
        "deliverables": ["Content calendar draft", "Blog post draft"],
        "tasks": [
            {"key": "t1", "agent": "Iris", "title": "Load brand guidelines", "tool": "vault.search",
             "action": "read", "payload": {"query": "Brand"}},
            {"key": "t2", "agent": "Iris", "title": "Draft content calendar", "tool": "vault.draft",
             "action": "write", "depends_on": ["t1"],
             "payload": {"title": "Content calendar (draft)",
                         "content": "Draft calendar. Dates are placeholders for the operator to set."}},
            {"key": "t3", "agent": "Iris", "title": "Draft launch blog post", "tool": "vault.draft",
             "action": "write", "depends_on": ["t1"],
             "payload": {"title": "Launch post (draft)",
                         "content": "CLEARGLASS: See Through Everything. Draft text for operator review; "
                                    "it makes no customer or results claims."}},
            {"key": "t4", "agent": "Iris", "title": "Publish the launch post", "tool": "content.publish",
             "action": "execute", "depends_on": ["t2", "t3"],
             "payload": {"summary": "Publish the launch blog post to the company blog", "channel": "blog",
                         "document_id": {"$output": "t3.document_id"}, "external": True}},
        ],
    },
    {
        "code": "M-104", "title": "Enterprise Lead Research", "department_key": "revenue", "priority": 3,
        "objective": "Research leads from verified sources only, then ask to send outreach.",
        "deliverables": ["Sourced context", "Outreach template"],
        "tasks": [
            {"key": "t1", "agent": "Juno", "title": "Search approved customer context", "tool": "vault.search",
             "action": "read", "payload": {"doc_type": "customer_context"}},
            {"key": "t2", "agent": "Juno", "title": "Propose a sourced memory record", "tool": "memory.propose",
             "action": "write", "depends_on": ["t1"],
             "payload": {"namespace": "revenue",
                         "content": "The vault holds no approved customer context, so no lead is verified.",
                         "source": "vault.search for doc_type=customer_context returned 0 documents",
                         "confidence": 0.9}},
            {"key": "t3", "agent": "Miles", "title": "Draft outreach template", "tool": "vault.draft",
             "action": "write", "depends_on": ["t1"],
             "payload": {"title": "Outreach template (draft)",
                         "content": "Template only. No recipient is named until a verified lead exists."}},
            {"key": "t4", "agent": "Miles", "title": "Send outreach", "tool": "email.send",
             "action": "execute", "depends_on": ["t2", "t3"],
             "payload": {"summary": "Send the outreach template to the approved lead list",
                         "template_document_id": {"$output": "t3.document_id"},
                         "recipients_source": "approved lead list (none exists yet)", "external": True}},
        ],
    },
    {
        "code": "S-201", "title": "Rollback Drill (simulation)", "department_key": "simulation", "priority": 4,
        "mode": "simulation",
        "objective": "Rehearse a rollback in the sandbox. Proves a simulation can never reach production.",
        "deliverables": ["Drill record"],
        "tasks": [
            {"key": "t1", "agent": "Kai", "title": "Load release scope", "tool": "vault.search",
             "action": "read", "payload": {"query": "Release scope"}},
            {"key": "t2", "agent": "Kai", "title": "Attempt production deploy from the drill",
             "tool": "deploy.production", "action": "execute", "depends_on": ["t1"],
             "payload": {"summary": "Drill: redeploy previous release", "service": "clearglass-web",
                         "version": "previous",
                         "rollback_plan": "Drill only. Redeploy the previous tag in the sandbox mirror."}},
        ],
    },
)


def seed_company(conn: sqlite3.Connection, clock: Clock) -> bool:
    """Create the demo headquarters once. Returns False if it already exists."""
    if conn.execute("SELECT 1 FROM companies WHERE slug = 'clearglass'").fetchone():
        return False
    now = iso(clock())
    company_id = new_id()
    ledger = AuditLedger(conn, company_id, clock)
    with transaction(conn):
        conn.execute(
            "INSERT INTO companies (id, name, slug, mission_statement, created_at) VALUES (?,?,?,?,?)",
            (company_id, "ClearGlass Inc.", "clearglass", "Your company, operated by intelligence. "
             "Your authority, preserved by design.", now),
        )
        dept_ids: dict[str, str] = {}
        for key, name, desc, floor in DEPARTMENTS:
            dept_ids[key] = new_id()
            conn.execute(
                "INSERT INTO departments (id, company_id, key, name, description, floor_index) VALUES (?,?,?,?,?,?)",
                (dept_ids[key], company_id, key, name, desc, floor),
            )
        agent_ids: dict[str, str] = {}
        tool_ids = {r["key"]: r["id"] for r in conn.execute("SELECT id, key FROM tools").fetchall()}
        for name, dept, role, objective, reports_to, critical, grants in AGENTS:
            agent_ids[name] = new_id()
            conn.execute(
                """INSERT INTO agents (id, company_id, department_id, reporting_to, name, role, objective,
                       success_criteria, memory_scope, identity_ref, owner_id, approver_id,
                       can_request_critical, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (agent_ids[name], company_id, dept_ids[dept], agent_ids.get(reports_to or ""), name, role,
                 objective, dumps([objective]),
                 dumps({"short_term": {"namespace": f"agent:{name.lower()}", "retention_hours": 24},
                        "long_term": {"namespaces": [dept], "write_requires_approval": True}}),
                 f"nhi:clearglass:{name.lower()}", OWNER, OWNER, int(critical), now, now),
            )
            for tool_key, action in grants:
                conn.execute(
                    """INSERT INTO agent_tool_grants (id, agent_id, tool_id, action, constraints, granted_by,
                           granted_at) VALUES (?,?,?,?,?,?,?)""",
                    (new_id(), agent_ids[name], tool_ids[tool_key], action, "{}", OWNER, now),
                )
        for title, doc_type, content in DOCUMENTS:
            conn.execute(
                """INSERT INTO knowledge_documents (id, company_id, title, doc_type, content, source, checksum,
                       approved, approved_by, created_at) VALUES (?,?,?,?,?,?,?,1,?,?)""",
                (new_id(), company_id, title, doc_type, content, "seed", sha256_hex(content), OWNER, now),
            )
        ledger.append(
            actor_type="system", actor_id="seed", action="system.seed", resource_type="company",
            resource_id=company_id, outcome="success", correlation_id=new_id(),
            payload={"departments": len(DEPARTMENTS), "agents": len(AGENTS), "documents": len(DOCUMENTS)},
            metadata={"owner_id": OWNER},
        )
        missions = MissionService(conn, ledger, company_id, clock)
        for spec in MISSIONS:
            missions.create(
                code=spec["code"], title=spec["title"], objective=spec["objective"],
                department_key=spec["department_key"], tasks=spec["tasks"], created_by=OWNER,
                deliverables=spec["deliverables"], mode=spec.get("mode", "production"),
                priority=spec["priority"], actor_type="system",
            )
    return True
