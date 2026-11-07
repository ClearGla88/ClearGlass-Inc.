"""Tool registry, adapters and the secret broker.

Every adapter here is local: it reads or writes this office's own store, or
records a dry run. No adapter calls an external system. Production connectors
(GitHub, Slack, email, CRM, cloud, payments) are not implemented; their tools
are registered so the gate can govern them, and their adapter records a dry run
and says so in the result.

Agents never receive credentials. The executor asks the :class:`SecretBroker`
for a :class:`Credential` handle at execution time and passes it to the adapter
only; the handle's ``repr`` is redacted, and results never contain it.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from .db import dumps, new_id, row_to_dict, rows_to_dicts
from .models import Clock, GovernanceError, iso, sha256_hex


@dataclass(frozen=True)
class ToolSpec:
    key: str
    name: str
    category: str
    environment: str  # internal | sandbox | production
    operations: dict[str, str]  # operation -> declared risk
    description: str
    secret_ref: str | None = None

    def capability_surface(self) -> dict[str, Any]:
        return {"operations": {op: {"risk": risk} for op, risk in self.operations.items()}}


class Credential:
    """Opaque credential handle. Only adapters may call :meth:`reveal`."""

    __slots__ = ("_ref", "_value")

    def __init__(self, ref: str, value: str):
        self._ref = ref
        self._value = value

    @property
    def ref(self) -> str:
        return self._ref

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return f"Credential(ref={self._ref!r}, value=<redacted>)"

    __str__ = __repr__


class SecretBroker:
    """Resolves secret references from the runtime environment at execution time.

    A reference ``github`` resolves from ``AGENT_OFFICE_SECRET_GITHUB``. Simulation
    missions never resolve anything.
    """

    def __init__(self, environ: Mapping[str, str] | None = None):
        self._environ = environ if environ is not None else os.environ

    def resolve(self, ref: str | None, *, mission_mode: str) -> Credential | None:
        if not ref or mission_mode == "simulation":
            return None
        value = self._environ.get(f"AGENT_OFFICE_SECRET_{ref.upper()}")
        return Credential(ref, value) if value else None


@dataclass
class ExecutionContext:
    conn: sqlite3.Connection
    company_id: str
    agent: dict[str, Any]
    correlation_id: str
    clock: Clock
    mission_id: str | None = None
    task_id: str | None = None
    mission_mode: str = "production"
    credential: Credential | None = field(default=None, repr=False)


class ToolAdapter(Protocol):
    def invoke(self, action: str, payload: dict[str, Any], ctx: ExecutionContext) -> dict[str, Any]: ...

    def verify(self, action: str, payload: dict[str, Any], result: dict[str, Any], ctx: ExecutionContext) -> bool: ...


def _require(payload: dict[str, Any], *names: str) -> None:
    missing = [n for n in names if not payload.get(n)]
    if missing:
        raise ValueError(f"payload missing required field(s): {', '.join(missing)}")


class VaultSearch:
    def invoke(self, action, payload, ctx):
        query = str(payload.get("query", "")).strip()
        params: list[Any] = [ctx.company_id]
        sql = "SELECT id, title, doc_type, checksum, content FROM knowledge_documents WHERE company_id = ? AND approved = 1"
        if payload.get("doc_type"):
            sql += " AND doc_type = ?"
            params.append(payload["doc_type"])
        if query:
            sql += " AND (title LIKE ? OR content LIKE ?)"
            params += [f"%{query}%", f"%{query}%"]
        rows = ctx.conn.execute(sql + " ORDER BY title LIMIT 5", params).fetchall()
        return {
            "query": query,
            "documents": [
                {
                    "id": r["id"],
                    "title": r["title"],
                    "doc_type": r["doc_type"],
                    "checksum": r["checksum"],
                    "snippet": r["content"][:160],
                }
                for r in rows
            ],
        }

    def verify(self, action, payload, result, ctx):
        return isinstance(result.get("documents"), list)


class VaultDraft:
    def invoke(self, action, payload, ctx):
        _require(payload, "title", "content")
        doc_id = new_id()
        checksum = sha256_hex(payload["content"])
        ctx.conn.execute(
            """INSERT INTO knowledge_documents
               (id, company_id, title, doc_type, content, source, checksum, approved,
                created_by_agent_id, created_at)
               VALUES (?,?,?,?,?,?,?,0,?,?)""",
            (
                doc_id,
                ctx.company_id,
                payload["title"],
                payload.get("doc_type", "draft"),
                payload["content"],
                f"agent:{ctx.agent['name']}",
                checksum,
                ctx.agent["id"],
                iso(ctx.clock()),
            ),
        )
        return {"document_id": doc_id, "checksum": checksum, "approved": False}

    def verify(self, action, payload, result, ctx):
        row = ctx.conn.execute(
            "SELECT checksum FROM knowledge_documents WHERE id = ?", (result.get("document_id"),)
        ).fetchone()
        return row is not None and row["checksum"] == result.get("checksum")


class MemoryPropose:
    """Writes a long-term memory candidate. It stays unapproved until a human approves it."""

    def invoke(self, action, payload, ctx):
        _require(payload, "namespace", "content", "source")
        record_id = new_id()
        ctx.conn.execute(
            """INSERT INTO memory_records
               (id, company_id, scope, namespace, content, source, confidence, approved,
                created_by_agent_id, created_at)
               VALUES (?,?,?,?,?,?,?,0,?,?)""",
            (
                record_id,
                ctx.company_id,
                "department",
                payload["namespace"],
                payload["content"],
                payload["source"],
                float(payload.get("confidence", 0.5)),
                ctx.agent["id"],
                iso(ctx.clock()),
            ),
        )
        return {"memory_record_id": record_id, "approved": False}

    def verify(self, action, payload, result, ctx):
        row = ctx.conn.execute(
            "SELECT approved FROM memory_records WHERE id = ?", (result.get("memory_record_id"),)
        ).fetchone()
        return row is not None and row["approved"] == 0


class TelemetryRead:
    """Governance telemetry computed from the office's own ledger and queues."""

    def invoke(self, action, payload, ctx):
        q = ctx.conn.execute
        by_outcome = {r["outcome"]: r["n"] for r in q(
            "SELECT outcome, COUNT(*) AS n FROM audit_events GROUP BY outcome"
        ).fetchall()}
        denials = rows_to_dicts(q(
            """SELECT actor_id, resource_id, metadata, created_at FROM audit_events
               WHERE action = 'governance.deny' ORDER BY seq DESC LIMIT 10"""
        ).fetchall())
        pending = {r["risk_level"]: r["n"] for r in q(
            "SELECT risk_level, COUNT(*) AS n FROM approvals WHERE status = 'pending' GROUP BY risk_level"
        ).fetchall()}
        divergences = q("SELECT COUNT(*) FROM policy_shadow_divergences").fetchone()[0]
        return {
            "audit_events_by_outcome": by_outcome,
            "recent_denials": [
                {"agent_id": d["actor_id"], "code": (d["metadata"] or {}).get("code"), "at": d["created_at"]}
                for d in denials
            ],
            "pending_approvals_by_risk": pending,
            "shadow_divergences": int(divergences),
        }

    def verify(self, action, payload, result, ctx):
        return "audit_events_by_outcome" in result


