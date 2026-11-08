"""Data models for the ClearGlass Agent Office.

Sixteen record kinds, one dataclass each. They are plain data: behavior lives
in the office runtime, the policy engine, and the workflow engine. Every model
round-trips through ``to_dict`` / ``from_dict`` so the same shapes serve the
SQLite store, the API, and the PostgreSQL schema in ``infra/db/postgres``.

``tests/test_schema_parity.py`` asserts that every field here has a column in
the PostgreSQL schema. Add a field here and you must add the column there.
"""

from __future__ import annotations

from dataclasses import MISSING, asdict, dataclass, field, fields
from enum import StrEnum
from typing import Any, ClassVar, TypeVar


class RiskTier(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


TIER_ORDER: dict[str, int] = {"low": 0, "medium": 1, "high": 2, "critical": 3}
TIERS: tuple[str, ...] = ("low", "medium", "high", "critical")


def max_tier(*tiers: str) -> str:
    return max(tiers, key=lambda t: TIER_ORDER[t])


def bump_tier(tier: str, steps: int = 1) -> str:
    return TIERS[min(TIER_ORDER[tier] + steps, len(TIERS) - 1)]


class PermissionLevel(StrEnum):
    NONE = "none"
    READ = "read"
    PROPOSE = "propose"
    WRITE = "write"
    EXECUTE = "execute"


LEVEL_ORDER: dict[str, int] = {"none": 0, "read": 1, "propose": 2, "write": 3, "execute": 4}

# "approve" exists only for humans. The config validator rejects any agent grant
# that names it, and the approval desk refuses any decision made by an agent.
HUMAN_ONLY_LEVEL = "approve"


class AgentStatus(StrEnum):
    IDLE = "idle"
    WORKING = "working"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"
    RETIRED = "retired"


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_TASK_STATUSES = frozenset({"completed", "failed", "cancelled"})


class MissionStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    PAUSED = "paused"
    CANCELLED = "cancelled"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    EXECUTED = "executed"


class Clearance(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


CLEARANCE_ORDER: dict[str, int] = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}

R = TypeVar("R", bound="Record")


@dataclass
class Record:
    """Base for every stored record. ``KIND`` names the table / collection."""

    KIND: ClassVar[str] = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls: type[R], data: dict[str, Any]) -> R:
        names = {f.name for f in fields(cls)}
        unknown = set(data) - names
        if unknown:
            raise ValueError(f"{cls.__name__}: unknown fields {sorted(unknown)}")
        missing = [
            f.name for f in fields(cls) if f.name not in data and f.default is MISSING and f.default_factory is MISSING
        ]
        if missing:
            raise ValueError(f"{cls.__name__}: missing fields {missing}")
        return cls(**data)


@dataclass
class Company(Record):
    KIND: ClassVar[str] = "company"
    id: str
    name: str
    tagline: str
    brand_line: str
    region: str
    mission: str
    operator: dict[str, Any]
    objectives: list[dict[str, Any]] = field(default_factory=list)
    ideal_customer_profile: dict[str, Any] = field(default_factory=dict)
    approved_sources: list[dict[str, Any]] = field(default_factory=list)
    brand_guidelines: list[str] = field(default_factory=list)
    created_at: str = ""


@dataclass
class Department(Record):
    KIND: ClassVar[str] = "department"
    id: str
    name: str
    room: str
    head: str
    mission: str
    responsibilities: list[str] = field(default_factory=list)
    boundaries: list[str] = field(default_factory=list)


@dataclass
class Agent(Record):
    KIND: ClassVar[str] = "agent"
    id: str
    callsign: str
    name: str
    department: str
    reports_to: str
    objective: str
    room: str = ""
    success_criteria: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    permissions: dict[str, str] = field(default_factory=dict)
    memory_scopes: list[str] = field(default_factory=list)
    clearance: str = "internal"
    boundaries: list[str] = field(default_factory=list)
    status: str = AgentStatus.IDLE
    current_task_id: str | None = None
    metrics: dict[str, int] = field(
        default_factory=lambda: {
            "tasks_completed": 0,
            "tasks_failed": 0,
            "approvals_requested": 0,
            "policy_denials": 0,
        }
    )
    version: int = 1
    created_at: str = ""
    updated_at: str = ""


@dataclass
class Mission(Record):
    KIND: ClassVar[str] = "mission"
    id: str
    key: str
    title: str
    objective: str
    department: str
    owner: str
    priority: int = 3
    deadline: str | None = None
    deliverables: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    approval_rules: list[str] = field(default_factory=list)
    goal_ids: list[str] = field(default_factory=list)
    status: str = MissionStatus.ACTIVE
    workflow_id: str = ""
    created_by: str = ""
    created_at: str = ""
    updated_at: str = ""


