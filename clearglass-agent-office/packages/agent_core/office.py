"""The Office: one object that owns the store, the ledger, the policy engine,
the approval desk, the tool registry, memory, and the workflow engine.

The API, the worker, and the tests all drive the office through this class.
Operator actions (hiring, editing grants, approvals, emergency stop) take a
``Principal`` and are audited with the human as the actor.
"""

from __future__ import annotations

import copy
from datetime import timedelta
from pathlib import Path
from typing import Any

from agent_core.approvals import SYSTEM, ApprovalDesk, ApprovalError, Principal
from agent_core.config import ConfigError, OfficeConfig, build_agent, load_config, validate_agents
from agent_core.governance import GovernedExecutor, PerformResult
from agent_core.models import (
    HUMAN_ONLY_LEVEL,
    LEVEL_ORDER,
    Agent,
    Approval,
    Company,
    Decision,
    Department,
    Message,
    Mission,
    Permission,
    Report,
    Simulation,
    Task,
    Tool,
    Workflow,
)
from agent_core.providers import OfflineProvider, TextProvider
from agent_core.skills import HANDLERS
from agent_core.store import Store
from agent_core.util import Clock, IdFactory, random_ids
from agent_core.workflow import WorkflowEngine, WorkflowError
from audit_ledger.ledger import AuditLedger
from memory_vault.vault import MemoryVault
from policy_engine.engine import ActionRequest, GateDecision, OfficeState, PolicyEngine
from tool_registry.registry import ToolRegistry
from tool_registry.vault import SecretVault

AGENT_EDITABLE = (
    "name",
    "objective",
    "success_criteria",
    "skills",
    "room",
    "memory_scopes",
    "clearance",
    "reports_to",
    "tools",
    "permissions",
    "boundaries",
)


class OfficeError(ValueError):
    pass


