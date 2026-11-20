"""Keep the PostgreSQL schema honest: every model field must have a home in it."""

import re
from dataclasses import fields

from agent_core.models import ALL_MODELS
from tests.conftest import ROOT

MIGRATIONS = sorted((ROOT / "infra" / "db" / "postgres").glob("*.sql"))
SQL = "\n".join(m.read_text() for m in MIGRATIONS)

TABLE = {
    "company": "companies",
    "department": "departments",
    "agent": "agents",
    "mission": "missions",
    "task": "tasks",
    "workflow": "workflows",
    "message": "messages",
    "decision": "decisions",
    "approval": "approvals",
    "tool": "tools",
    "permission": "permissions",
    "memory": "memory_records",
    "audit_event": "audit_events",
    "simulation": "simulations",
    "report": "reports",
    "risk_assessment": "risk_assessments",
    "shadow_divergence": "shadow_divergences",
}

# Fields stored outside their own table, with where they live.
ELSEWHERE = {
    ("agent", "tools"): ("agent_tools", "tool_id"),
    ("agent", "permissions"): ("permissions", "level"),
    ("task", "depends_on"): ("task_dependencies", "depends_on"),
    ("approval", "decisions"): ("approval_decisions", "decision"),
    ("workflow", "task_ids"): ("tasks", "workflow_id"),
    ("workflow", "waves"): ("tasks", "wave"),
}

SKIP = ("CHECK", "UNIQUE", "PRIMARY", "CONSTRAINT", "FOREIGN", "--", ")")


def tables() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for name, body in re.findall(r"CREATE TABLE (\w+) \((.*?)\n\);", SQL, re.S):
        cols = set()
        for line in body.splitlines():
            line = line.strip()
            if line and not line.startswith(SKIP):
                cols.add(line.split()[0])
        out[name] = cols
    for name, column in re.findall(r"ALTER TABLE (\w+) ADD COLUMN (\w+)", SQL):
        out.setdefault(name, set()).add(column)
    return out


def test_migrations_are_numbered_and_transactional():
    assert [m.name[:4] for m in MIGRATIONS] == [f"{i:03d}_" for i in range(1, len(MIGRATIONS) + 1)]
    for m in MIGRATIONS:
        text = m.read_text()
        assert "BEGIN;" in text and text.rstrip().endswith("COMMIT;"), m.name


def test_every_model_has_a_table():
    t = tables()
    assert {m.KIND for m in ALL_MODELS} == set(TABLE)
    for kind, table in TABLE.items():
        assert table in t, f"{kind}: table {table} missing"


def test_every_field_has_a_column():
    t = tables()
    missing = []
    for model in ALL_MODELS:
        for f in fields(model):
            key = (model.KIND, f.name)
            if key in ELSEWHERE:
                table, column = ELSEWHERE[key]
                if column not in t.get(table, set()):
                    missing.append(f"{model.KIND}.{f.name} -> {table}.{column}")
            elif f.name not in t[TABLE[model.KIND]]:
                missing.append(f"{model.KIND}.{f.name}")
    assert not missing, f"fields without a column: {missing}"


def test_append_only_tables_are_guarded():
    for table in (
        "audit_events",
        "approval_decisions",
        "decisions",
        "messages",
        "risk_assessments",
        "approval_executions",
        "shadow_divergences",
    ):
        assert f"'{table}'" in SQL
    assert "'approve'" not in SQL.split("CREATE TABLE permissions")[1].split(");")[0]