@dataclass
class Task(Record):
    KIND: ClassVar[str] = "task"
    id: str
    key: str
    mission_id: str
    workflow_id: str
    title: str
    assignee: str
    action: dict[str, Any]
    depends_on: list[str] = field(default_factory=list)
    status: str = TaskStatus.PENDING
    resolved_action: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    approval_id: str | None = None
    attempts: int = 0
    max_attempts: int = 2
    error: str | None = None
    wave: int = 0
    started_at: str | None = None
    completed_at: str | None = None
    created_at: str = ""
    updated_at: str = ""


@dataclass
class Workflow(Record):
    KIND: ClassVar[str] = "workflow"
    id: str
    mission_id: str
    task_ids: list[str] = field(default_factory=list)
    waves: list[list[str]] = field(default_factory=list)
    status: str = "active"
    created_at: str = ""
    updated_at: str = ""


@dataclass
class Message(Record):
    KIND: ClassVar[str] = "message"
    id: str
    thread_id: str
    sender: str
    recipient: str
    kind: str
    subject: str
    body: str
    mission_id: str | None = None
    task_id: str | None = None
    refs: list[str] = field(default_factory=list)
    created_at: str = ""


@dataclass
class Decision(Record):
    KIND: ClassVar[str] = "decision"
    id: str
    made_by: str
    kind: str
    summary: str
    rationale: str
    outcome: str
    mission_id: str | None = None
    task_id: str | None = None
    refs: list[str] = field(default_factory=list)
    created_at: str = ""


@dataclass
class Approval(Record):
    KIND: ClassVar[str] = "approval"
    id: str
    action_type: str
    action: dict[str, Any]
    action_digest: str
    requested_by: str
    risk_tier: str
    reasons: list[str] = field(default_factory=list)
    task_id: str | None = None
    mission_id: str | None = None
    change_plan: str | None = None
    rollback_plan: str | None = None
    verification_plan: str | None = None
    status: str = ApprovalStatus.PENDING
    approved_digest: str | None = None
    approved_action: dict[str, Any] | None = None
    decisions: list[dict[str, Any]] = field(default_factory=list)
    execution: dict[str, Any] | None = None
    expires_at: str = ""
    created_at: str = ""
    updated_at: str = ""


@dataclass
class Tool(Record):
    KIND: ClassVar[str] = "tool"
    id: str
    name: str
    description: str
    connector: str
    actions: list[str]
    external: bool = False
    sandbox_only: bool = False
    risk_ceiling: str = "low"
    secret_ref: str | None = None


@dataclass
class Permission(Record):
    """One normalized grant row. ``Agent.permissions`` is the denormalized view."""

    KIND: ClassVar[str] = "permission"
    id: str
    agent_id: str
    domain: str
    level: str
    granted_by: str
    granted_at: str = ""


@dataclass
class MemoryRecord(Record):
    KIND: ClassVar[str] = "memory"
    id: str
    layer: str  # "short_term" | "long_term"
    scope: str
    title: str
    content: str
    source: str
    classification: str = "internal"
    status: str = "active"  # short_term: active|expired; long_term: proposed|approved|rejected
    created_by: str = ""
    approved_by: str | None = None
    tags: list[str] = field(default_factory=list)
    expires_at: str | None = None
    created_at: str = ""
    updated_at: str = ""


@dataclass
class AuditEvent(Record):
    KIND: ClassVar[str] = "audit_event"
    seq: int
    event_id: str
    ts: str
    actor: str
    actor_type: str
    event_type: str
    subject: str
    payload: dict[str, Any]
    risk_tier: str | None
    policy_version: str | None
    prev_hash: str
    hash: str


@dataclass
class Simulation(Record):
    KIND: ClassVar[str] = "simulation"
    id: str
    scenario_type: str
    title: str
    assumptions: dict[str, Any]
    options: list[dict[str, Any]]
    seed: int
    runs: int
    status: str = "completed"
    results: dict[str, Any] = field(default_factory=dict)
    recommendation: dict[str, Any] = field(default_factory=dict)
    disclaimer: str = ""
    created_by: str = ""
    created_at: str = ""


@dataclass
class Report(Record):
    KIND: ClassVar[str] = "report"
    id: str
    kind: str  # briefing | eod | weekly | incident | after_action | security_review
    title: str
    period: str
    generated_by: str
    sections: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    generated_at: str = ""


@dataclass
class RiskAssessment(Record):
    KIND: ClassVar[str] = "risk_assessment"
    id: str
    subject_type: str
    subject_id: str
    action_type: str
    tier: str
    score: int
    outcome: str  # allow | approval_required | deny
    factors: list[str] = field(default_factory=list)
    injection_suspected: bool = False
    policy_version: str = ""
    assessed_by: str = "policy-engine"
    created_at: str = ""


ALL_MODELS: tuple[type[Record], ...] = (
    Company,
    Department,
    Agent,
    Mission,
    Task,
    Workflow,
    Message,
    Decision,
    Approval,
    Tool,
    Permission,
    MemoryRecord,
    AuditEvent,
    Simulation,
    Report,
    RiskAssessment,
)
MODEL_BY_KIND: dict[str, type[Record]] = {m.KIND: m for m in ALL_MODELS}
