"""Two-layer agent memory.

- Short-term task memory: scoped to a mission, written freely by agents working
  on it, expires at the end of the operating day.
- Long-term company memory: what the whole office may rely on. Agents can only
  *propose* records; a human operator approves or rejects each one. This is the
  defense against memory poisoning: an injected instruction in a prospect note
  cannot become company policy without a named person accepting it.

Reads are filtered by the agent's memory scopes (fnmatch patterns such as
``dept:eng`` or ``mission:*``) and by clearance. Writes that contain
credential-shaped strings are rejected outright.
"""

from __future__ import annotations

import fnmatch
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from agent_core.models import CLEARANCE_ORDER, Agent, MemoryRecord
from agent_core.store import Store
from agent_core.util import Clock, IdFactory, parse_iso
from audit_ledger.canonical import find_secrets

AuditFn = Callable[..., Any]


class MemoryError_(ValueError):
    """Rejected memory write (named to avoid shadowing the builtin MemoryError)."""


class MemoryVault:
    def __init__(self, store: Store, clock: Clock, ids: IdFactory, audit: AuditFn) -> None:
        self.store = store
        self.clock = clock
        self.ids = ids
        self.audit = audit

    # -- writes ---------------------------------------------------------------

    def _guard(self, title: str, content: str, classification: str) -> None:
        if classification not in CLEARANCE_ORDER:
            raise MemoryError_(f"unknown classification {classification!r}")
        hits = find_secrets(f"{title}\n{content}")
        if hits:
            raise MemoryError_(f"memory write rejected: credential-shaped content ({', '.join(hits)})")
        if not content.strip():
            raise MemoryError_("memory content is empty")

    def write_task(self, agent: Agent, mission_id: str, title: str, content: str, source: str) -> MemoryRecord:
        self._guard(title, content, "internal")
        now = self.clock.now()
        record = MemoryRecord(
            id=self.ids("mem"),
            layer="short_term",
            scope=f"mission:{mission_id}",
            title=title,
            content=content,
            source=source,
            classification="internal",
            status="active",
            created_by=agent.id,
            expires_at=(now + timedelta(hours=24)).isoformat(timespec="seconds"),
            created_at=now.isoformat(timespec="seconds"),
            updated_at=now.isoformat(timespec="seconds"),
        )
        self.store.put(record, record.created_at)
        return record

    def propose(
        self,
        agent: Agent,
        scope: str,
        title: str,
        content: str,
        source: str,
        classification: str = "internal",
        tags: list[str] | None = None,
    ) -> MemoryRecord:
        self._guard(title, content, classification)
        now = self.clock.iso()
        record = MemoryRecord(
            id=self.ids("mem"),
            layer="long_term",
            scope=scope,
            title=title,
            content=content,
            source=source,
            classification=classification,
            status="proposed",
            created_by=agent.id,
            tags=list(tags or []),
            created_at=now,
            updated_at=now,
        )
        self.store.put(record, now)
        self.audit(
            actor=agent.id,
            actor_type="agent",
            event_type="memory.proposed",
            subject=record.id,
            payload={"scope": scope, "title": title, "source": source},
        )
        return record

    def add_approved(
        self,
        operator_id: str,
        scope: str,
        title: str,
        content: str,
        source: str,
        classification: str = "internal",
        tags: list[str] | None = None,
    ) -> MemoryRecord:
        self._guard(title, content, classification)
        now = self.clock.iso()
        record = MemoryRecord(
            id=self.ids("mem"),
            layer="long_term",
            scope=scope,
            title=title,
            content=content,
            source=source,
            classification=classification,
            status="approved",
            created_by=operator_id,
            approved_by=operator_id,
            tags=list(tags or []),
            created_at=now,
            updated_at=now,
        )
        self.store.put(record, now)
        self.audit(
            actor=operator_id,
            actor_type="human",
            event_type="memory.added",
            subject=record.id,
            payload={"scope": scope, "title": title, "source": source},
        )
        return record

    def decide(self, record_id: str, operator_id: str, approve: bool, reason: str) -> MemoryRecord:
        record = self.store.get(MemoryRecord, record_id)
        if record is None:
            raise MemoryError_("unknown memory record")
        if record.status != "proposed":
            raise MemoryError_(f"record is {record.status}, not proposed")
        if len(reason.strip()) < 12:
            raise MemoryError_("a reason of at least 12 characters is required")
        record.status = "approved" if approve else "rejected"
        record.approved_by = operator_id if approve else None
        record.updated_at = self.clock.iso()
        self.store.put(record, record.updated_at)
        self.audit(
            actor=operator_id,
            actor_type="human",
            event_type=f"memory.{record.status}",
            subject=record.id,
            payload={"reason": reason},
        )
        return record

    # -- reads ----------------------------------------------------------------

    def visible_to(self, agent: Agent, record: MemoryRecord) -> bool:
        if CLEARANCE_ORDER[record.classification] > CLEARANCE_ORDER.get(agent.clearance, 0):
            return False
        if not any(fnmatch.fnmatchcase(record.scope, pat) for pat in agent.memory_scopes):
            return False
        if record.layer == "long_term":
            return record.status == "approved"
        return record.status == "active" and not self._expired(record)

    def read(self, agent: Agent, scope_prefix: str | None = None) -> list[MemoryRecord]:
        return self.store.list(
            MemoryRecord,
            lambda r: self.visible_to(agent, r) and (scope_prefix is None or r.scope.startswith(scope_prefix)),
        )

    def all(self, layer: str | None = None) -> list[MemoryRecord]:
        return self.store.list(MemoryRecord, lambda r: layer is None or r.layer == layer, newest_first=True)

    def expire(self) -> int:
        n = 0
        for record in self.store.list(MemoryRecord, lambda r: r.layer == "short_term" and r.status == "active"):
            if self._expired(record):
                record.status = "expired"
                record.updated_at = self.clock.iso()
                self.store.put(record, record.updated_at)
                n += 1
        return n

    def _expired(self, record: MemoryRecord) -> bool:
        return bool(record.expires_at) and parse_iso(record.expires_at) <= self.clock.now()
