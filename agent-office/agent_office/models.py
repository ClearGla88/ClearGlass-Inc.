"""Shared enums, value objects and errors."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Callable

Clock = Callable[[], datetime]


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="microseconds")


def canonical_json(value: Any) -> str:
    """Deterministic JSON used for every hash in the system."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def sha256_hex(value: Any) -> str:
    data = value if isinstance(value, str) else canonical_json(value)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return _RISK_ORDER[self]

    def at_least(self, other: RiskLevel) -> RiskLevel:
        return self if self.rank >= other.rank else other


_RISK_ORDER = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2, RiskLevel.CRITICAL: 3}
APPROVAL_REQUIRED_RISKS = frozenset({RiskLevel.HIGH, RiskLevel.CRITICAL})


class AgentStatus(StrEnum):
    IDLE = "idle"
    WORKING = "working"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"
    SUSPENDED = "suspended"
    RETIRED = "retired"


# An agent in any other status cannot act at all.
ACTIVE_AGENT_STATUSES = frozenset(
    {
        AgentStatus.IDLE,
        AgentStatus.WORKING,
        AgentStatus.WAITING_FOR_APPROVAL,
        AgentStatus.BLOCKED,
        AgentStatus.COMPLETED,
        AgentStatus.FAILED,
    }
)


class PermissionAction(StrEnum):
    READ = "read"
    WRITE = "write"
    # May ask for execution. The gate routes the request to a human approval
    # and, once approved, executes it under that approval only (JIT elevation).
    PROPOSE = "propose"
    EXECUTE = "execute"
    # May decide other agents' approvals, for low and medium risk only.
    APPROVE = "approve"


# Operations a tool can declare. ``propose`` and ``approve`` are grant types,
# not operations.
TOOL_OPERATIONS = frozenset({PermissionAction.READ, PermissionAction.WRITE, PermissionAction.EXECUTE})


class MissionStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    MODIFIED = "modified"  # approved with a changed payload
    EXPIRED = "expired"
    CANCELLED = "cancelled"


EXECUTABLE_APPROVAL_STATUSES = frozenset({ApprovalStatus.APPROVED, ApprovalStatus.MODIFIED})


class GovernanceError(Exception):
    """A request refused by a governance rule. ``code`` is stable and machine-readable."""

    status_code = 409

    def __init__(self, code: str, message: str = "", *, status_code: int | None = None):
        super().__init__(message or code)
        self.code = code
        self.message = message or code
        if status_code is not None:
            self.status_code = status_code


class NotFound(GovernanceError):
    status_code = 404

    def __init__(self, what: str, ident: str):
        super().__init__("not_found", f"{what} {ident} not found")


class AuditFailure(Exception):
    """The ledger could not record an event. Callers must fail closed."""


@dataclass(frozen=True)
class ActionRequest:
    """One agent's request to use one tool. The unit the gate evaluates."""

    agent_id: str
    tool_key: str
    action: str
    payload: dict[str, Any] = field(default_factory=dict)
    mission_id: str | None = None
    task_id: str | None = None
    correlation_id: str | None = None
    approval_id: str | None = None

    def request_hash(self) -> str:
        """Binds an approval to exactly this request. Any change breaks the match."""
        return sha256_hex(
            {
                "agent_id": self.agent_id,
                "tool_key": self.tool_key,
                "action": self.action,
                "payload": self.payload,
                "mission_id": self.mission_id,
                "task_id": self.task_id,
            }
        )


@dataclass
class GateOutcome:
    status: str  # executed | waiting_for_approval | denied | failed
    correlation_id: str
    code: str = ""
    message: str = ""
    risk_level: RiskLevel | None = None
    approval_id: str | None = None
    result: dict[str, Any] | None = None
    verified: bool | None = None
    policy_ids: list[str] = field(default_factory=list)

    @property
    def executed(self) -> bool:
        return self.status == "executed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "correlation_id": self.correlation_id,
            "code": self.code,
            "message": self.message,
            "risk_level": self.risk_level.value if self.risk_level else None,
            "approval_id": self.approval_id,
            "result": self.result,
            "verified": self.verified,
            "policy_ids": self.policy_ids,
        }
