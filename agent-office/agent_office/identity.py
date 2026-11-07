"""Agent identities, lifecycle, and deny-by-default tool grants."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from .audit import AuditLedger
from .db import dumps, new_id, row_to_dict, rows_to_dicts, transaction
from .models import (
    ACTIVE_AGENT_STATUSES,
    AgentStatus,
    Clock,
    GovernanceError,
    NotFound,
    PermissionAction,
    iso,
    utcnow,
)

# What each department may hold, by tool category and grant action. Anything
# not listed is withheld. A grant outside its department's profile is reported
# as permission sprawl by :meth:`PermissionService.effective_permissions`.
DEPARTMENT_PROFILES: dict[str, dict[str, frozenset[str]]] = {
    "executive": {
        "read": frozenset({"knowledge", "security", "reporting"}),
        "write": frozenset({"knowledge", "reporting"}),
        "approve": frozenset({"knowledge", "reporting"}),
    },
    "engineering": {
        "read": frozenset({"knowledge"}),
        "write": frozenset({"knowledge"}),
        "execute": frozenset({"engineering"}),
        "propose": frozenset({"deployment"}),
    },
    "cyber": {
        "read": frozenset({"knowledge", "security"}),
        "write": frozenset({"knowledge"}),
        "propose": frozenset({"security"}),
    },
    "growth": {
        "read": frozenset({"knowledge"}),
        "write": frozenset({"knowledge"}),
        "propose": frozenset({"comms"}),
    },
    "revenue": {
        "read": frozenset({"knowledge"}),
        "write": frozenset({"knowledge"}),
        "propose": frozenset({"comms"}),
    },
    "intelligence": {
        "read": frozenset({"knowledge"}),
        "write": frozenset({"knowledge"}),
    },
    "simulation": {
        "read": frozenset({"knowledge"}),
        "write": frozenset({"knowledge"}),
        "execute": frozenset({"engineering"}),
    },
}


class IdentityService:
    def __init__(self, conn: sqlite3.Connection, ledger: AuditLedger, clock: Clock = utcnow):
        self.conn = conn
        self.ledger = ledger
        self.clock = clock

    def get(self, agent_id: str) -> dict[str, Any]:
        agent = row_to_dict(
            self.conn.execute(
                """SELECT a.*, d.key AS department_key, d.name AS department_name
                   FROM agents a JOIN departments d ON d.id = a.department_id
                   WHERE a.id = ?""",
                (agent_id,),
            ).fetchone()
        )
        if agent is None:
            raise NotFound("agent", agent_id)
        return agent

    def find_by_name(self, name: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT id FROM agents WHERE name = ?", (name,)).fetchone()
        if row is None:
            raise NotFound("agent", name)
        return self.get(row["id"])

    def list(self) -> list[dict[str, Any]]:
        return rows_to_dicts(
            self.conn.execute(
                """SELECT a.*, d.key AS department_key, d.name AS department_name
                   FROM agents a JOIN departments d ON d.id = a.department_id
                   ORDER BY d.floor_index, a.name"""
            ).fetchall()
        )

    def resolve_active_agent(self, agent_id: str) -> dict[str, Any] | None:
        """Stage 1 of the gate. Paused, suspended and retired agents cannot act."""
        try:
            agent = self.get(agent_id)
        except NotFound:
            return None
        if AgentStatus(agent["status"]) not in ACTIVE_AGENT_STATUSES:
            return None
        return agent

    def create(
        self,
        *,
        company_id: str,
        department_id: str,
        name: str,
        role: str,
        objective: str,
        owner_id: str,
        identity_ref: str,
        approver_id: str | None = None,
        reporting_to: str | None = None,
        success_criteria: list[str] | None = None,
        memory_scope: dict[str, Any] | None = None,
        can_request_critical: bool = False,
        actor_id: str,
    ) -> dict[str, Any]:
        if not owner_id:
            raise GovernanceError("owner_required", "every agent needs a human owner")
        agent_id = new_id()
        now = iso(self.clock())
        with transaction(self.conn):
            self.conn.execute(
                """INSERT INTO agents (id, company_id, department_id, reporting_to, name, role,
                       objective, success_criteria, memory_scope, identity_ref, owner_id,
                       approver_id, can_request_critical, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    agent_id,
                    company_id,
                    department_id,
                    reporting_to,
                    name,
                    role,
                    objective,
                    dumps(success_criteria or []),
                    dumps(memory_scope or {}),
                    identity_ref,
                    owner_id,
                    approver_id,
                    int(can_request_critical),
                    now,
                    now,
                ),
            )
            self.ledger.append(
                actor_type="human",
                actor_id=actor_id,
                action="agent.create",
                resource_type="agent",
                resource_id=agent_id,
                outcome="success",
                correlation_id=new_id(),
                payload={"name": name, "role": role, "department_id": department_id},
                metadata={"owner_id": owner_id, "can_request_critical": can_request_critical},
            )
        return self.get(agent_id)

    def set_status(
        self, agent_id: str, status: AgentStatus, *, actor_type: str, actor_id: str, reason: str = ""
    ) -> dict[str, Any]:
        agent = self.get(agent_id)
        current = AgentStatus(agent["status"])
        if current == AgentStatus.RETIRED:
            raise GovernanceError("agent_retired", "a retired agent cannot change status")
        if current == status:
            return agent
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE agents SET status = ?, updated_at = ? WHERE id = ?",
                (status.value, iso(self.clock()), agent_id),
            )
            self.ledger.append(
                actor_type=actor_type,
                actor_id=actor_id,
                action="agent.status",
                resource_type="agent",
                resource_id=agent_id,
                outcome="success",
                correlation_id=new_id(),
                metadata={"from": current.value, "to": status.value, "reason": reason},
            )
        return self.get(agent_id)

    def update_work_status(self, agent_id: str, status: AgentStatus) -> None:
        """Runner bookkeeping. Never overrides paused, suspended or retired."""
        self.conn.execute(
            """UPDATE agents SET status = ?, updated_at = ?
               WHERE id = ? AND status NOT IN ('paused','suspended','retired')""",
            (status.value, iso(self.clock()), agent_id),
        )

    def retire(self, agent_id: str, *, actor_id: str, reason: str) -> dict[str, Any]:
        """Retire the agent and revoke every grant it holds in the same transaction."""
        self.get(agent_id)
        now = iso(self.clock())
        with transaction(self.conn):
            revoked = self.conn.execute(
                """UPDATE agent_tool_grants SET revoked_at = ?, revoked_by = ?
                   WHERE agent_id = ? AND revoked_at IS NULL""",
                (now, actor_id, agent_id),
            ).rowcount
            self.set_status(
                agent_id, AgentStatus.RETIRED, actor_type="human", actor_id=actor_id, reason=reason
            )
            self.ledger.append(
                actor_type="human",
                actor_id=actor_id,
                action="agent.retire",
                resource_type="agent",
                resource_id=agent_id,
                outcome="success",
                correlation_id=new_id(),
                metadata={"grants_revoked": revoked, "reason": reason},
            )
        return self.get(agent_id)


