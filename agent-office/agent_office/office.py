"""Composition root: one object that wires the services together."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from typing import Any

from . import db
from .approvals import ApprovalService
from .audit import AuditLedger
from .emergency import EmergencyService
from .gate import GovernanceGate
from .identity import IdentityService, PermissionService
from .missions import MissionRunner, MissionService
from .models import Clock, utcnow
from .policy import PolicyEngine
from .tools import SecretBroker, ToolRegistry

COMPANY_SLUG = "clearglass"


class Office:
    def __init__(
        self,
        path: str = ":memory:",
        *,
        clock: Clock = utcnow,
        policy: PolicyEngine | None = None,
        registry: ToolRegistry | None = None,
        environ: Mapping[str, str] | None = None,
        seed: bool = True,
    ):
        self.clock = clock
        self.conn: sqlite3.Connection = db.connect(path)
        self.registry = registry or ToolRegistry.builtin()
        self.registry.sync(self.conn)
        self.policy = policy or PolicyEngine.load()
        if seed:
            from .seed import seed_company

            seed_company(self.conn, clock)
        company = self.conn.execute("SELECT id FROM companies WHERE slug = ?", (COMPANY_SLUG,)).fetchone()
        self.company_id: str = company["id"] if company else ""
        self.ledger = AuditLedger(self.conn, self.company_id, clock)
        self.identity = IdentityService(self.conn, self.ledger, clock)
        self.permissions = PermissionService(self.conn, self.ledger, clock)
        self.approvals = ApprovalService(self.conn, self.ledger, clock)
        self.emergency = EmergencyService(self.conn, self.ledger, self.approvals, clock)
        self.gate = GovernanceGate(
            conn=self.conn,
            company_id=self.company_id,
            ledger=self.ledger,
            identity=self.identity,
            permissions=self.permissions,
            policy=self.policy,
            registry=self.registry,
            approvals=self.approvals,
            emergency=self.emergency,
            secrets=SecretBroker(environ),
            clock=clock,
        )
        self.missions = MissionService(self.conn, self.ledger, self.company_id, clock)
        self.runner = MissionRunner(
            conn=self.conn,
            gate=self.gate,
            missions=self.missions,
            approvals=self.approvals,
            identity=self.identity,
            clock=clock,
        )

    def agent_id(self, name: str) -> str:
        return self.identity.find_by_name(name)["id"]

    def company(self) -> dict[str, Any]:
        return db.row_to_dict(
            self.conn.execute("SELECT * FROM companies WHERE id = ?", (self.company_id,)).fetchone()
        ) or {}

    def departments(self) -> list[dict[str, Any]]:
        return db.rows_to_dicts(
            self.conn.execute(
                "SELECT * FROM departments WHERE company_id = ? ORDER BY floor_index", (self.company_id,)
            ).fetchall()
        )

    def close(self) -> None:
        self.conn.close()