class Office:
    def __init__(
        self,
        base_dir: str | Path,
        *,
        db_path: str | Path = ":memory:",
        clock: Clock | None = None,
        ids: IdFactory | None = None,
        provider: TextProvider | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self.base_dir = Path(base_dir).resolve()
        self.config: OfficeConfig = load_config(self.base_dir / "config")
        self.clock = clock or Clock()
        self.ids = ids or random_ids
        self.store = Store(db_path)
        self.audit = AuditLedger(self.store.conn, clock=self.clock.iso, lock=self.store.lock)
        self.policy = self.config.policy
        self.engine = PolicyEngine(self.policy)
        self.tools = ToolRegistry(self.config.tools)
        for action_type, handler in HANDLERS.items():
            self.tools.register(action_type, handler)
        self.vault = SecretVault(env)
        self.memory = MemoryVault(self.store, self.clock, self.ids, self.log)
        self.desk = ApprovalDesk(self)
        self.executor = GovernedExecutor(self)
        self.workflows = WorkflowEngine(self)
        self.provider: TextProvider = provider or OfflineProvider()
        self._bootstrap()

    # -- audit ------------------------------------------------------------------

    def log(
        self,
        actor: str,
        actor_type: str,
        event_type: str,
        subject: str,
        payload: dict[str, Any] | None = None,
        risk_tier: str | None = None,
    ) -> dict[str, Any]:
        return self.audit.append(
            actor=actor,
            actor_type=actor_type,
            event_type=event_type,
            subject=subject,
            payload=payload or {},
            risk_tier=risk_tier,
            policy_version=self.policy.version,
        )

    # -- bootstrap ----------------------------------------------------------------

    def _bootstrap(self) -> None:
        now = self.clock.iso()
        for tool in self.config.tools:  # tools always follow config: config is reviewed, the DB is not
            self.store.put(tool, now)
        if self.store.get(Company, self.config.company.id) is not None:
            return
        company = copy.deepcopy(self.config.company)
        company.created_at = now
        self.store.put(company, now)
        for d in self.config.departments:
            self.store.put(d, now)
        for agent in self.config.agents:
            agent = copy.deepcopy(agent)
            agent.created_at = agent.updated_at = now
            self.store.put(agent, now)
            self._write_grants(agent, "config/org.json")
        self.log(
            "system.office",
            "system",
            "office.bootstrapped",
            company.id,
            {
                "departments": len(self.config.departments),
                "agents": len(self.config.agents),
                "tools": len(self.config.tools),
                "policy_version": self.policy.version,
            },
        )
        self._seed_knowledge(company)

    def _seed_knowledge(self, company: Company) -> None:
        """Long-term memory the office starts with: reviewed config, recorded as operator-approved."""
        from agent_core.providers import DRAFTING_SYSTEM_PROMPT

        op = company.operator["id"]
        seeds = [
            (
                "Company objectives",
                "\n".join(
                    f"{o['id']}: {o['title']} (target {o['target']} {o['metric']}, due {o['due']})"
                    for o in company.objectives
                ),
                "config/company.json",
                ["goals"],
            ),
            ("Brand guidelines", "\n".join(company.brand_guidelines), "config/company.json", ["brand"]),
            ("Ideal customer profile", str(company.ideal_customer_profile), "config/company.json", ["customer"]),
            (
                "Approved research sources",
                "\n".join(f"{s['id']}: {s['label']}" for s in company.approved_sources),
                "config/company.json",
                ["policy"],
            ),
            (
                "Governance policy summary",
                "\n".join(f"{t}: {spec['summary']}" for t, spec in self.policy.tiers.items())
                + f"\nHard-blocked: {', '.join(sorted(self.policy.hard_blocked))}",
                "config/policy.json",
                ["policy"],
            ),
            (
                "Reusable prompt: drafting rewrite",
                DRAFTING_SYSTEM_PROMPT,
                "packages/agent_core/providers.py",
                ["prompt"],
            ),
            (
                "Technical documentation index",
                "docs/ARCHITECTURE.md, docs/API.md, docs/AGENT_MODEL.md, docs/WORKFLOW_ENGINE.md, "
                "docs/THREAT_MODEL.md, infra/db/postgres/001_init.sql",
                "docs/",
                ["technical"],
            ),
        ]
        for title, content, source, tags in seeds:
            self.memory.add_approved(op, "company", title, content, source, "internal", tags)

    def _write_grants(self, agent: Agent, granted_by: str) -> None:
        for domain, level in agent.permissions.items():
            self.store.put(
                Permission(
                    id=f"{agent.id}:{domain}",
                    agent_id=agent.id,
                    domain=domain,
                    level=level,
                    granted_by=granted_by,
                    granted_at=self.clock.iso(),
                ),
                self.clock.iso(),
            )

    # -- reads ----------------------------------------------------------------------

    def company(self) -> Company:
        company = self.store.get(Company, self.config.company.id)
        assert company is not None
        return company

    def departments(self) -> list[Department]:
        return self.store.list(Department)

    def agents(self) -> list[Agent]:
        return self.store.list(Agent)

    def agent(self, agent_id: str) -> Agent | None:
        return self.store.get(Agent, agent_id)

    def tool_list(self) -> list[Tool]:
        return list(self.tools.tools.values())

    def latest_report(self, kind: str) -> Report | None:
        items = self.store.list(Report, lambda r: r.kind == kind)
        items.sort(key=lambda r: r.generated_at)
        return items[-1] if items else None

    def halt_state(self) -> dict[str, Any]:
        return self.store.get_state("emergency_stop", {"halted": False})

    @property
    def halted(self) -> bool:
        return bool(self.halt_state().get("halted"))

    def state(self, ignore_halt: bool = False) -> OfficeState:
        halt = self.halt_state()
        return OfficeState(
            halted=bool(halt.get("halted")) and not ignore_halt,
            halted_reason=halt.get("reason"),
            approved_sources=tuple(s["id"] for s in self.company().approved_sources),
        )

    # -- governance -------------------------------------------------------------------

    def evaluate(
        self, request: ActionRequest, *, agent: Agent | None = None, ignore_halt: bool = False
    ) -> GateDecision:
        """Pure policy evaluation (steps 1-6). Never executes, never writes."""
        if agent is None:
            agent = self.agent(request.agent_id)
        return self.engine.evaluate(request, agent=agent, tools=self.tools.tools, state=self.state(ignore_halt))

    def perform(self, request: ActionRequest) -> PerformResult:
        result = self.executor.perform(request)
        if result.status == "completed" and result.output:
            self._apply_side_effects(request.agent_id, request.mission_id, request.task_id, result.output)
        return result

    def _apply_side_effects(
        self, agent_id: str, mission_id: str | None, task_id: str | None, output: dict[str, Any]
    ) -> None:
        for m in output.get("messages", []) or []:
            self.post_message(
                sender=agent_id,
                recipient=m["to"],
                kind=m.get("kind", "note"),
                subject=m.get("subject", ""),
                body=m.get("body", ""),
                mission_id=mission_id,
                task_id=task_id,
            )
        report = output.get("report")
        if report:
            now = self.clock.iso()
            rec = Report(
                id=self.ids("rpt"),
                kind=report["kind"],
                title=report["title"],
                period=self.clock.now().date().isoformat(),
                generated_by=agent_id,
                sections=report.get("sections", {}),
                metrics=report.get("metrics", {}),
                generated_at=now,
            )
            self.store.put(rec, now)
            output["report_id"] = rec.id
        decision = output.get("decision")
        if decision:
            self.record_decision(
                made_by=agent_id,
                kind=decision.get("kind", "agent"),
                summary=decision["summary"],
                rationale=decision.get("rationale", ""),
                outcome=decision.get("outcome", ""),
                mission_id=mission_id,
                task_id=task_id,
            )

    def bump_metric(self, agent_id: str, metric: str) -> None:
        agent = self.agent(agent_id)
        if agent is None:
            return
        agent.metrics[metric] = agent.metrics.get(metric, 0) + 1
        agent.updated_at = self.clock.iso()
        self.store.put(agent, agent.updated_at)

    def set_agent_status(self, agent_id: str, status: str, current_task_id: str | None = None) -> None:
        agent = self.agent(agent_id)
        if agent is None or agent.status in ("paused", "retired"):
            return
        agent.status = status
        agent.current_task_id = current_task_id
        agent.updated_at = self.clock.iso()
        self.store.put(agent, agent.updated_at)

    # -- collaboration ----------------------------------------------------------------

    def post_message(
        self,
        *,
        sender: str,
        recipient: str,
        kind: str,
        subject: str,
        body: str,
        mission_id: str | None = None,
        task_id: str | None = None,
        thread_id: str | None = None,
        refs: list[str] | None = None,
    ) -> Message:
        now = self.clock.iso()
        msg = Message(
            id=self.ids("msg"),
            thread_id=thread_id or mission_id or task_id or "general",
            sender=sender,
            recipient=recipient,
            kind=kind,
            subject=subject,
            body=body,
            mission_id=mission_id,
            task_id=task_id,
            refs=list(refs or []),
            created_at=now,
        )
        self.store.put(msg, now)
        return msg

    def messages(self, *, thread_id: str | None = None, kind: str | None = None, limit: int = 200) -> list[Message]:
        items = self.store.list(
            Message,
            lambda m: (thread_id is None or m.thread_id == thread_id) and (kind is None or m.kind == kind),
            newest_first=True,
        )
        return items[: max(1, min(limit, 1000))]

    def record_decision(
        self,
        *,
        made_by: str,
        kind: str,
        summary: str,
        rationale: str,
        outcome: str,
        mission_id: str | None = None,
        task_id: str | None = None,
        refs: list[str] | None = None,
    ) -> Decision:
        now = self.clock.iso()
        rec = Decision(
            id=self.ids("dec"),
            made_by=made_by,
            kind=kind,
            summary=summary,
            rationale=rationale,
            outcome=outcome,
            mission_id=mission_id,
            task_id=task_id,
            refs=list(refs or []),
            created_at=now,
        )
        self.store.put(rec, now)
        return rec

    # -- workflow hooks (called by WorkflowEngine) ------------------------------------------

    def save_task(self, task: Task) -> None:
        task.updated_at = self.clock.iso()
        self.store.put(task, task.updated_at)

    def after_task_completed(self, task: Task, output: dict[str, Any], by_id: dict[str, Task]) -> None:
        self._apply_side_effects(task.assignee, task.mission_id, task.id, output)
        try:
            self.memory.write_task(
                self.agent(task.assignee),
                task.mission_id,
                task.title,  # type: ignore[arg-type]
                str(output.get("summary", "")) or task.title,
                f"task:{task.id}",
            )
        except ValueError:
            pass  # a summary that trips the secret scanner is simply not remembered
        for child in self.store.list(Task, lambda t: task.id in t.depends_on):
            if child.assignee != task.assignee:
                self.post_message(
                    sender=task.assignee,
                    recipient=child.assignee,
                    kind="handoff",
                    subject=f"Handoff: {task.title} -> {child.title}",
                    body=str(output.get("summary", "")),
                    mission_id=task.mission_id,
                    task_id=task.id,
                )

    def after_task_held(self, task: Task, approval: Approval) -> None:
        agent = self.agent(task.assignee)
        to = agent.reports_to if agent else "operator"
        self.post_message(
            sender=task.assignee,
            recipient="operator",
            kind="escalation",
            subject=f"Approval needed: {approval.action_type} ({approval.risk_tier})",
            body=f"'{task.title}' is held in the Approval Desk as {approval.id}. "
            f"Reasons: {'; '.join(approval.reasons)}",
            mission_id=task.mission_id,
            task_id=task.id,
            refs=[approval.id],
        )
        if to != "operator":
            self.post_message(
                sender=task.assignee,
                recipient=to,
                kind="escalation",
                subject=f"FYI: {task.title} is waiting for the operator",
                body=f"Approval {approval.id}",
                mission_id=task.mission_id,
                task_id=task.id,
                refs=[approval.id],
            )

    def after_task_denied(self, task: Task, reason: str) -> None:
        agent = self.agent(task.assignee)
        self.post_message(
            sender="policy-engine",
            recipient=agent.reports_to if agent else "operator",
            kind="escalation",
            subject=f"Denied by policy: {task.title}",
            body=reason,
            mission_id=task.mission_id,
            task_id=task.id,
        )
        self.record_decision(
            made_by="policy-engine",
            kind="policy",
            summary=f"Denied: {task.title}",
            rationale=reason,
            outcome="deny",
            mission_id=task.mission_id,
            task_id=task.id,
        )

    def after_task_failed(self, task: Task) -> None:
        agent = self.agent(task.assignee)
        self.post_message(
            sender=task.assignee,
            recipient=agent.reports_to if agent else "operator",
            kind="escalation",
            subject=f"Task failed: {task.title}",
            body=task.error or "",
            mission_id=task.mission_id,
            task_id=task.id,
        )

    # -- missions ----------------------------------------------------------------------------

    def create_mission(self, spec: dict[str, Any], *, created_by: str) -> Mission:
        required = ("title", "objective", "department", "owner", "tasks")
        missing = [k for k in required if not spec.get(k)]
        if missing:
            raise OfficeError(f"mission is missing {missing}")
        if spec["department"] not in {d.id for d in self.departments()}:
            raise OfficeError(f"unknown department {spec['department']!r}")
        if self.agent(spec["owner"]) is None:
            raise OfficeError(f"unknown owner {spec['owner']!r}")
        now = self.clock.now()
        deadline = spec.get("deadline")
        if not deadline and spec.get("deadline_days") is not None:
            deadline = (now + timedelta(days=int(spec["deadline_days"]))).date().isoformat()
        mission = Mission(
            id=self.ids("msn"),
            key=str(spec.get("key") or ""),
            title=spec["title"],
            objective=spec["objective"],
            department=spec["department"],
            owner=spec["owner"],
            priority=int(spec.get("priority", 3)),
            deadline=deadline,
            deliverables=list(spec.get("deliverables", [])),
            constraints=list(spec.get("constraints", [])),
            approval_rules=list(spec.get("approval_rules", [])),
            goal_ids=list(spec.get("goal_ids", [])),
            created_by=created_by,
            created_at=now.isoformat(timespec="seconds"),
            updated_at=now.isoformat(timespec="seconds"),
        )
        try:
            workflow, tasks = self.workflows.build(mission, list(spec["tasks"]))
        except WorkflowError as exc:
            raise OfficeError(str(exc)) from exc
        mission.workflow_id = workflow.id
        self.store.put(mission, mission.created_at)
        self.store.put(workflow, workflow.created_at)
        for t in tasks:
            self.store.put(t, t.created_at)
        self.log(
            created_by,
            "human" if created_by.startswith("operator") else "agent",
            "mission.created",
            mission.id,
            {"title": mission.title, "tasks": len(tasks), "waves": len(workflow.waves)},
        )
        return mission

    def missions(self) -> list[Mission]:
        return self.store.list(Mission)

    def mission_detail(self, mission_id: str) -> dict[str, Any]:
        mission = self.store.get(Mission, mission_id)
        if mission is None:
            raise OfficeError("unknown mission")
        workflow = self.store.get(Workflow, mission.workflow_id)
        tasks = self.workflows.tasks(mission.workflow_id)
        return {
            "mission": mission.to_dict(),
            "workflow": workflow.to_dict() if workflow else None,
            "tasks": [t.to_dict() for t in tasks],
        }

    def run_mission(self, mission_id: str) -> dict[str, int]:
        mission = self.store.get(Mission, mission_id)
        if mission is None:
            raise OfficeError("unknown mission")
        if mission.status != "active":
            raise OfficeError(f"mission is {mission.status}")
        return self.workflows.run(mission.workflow_id)

    # -- approvals ----------------------------------------------------------------------------

    def decide_approval(
        self,
        approval_id: str,
        principal: Principal,
        decision: str,
        reason: str,
        modifications: dict[str, Any] | None = None,
        *,
        resume: bool = True,
    ) -> Approval:
        if self.halted and decision != "reject":
            raise ApprovalError("emergency stop engaged: approvals are frozen until it is released")
        approval = self.desk.decide(approval_id, principal, decision, reason, modifications)
        self.record_decision(
            made_by=principal.id,
            kind="operator",
            summary=f"{decision.capitalize()}: {approval.action_type}",
            rationale=reason,
            outcome=approval.status,
            mission_id=approval.mission_id,
            task_id=approval.task_id,
            refs=[approval.id],
        )
        task = self.store.get(Task, approval.task_id) if approval.task_id else None
        if task is not None and task.status == "waiting_approval":
            if approval.status == "approved" and approval.approved_action:
                task.status = "pending"
                task.resolved_action = {"type": approval.action_type, "params": approval.approved_action["params"]}
                self.save_task(task)
                self.post_message(
                    sender=principal.id,
                    recipient=task.assignee,
                    kind="decision",
                    subject=f"Approved: {task.title}",
                    body=reason,
                    mission_id=task.mission_id,
                    task_id=task.id,
                    refs=[approval.id],
                )
                if resume:
                    self.workflows.run(task.workflow_id)
            elif approval.status == "rejected":
                task.status = "cancelled"
                task.error = f"rejected by operator: {reason}"
                task.completed_at = self.clock.iso()
                self.save_task(task)
                self.set_agent_status(task.assignee, "idle")
                self.post_message(
                    sender=principal.id,
                    recipient=task.assignee,
                    kind="decision",
                    subject=f"Rejected: {task.title}",
                    body=reason,
                    mission_id=task.mission_id,
                    task_id=task.id,
                    refs=[approval.id],
                )
                self.workflows.run(task.workflow_id)  # propagates blocks downstream
        return self.desk.get(approval_id)  # type: ignore[return-value]

    # -- agents (operator actions) -------------------------------------------------------------

    def _check_grants(self, agent: Agent) -> None:
        dept = {d.id: d for d in self.departments()}
        rooms = {r["id"] for r in self.config.rooms}
        others = [a for a in self.agents() if a.id != agent.id]
        problems = validate_agents([*others, agent], dept, self.tools.tools, rooms, self.policy)
        mine = [p for p in problems if agent.id in p or "duplicate" in p]
        if mine:
            raise OfficeError("; ".join(mine))

    def hire_agent(self, spec: dict[str, Any], principal: Principal) -> Agent:
        if self.agent(str(spec.get("id", ""))) is not None:
            raise OfficeError("an agent with that id already exists")
        dept = {d.id: d for d in self.departments()}
        try:
            agent = build_agent(spec, self.config.base_grants, dept)
        except (KeyError, ConfigError) as exc:
            raise OfficeError(f"invalid agent spec: {exc}") from exc
        agent.created_at = agent.updated_at = self.clock.iso()
        self._check_grants(agent)
        self.store.put(agent, agent.created_at)
        self._write_grants(agent, principal.id)
        self.log(
            principal.id,
            "human",
            "agent.hired",
            agent.id,
            {"department": agent.department, "permissions": agent.permissions, "tools": agent.tools},
            "medium",
        )
        return agent

    def clone_agent(self, agent_id: str, new_id: str, callsign: str, principal: Principal) -> Agent:
        src = self.agent(agent_id)
        if src is None:
            raise OfficeError("unknown agent")
        spec = {
            **{
                k: getattr(src, k)
                for k in (
                    "department",
                    "reports_to",
                    "objective",
                    "success_criteria",
                    "skills",
                    "memory_scopes",
                    "clearance",
                    "room",
                )
            },
            "id": new_id,
            "callsign": callsign,
            "name": f"{src.name} (clone)",
            "permissions": dict(src.permissions),
            "tools": list(src.tools),
        }
        agent = self.hire_agent(spec, principal)
        self.log(principal.id, "human", "agent.cloned", agent.id, {"from": agent_id})
        return agent

    def update_agent(self, agent_id: str, changes: dict[str, Any], principal: Principal) -> Agent:
        agent = self.agent(agent_id)
        if agent is None:
            raise OfficeError("unknown agent")
        if agent.status == "retired":
            raise OfficeError("retired agents cannot be edited")
        bad = set(changes) - set(AGENT_EDITABLE)
        if bad:
            raise OfficeError(f"not editable: {sorted(bad)}")
        for level in (changes.get("permissions") or {}).values():
            if level == HUMAN_ONLY_LEVEL or level not in LEVEL_ORDER:
                raise OfficeError(f"invalid permission level {level!r}")
        before = {k: copy.deepcopy(getattr(agent, k)) for k in changes}
        for k, v in changes.items():
            setattr(agent, k, v)
        agent.version += 1
        agent.updated_at = self.clock.iso()
        self._check_grants(agent)
        self.store.put(agent, agent.updated_at)
        if "permissions" in changes:
            self._write_grants(agent, principal.id)
        sensitive = bool({"permissions", "tools", "clearance"} & set(changes))
        self.log(
            principal.id,
            "human",
            "agent.updated",
            agent.id,
            {"before": before, "after": changes, "version": agent.version},
            "high" if sensitive else "low",
        )
        return agent

    def set_agent_lifecycle(self, agent_id: str, action: str, principal: Principal, reason: str = "") -> Agent:
        agent = self.agent(agent_id)
        if agent is None:
            raise OfficeError("unknown agent")
        transitions = {
            "pause": ("paused", {"idle", "working", "waiting_for_approval", "blocked", "completed", "failed"}),
            "resume": ("idle", {"paused"}),
            "retire": ("retired", {"idle", "paused", "blocked", "completed", "failed"}),
        }
        if action not in transitions:
            raise OfficeError(f"unknown lifecycle action {action!r}")
        target, allowed = transitions[action]
        if agent.status not in allowed:
            raise OfficeError(f"cannot {action} an agent that is {agent.status}")
        agent.status = target
        agent.current_task_id = None if action == "retire" else agent.current_task_id
        agent.updated_at = self.clock.iso()
        self.store.put(agent, agent.updated_at)
        self.log(principal.id, "human", f"agent.{action}", agent.id, {"reason": reason})
        return agent

    # -- emergency stop ----------------------------------------------------------------------------

    def emergency_stop(self, principal: Principal, reason: str) -> dict[str, Any]:
        if principal.kind != "human":
            raise ApprovalError("only a human operator can engage the emergency stop")
        if len(reason.strip()) < self.policy.min_reason_chars:
            raise ApprovalError(f"a reason of at least {self.policy.min_reason_chars} characters is required")
        if self.halted:
            return self.halt_state()
        now = self.clock.iso()
        paused = []
        for agent in self.agents():
            if agent.status not in ("paused", "retired"):
                agent.status = "paused"
                agent.updated_at = now
                self.store.put(agent, now)
                paused.append(agent.id)
        cancelled = self.desk.cancel_open(principal, f"emergency stop: {reason}")
        held_tasks = []
        for task in self.store.list(Task, lambda t: t.status == "waiting_approval" and t.approval_id in cancelled):
            task.status = "blocked"
            task.error = "approval cancelled by emergency stop"
            self.save_task(task)
            held_tasks.append(task.id)
        incident = Report(
            id=self.ids("inc"),
            kind="incident",
            title=f"Emergency stop: {reason}",
            period=self.clock.now().date().isoformat(),
            generated_by=principal.id,
            sections={
                "what_happened": reason,
                "when": now,
                "engaged_by": principal.id,
                "agents_paused": paused,
                "approvals_cancelled": cancelled,
                "tasks_blocked": held_tasks,
                "state_preserved": "No record was deleted. Tasks, approvals, and memory are kept as they were.",
                "containment_status": "contained: all agents paused, no external action can execute",
                "required_human_decision": "Investigate, then release the stop with a reason.",
            },
            metrics={"agents_paused": len(paused), "approvals_cancelled": len(cancelled)},
            generated_at=now,
        )
        self.store.put(incident, now)
        state = {
            "halted": True,
            "reason": reason,
            "engaged_by": principal.id,
            "engaged_at": now,
            "incident_id": incident.id,
        }
        self.store.set_state("emergency_stop", state)
        self.post_message(
            sender="system.office",
            recipient="operator",
            kind="notification",
            subject="EMERGENCY STOP ENGAGED",
            body=f"{reason}. Incident {incident.id}.",
            thread_id="emergency",
            refs=[incident.id],
        )
        self.log(
            principal.id,
            "human",
            "emergency.engaged",
            incident.id,
            {"reason": reason, "agents_paused": len(paused), "approvals_cancelled": cancelled},
            "critical",
        )
        return state

    def release_emergency_stop(self, principal: Principal, reason: str) -> dict[str, Any]:
        if principal.kind != "human":
            raise ApprovalError("only a human operator can release the emergency stop")
        if len(reason.strip()) < self.policy.min_reason_chars:
            raise ApprovalError(f"a reason of at least {self.policy.min_reason_chars} characters is required")
        state = self.halt_state()
        if not state.get("halted"):
            return state
        now = self.clock.iso()
        resumed = []
        for agent in self.agents():
            if agent.status == "paused":
                agent.status = "idle"
                agent.updated_at = now
                self.store.put(agent, now)
                resumed.append(agent.id)
        new_state = {
            "halted": False,
            "released_by": principal.id,
            "released_at": now,
            "release_reason": reason,
            "previous": state,
        }
        self.store.set_state("emergency_stop", new_state)
        self.log(
            principal.id,
            "human",
            "emergency.released",
            state.get("incident_id", "office"),
            {"reason": reason, "agents_resumed": len(resumed)},
            "high",
        )
        return new_state

    # -- simulation ----------------------------------------------------------------------------

    def run_simulation(self, agent_id: str, spec: dict[str, Any]) -> PerformResult:
        params = {k: spec[k] for k in ("scenario_type", "assumptions", "options", "seed", "runs", "title") if k in spec}
        return self.perform(ActionRequest(agent_id=agent_id, action_type="simulation.run", params=params, sandbox=True))

    def simulations(self) -> list[Simulation]:
        return self.store.list(Simulation, newest_first=True)

    # -- health ----------------------------------------------------------------------------------

    def readiness(self) -> dict[str, Any]:
        checks: dict[str, Any] = {}
        try:
            checks["database"] = self.store.ping()
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            checks["database"] = False
            checks["database_error"] = type(exc).__name__
        chain = self.audit.verify() if checks["database"] else None
        checks["audit_chain"] = bool(chain and chain.ok)
        checks["halted"] = self.halted if checks["database"] else None
        return {"ready": bool(checks["database"] and checks["audit_chain"]), "checks": checks}


__all__ = ["SYSTEM", "Office", "OfficeError", "Principal"]