class PermissionService:
    def __init__(self, conn: sqlite3.Connection, ledger: AuditLedger, clock: Clock = utcnow):
        self.conn = conn
        self.ledger = ledger
        self.clock = clock

    def _tool(self, tool_key: str) -> dict[str, Any]:
        tool = row_to_dict(self.conn.execute("SELECT * FROM tools WHERE key = ?", (tool_key,)).fetchone())
        if tool is None:
            raise NotFound("tool", tool_key)
        return tool

    def grant(
        self,
        agent_id: str,
        tool_key: str,
        action: PermissionAction,
        *,
        granted_by: str,
        constraints: dict[str, Any] | None = None,
        expires_at: datetime | None = None,
    ) -> dict[str, Any]:
        tool = self._tool(tool_key)
        if self.conn.execute("SELECT 1 FROM agents WHERE id = ?", (agent_id,)).fetchone() is None:
            raise NotFound("agent", agent_id)
        grant_id = new_id()
        with transaction(self.conn):
            try:
                self.conn.execute(
                    """INSERT INTO agent_tool_grants
                       (id, agent_id, tool_id, action, constraints, granted_by, granted_at, expires_at)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (
                        grant_id,
                        agent_id,
                        tool["id"],
                        PermissionAction(action).value,
                        dumps(constraints or {}),
                        granted_by,
                        iso(self.clock()),
                        iso(expires_at) if expires_at else None,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise GovernanceError("grant_exists", "an active grant already covers this") from exc
            self.ledger.append(
                actor_type="human",
                actor_id=granted_by,
                action="grant.create",
                resource_type="agent",
                resource_id=agent_id,
                outcome="success",
                correlation_id=new_id(),
                payload={"tool_key": tool_key, "action": str(action), "constraints": constraints or {}},
                metadata={"grant_id": grant_id, "expires_at": iso(expires_at) if expires_at else None},
            )
        return self.get_grant(grant_id)

    def get_grant(self, grant_id: str) -> dict[str, Any]:
        grant = row_to_dict(
            self.conn.execute(
                """SELECT g.*, t.key AS tool_key, t.category, t.environment
                   FROM agent_tool_grants g JOIN tools t ON t.id = g.tool_id WHERE g.id = ?""",
                (grant_id,),
            ).fetchone()
        )
        if grant is None:
            raise NotFound("grant", grant_id)
        return grant

    def revoke(self, grant_id: str, *, revoked_by: str) -> dict[str, Any]:
        grant = self.get_grant(grant_id)
        if grant["revoked_at"]:
            return grant
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE agent_tool_grants SET revoked_at = ?, revoked_by = ? WHERE id = ?",
                (iso(self.clock()), revoked_by, grant_id),
            )
            self.ledger.append(
                actor_type="human",
                actor_id=revoked_by,
                action="grant.revoke",
                resource_type="agent",
                resource_id=grant["agent_id"],
                outcome="success",
                correlation_id=new_id(),
                metadata={"grant_id": grant_id, "tool_key": grant["tool_key"], "action": grant["action"]},
            )
        return self.get_grant(grant_id)

    def active_grant(self, agent_id: str, tool_key: str, action: str) -> dict[str, Any] | None:
        now = iso(self.clock())
        return row_to_dict(
            self.conn.execute(
                """SELECT g.*, t.key AS tool_key FROM agent_tool_grants g
                   JOIN tools t ON t.id = g.tool_id
                   WHERE g.agent_id = ? AND t.key = ? AND g.action = ?
                     AND g.revoked_at IS NULL AND (g.expires_at IS NULL OR g.expires_at > ?)""",
                (agent_id, tool_key, action, now),
            ).fetchone()
        )

    def grants_for(self, agent_id: str, *, include_inactive: bool = False) -> list[dict[str, Any]]:
        now = iso(self.clock())
        sql = """SELECT g.*, t.key AS tool_key, t.category, t.environment
                 FROM agent_tool_grants g JOIN tools t ON t.id = g.tool_id WHERE g.agent_id = ?"""
        params: list[Any] = [agent_id]
        if not include_inactive:
            sql += " AND g.revoked_at IS NULL AND (g.expires_at IS NULL OR g.expires_at > ?)"
            params.append(now)
        return rows_to_dicts(self.conn.execute(sql + " ORDER BY t.key, g.action", params).fetchall())

    def effective_permissions(self, agent_id: str, department_key: str) -> dict[str, Any]:
        """Aggregate capability across tools, and flag grants outside the department profile."""
        grants = self.grants_for(agent_id)
        profile = DEPARTMENT_PROFILES.get(department_key, {})
        capabilities: dict[str, set[str]] = {}
        environments: set[str] = set()
        sprawl: list[dict[str, Any]] = []
        for g in grants:
            capabilities.setdefault(g["action"], set()).add(g["category"])
            if g["action"] in ("execute", "propose"):
                environments.add(g["environment"])
            if g["category"] not in profile.get(g["action"], frozenset()):
                sprawl.append(
                    {
                        "grant_id": g["id"],
                        "tool_key": g["tool_key"],
                        "action": g["action"],
                        "category": g["category"],
                        "reason": f"{department_key} profile withholds {g['action']} on {g['category']}",
                    }
                )
        return {
            "agent_id": agent_id,
            "department": department_key,
            "grants": len(grants),
            "capabilities": {k: sorted(v) for k, v in sorted(capabilities.items())},
            "reachable_environments": sorted(environments),
            "can_reach_production": "production" in environments,
            "permission_sprawl": sprawl,
        }