class SandboxChecks:
    """Checks that a document contains every required section. Deterministic, local."""

    def invoke(self, action, payload, ctx):
        _require(payload, "document_id", "required_sections")
        row = ctx.conn.execute(
            "SELECT content FROM knowledge_documents WHERE id = ?", (payload["document_id"],)
        ).fetchone()
        if row is None:
            raise ValueError("document_id does not exist")
        content = row["content"].lower()
        checks = [
            {"name": section, "passed": section.lower() in content}
            for section in payload["required_sections"]
        ]
        return {
            "document_id": payload["document_id"],
            "checks": checks,
            "passed": bool(checks) and all(c["passed"] for c in checks),
            "environment": "sandbox",
        }

    def verify(self, action, payload, result, ctx):
        return isinstance(result.get("passed"), bool) and result.get("environment") == "sandbox"


class ReportWrite:
    def invoke(self, action, payload, ctx):
        _require(payload, "report_type", "content", "markdown")
        report_id = new_id()
        ctx.conn.execute(
            """INSERT INTO reports (id, company_id, report_type, content_json, rendered_markdown,
                                    generated_by, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (
                report_id,
                ctx.company_id,
                payload["report_type"],
                dumps(payload["content"]),
                payload["markdown"],
                ctx.agent["name"],
                iso(ctx.clock()),
            ),
        )
        return {"report_id": report_id, "report_type": payload["report_type"]}

    def verify(self, action, payload, result, ctx):
        return ctx.conn.execute("SELECT 1 FROM reports WHERE id = ?", (result.get("report_id"),)).fetchone() is not None


class DryRunConnector:
    """Stand-in for a production connector that is not built. Nothing leaves the system."""

    def __init__(self, key: str):
        self.key = key

    def invoke(self, action, payload, ctx):
        return {
            "executed": False,
            "dry_run": True,
            "connector": self.key,
            "credential_available": ctx.credential is not None,
            "request_digest": sha256_hex(payload),
            "note": "No production connector is implemented for this tool. The approved request "
            "was recorded as a dry run and nothing left the system.",
        }

    def verify(self, action, payload, result, ctx):
        return result.get("dry_run") is True and result.get("executed") is False


class NeverExecute:
    """Adapter for governance tools. Policy forbids them; reaching this is a bug."""

    def invoke(self, action, payload, ctx):
        raise RuntimeError("governance tools must never execute")

    def verify(self, action, payload, result, ctx):
        return False


BUILTIN_TOOLS: tuple[tuple[ToolSpec, ToolAdapter], ...] = (
    (ToolSpec("vault.search", "Knowledge Vault search", "knowledge", "internal",
              {"read": "low"}, "Search approved knowledge documents."), VaultSearch()),
    (ToolSpec("vault.draft", "Knowledge Vault draft", "knowledge", "internal",
              {"write": "low"}, "Write an unapproved internal draft."), VaultDraft()),
    (ToolSpec("memory.propose", "Long-term memory proposal", "knowledge", "internal",
              {"write": "medium"}, "Propose a memory record; a human must approve it."), MemoryPropose()),
    (ToolSpec("report.write", "Report writer", "reporting", "internal",
              {"write": "low"}, "Store an internal report."), ReportWrite()),
    (ToolSpec("telemetry.read", "Governance telemetry", "security", "internal",
              {"read": "low"}, "Read ledger and approval-queue telemetry."), TelemetryRead()),
    (ToolSpec("sandbox.checks", "Sandbox release checks", "engineering", "sandbox",
              {"execute": "low"}, "Verify a document contains its required sections."), SandboxChecks()),
    (ToolSpec("deploy.production", "Production deployment", "deployment", "production",
              {"execute": "critical"}, "Deploy to production.", "deploy"), DryRunConnector("deploy.production")),
    (ToolSpec("security.config", "Security configuration change", "security", "production",
              {"execute": "critical"}, "Change a production security setting.", "security"),
     DryRunConnector("security.config")),
    (ToolSpec("content.publish", "Public content publishing", "comms", "production",
              {"execute": "high"}, "Publish content to a public channel.", "cms"), DryRunConnector("content.publish")),
    (ToolSpec("email.send", "Outbound email", "comms", "production",
              {"execute": "high"}, "Send email outside the company.", "email"), DryRunConnector("email.send")),
    (ToolSpec("payments.transfer", "Payment transfer", "finance", "production",
              {"execute": "critical"}, "Move money.", "payments"), DryRunConnector("payments.transfer")),
    (ToolSpec("governance.audit_rewrite", "Audit ledger rewrite", "governance", "internal",
              {"execute": "critical"}, "Exists only so policy can forbid it."), NeverExecute()),
)


class ToolRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}
        self._adapters: dict[str, ToolAdapter] = {}

    @classmethod
    def builtin(cls) -> ToolRegistry:
        registry = cls()
        for spec, adapter in BUILTIN_TOOLS:
            registry.register(spec, adapter)
        return registry

    def register(self, spec: ToolSpec, adapter: ToolAdapter) -> None:
        if spec.environment not in ("internal", "sandbox", "production"):
            raise ValueError(f"unknown environment {spec.environment!r}")
        self._specs[spec.key] = spec
        self._adapters[spec.key] = adapter

    def spec(self, key: str) -> ToolSpec | None:
        return self._specs.get(key)

    def adapter(self, key: str) -> ToolAdapter:
        if key not in self._adapters:
            raise GovernanceError("tool_unknown", f"no adapter for {key}")
        return self._adapters[key]

    def sync(self, conn: sqlite3.Connection) -> None:
        """The code is the source of truth for tool capability surfaces."""
        for spec in self._specs.values():
            existing = conn.execute("SELECT id FROM tools WHERE key = ?", (spec.key,)).fetchone()
            values = (
                spec.name,
                spec.description,
                spec.category,
                spec.environment,
                dumps(spec.capability_surface()),
                int(spec.secret_ref is not None),
            )
            if existing:
                conn.execute(
                    """UPDATE tools SET name=?, description=?, category=?, environment=?,
                       capability_surface=?, requires_secret=? WHERE key=?""",
                    (*values, spec.key),
                )
            else:
                conn.execute(
                    """INSERT INTO tools (id, name, description, category, environment,
                       capability_surface, requires_secret, key) VALUES (?,?,?,?,?,?,?,?)""",
                    (new_id(), *values, spec.key),
                )

    def tool_row(self, conn: sqlite3.Connection, key: str) -> dict[str, Any] | None:
        return row_to_dict(conn.execute("SELECT * FROM tools WHERE key = ?", (key,)).fetchone())
