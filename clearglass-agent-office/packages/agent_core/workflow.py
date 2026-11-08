"""Workflow engine: missions as dependency graphs of tasks.

- ``build`` validates a mission's task graph (unique keys, known dependencies, no
  cycles) and assigns each task a *wave*: tasks in the same wave have no
  dependency on each other and may run in parallel; waves run in order.
- ``run`` advances a workflow until nothing more can move: it executes every
  ready task through the governed executor, retries failures up to
  ``max_attempts``, holds tasks that need approval, and blocks every task
  downstream of a failure, rejection, or cancellation.
- Inputs written as ``{"$from": "<task key>", "path": "a.b.0"}`` are resolved
  from upstream outputs just before the policy engine sees the action, so the
  approved digest covers the real payload.

The MVP worker executes the tasks of a wave one after another in a
deterministic order, which keeps the audit chain reproducible. The queue-based
worker on the roadmap runs a wave's tasks concurrently; the graph semantics do
not change.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import TYPE_CHECKING, Any

from agent_core.models import TERMINAL_TASK_STATUSES, Agent, Mission, Task, Workflow
from policy_engine.engine import ActionRequest

if TYPE_CHECKING:
    from agent_core.office import Office


class WorkflowError(ValueError):
    pass


def compute_waves(keys: list[str], deps: dict[str, list[str]]) -> dict[str, int]:
    indegree = {k: len(deps.get(k, [])) for k in keys}
    children: dict[str, list[str]] = defaultdict(list)
    for k in keys:
        for d in deps.get(k, []):
            children[d].append(k)
    wave = {k: 0 for k in keys}
    queue = deque(k for k in keys if indegree[k] == 0)
    seen = 0
    while queue:
        k = queue.popleft()
        seen += 1
        for c in children[k]:
            wave[c] = max(wave[c], wave[k] + 1)
            indegree[c] -= 1
            if indegree[c] == 0:
                queue.append(c)
    if seen != len(keys):
        raise WorkflowError("task graph has a cycle")
    return wave


def resolve_refs(value: Any, outputs: dict[str, dict[str, Any] | None]) -> Any:
    if isinstance(value, dict):
        if set(value) == {"$from", "path"}:
            source = outputs.get(value["$from"])
            if source is None:
                raise WorkflowError(f"input from '{value['$from']}' is not available")
            node: Any = source
            for part in str(value["path"]).split("."):
                if isinstance(node, list) and part.isdigit() and int(part) < len(node):
                    node = node[int(part)]
                elif isinstance(node, dict) and part in node:
                    node = node[part]
                else:
                    raise WorkflowError(f"path '{value['path']}' not found in output of '{value['$from']}'")
            return node
        return {k: resolve_refs(v, outputs) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_refs(v, outputs) for v in value]
    return value


class WorkflowEngine:
    def __init__(self, office: Office) -> None:
        self.office = office

    # -- construction ------------------------------------------------------------

    def build(self, mission: Mission, specs: list[dict[str, Any]]) -> tuple[Workflow, list[Task]]:
        o = self.office
        if not specs:
            raise WorkflowError("a mission needs at least one task")
        keys = [str(s.get("key", "")) for s in specs]
        if "" in keys or len(set(keys)) != len(keys):
            raise WorkflowError("task keys must be present and unique")
        deps = {str(s["key"]): list(s.get("depends_on", [])) for s in specs}
        for k, ds in deps.items():
            missing = [d for d in ds if d not in deps]
            if missing:
                raise WorkflowError(f"task '{k}' depends on unknown task(s) {missing}")
        for s in specs:
            if o.agent(str(s.get("assignee", ""))) is None:
                raise WorkflowError(f"task '{s['key']}': unknown assignee {s.get('assignee')!r}")
            action = s.get("action") or {}
            if not isinstance(action, dict) or not action.get("type"):
                raise WorkflowError(f"task '{s['key']}': action.type is required")
        waves = compute_waves(keys, deps)
        now = o.clock.iso()
        workflow = Workflow(id=o.ids("wf"), mission_id=mission.id, created_at=now, updated_at=now)
        ids = {k: o.ids("task") for k in keys}
        tasks = [
            Task(
                id=ids[s["key"]],
                key=s["key"],
                mission_id=mission.id,
                workflow_id=workflow.id,
                title=str(s.get("title") or s["key"]),
                assignee=str(s["assignee"]),
                action={"type": s["action"]["type"], "params": s["action"].get("params", {})},
                depends_on=[ids[d] for d in deps[s["key"]]],
                wave=waves[s["key"]],
                max_attempts=int(s.get("max_attempts", 2)),
                created_at=now,
                updated_at=now,
            )
            for s in specs
        ]
        workflow.task_ids = [t.id for t in tasks]
        n_waves = max(waves.values()) + 1
        workflow.waves = [[t.id for t in tasks if t.wave == w] for w in range(n_waves)]
        return workflow, tasks

    # -- execution -----------------------------------------------------------------

    def tasks(self, workflow_id: str) -> list[Task]:
        wf = self.office.store.get(Workflow, workflow_id)
        if wf is None:
            raise WorkflowError("unknown workflow")
        by_id = {t.id: t for t in self.office.store.list(Task, lambda t: t.workflow_id == workflow_id)}
        return [by_id[i] for i in wf.task_ids if i in by_id]

    def run(self, workflow_id: str, max_rounds: int = 50) -> dict[str, int]:
        o = self.office
        ran = 0
        for _ in range(max_rounds):
            if o.halted:
                break
            tasks = self.tasks(workflow_id)
            by_id = {t.id: t for t in tasks}
            self._propagate_blocks(tasks, by_id)
            ready = [
                t for t in tasks if t.status == "pending" and all(by_id[d].status == "completed" for d in t.depends_on)
            ]
            if not ready:
                break
            ready.sort(key=lambda t: (t.wave, t.id))
            for task in ready:
                if o.halted:
                    break
                self.run_task(task, by_id)
                ran += 1
        self._finish(workflow_id)
        counts: dict[str, int] = defaultdict(int)
        for t in self.tasks(workflow_id):
            counts[t.status] += 1
        counts["ran"] = ran
        return dict(counts)

    def run_task(self, task: Task, by_id: dict[str, Task]) -> Task:
        o = self.office
        agent = o.store.get(Agent, task.assignee)
        outputs_by_key = {by_id[a].key: by_id[a].output for a in self._ancestors(task, by_id)}
        if task.resolved_action is None:
            try:
                params = resolve_refs(task.action.get("params", {}), outputs_by_key)
            except WorkflowError as exc:
                return self._settle(task, agent, "failed", error=f"input resolution failed: {exc}")
            task.resolved_action = {"type": task.action["type"], "params": params}

        task.status = "running"
        task.attempts += 1
        task.started_at = task.started_at or o.clock.iso()
        o.save_task(task)
        o.set_agent_status(task.assignee, "working", current_task_id=task.id)

        request = ActionRequest(
            agent_id=task.assignee,
            action_type=task.resolved_action["type"],
            params=task.resolved_action["params"],
            task_id=task.id,
            mission_id=task.mission_id,
            approval_id=task.approval_id,
        )
        result = o.executor.perform(request)
        governance = {
            "outcome": result.status,
            "tier": result.decision.tier,
            "score": result.decision.score,
            "digest": result.decision.digest,
            "trace": result.trace(),
            "policy_version": result.decision.policy_version,
        }

        if result.status == "completed":
            output = dict(result.output or {})
            output["governance"] = governance
            task.output = output
            task = self._settle(task, agent, "completed")
            o.after_task_completed(task, output, by_id)
        elif result.status == "waiting_approval":
            assert result.approval is not None
            task.approval_id = result.approval.id
            task.output = {"governance": governance}
            task = self._settle(task, agent, "waiting_approval")
            o.after_task_held(task, result.approval)
        elif result.status == "denied":
            task.output = {"governance": governance}
            task = self._settle(task, agent, "failed", error=f"denied: {result.error}")
            o.after_task_denied(task, result.error or "")
        else:
            task.output = {"governance": governance, **({"partial": result.output} if result.output else {})}
            if task.attempts < task.max_attempts:
                task.status = "pending"
                task.error = f"attempt {task.attempts} failed: {result.error}"
                o.save_task(task)
                o.set_agent_status(task.assignee, "idle")
            else:
                task = self._settle(task, agent, "failed", error=result.error)
                o.after_task_failed(task)
        return task

    @staticmethod
    def _ancestors(task: Task, by_id: dict[str, Task]) -> set[str]:
        """Every task upstream of ``task``. Inputs may come from any of them, never from a sibling."""
        seen: set[str] = set()
        stack = list(task.depends_on)
        while stack:
            tid = stack.pop()
            if tid in seen or tid not in by_id:
                continue
            seen.add(tid)
            stack.extend(by_id[tid].depends_on)
        return seen

    def _settle(self, task: Task, agent: Agent | None, status: str, error: str | None = None) -> Task:
        o = self.office
        task.status = status
        task.error = error
        if status in TERMINAL_TASK_STATUSES:
            task.completed_at = o.clock.iso()
        o.save_task(task)
        agent_status = {
            "completed": "completed",
            "waiting_approval": "waiting_for_approval",
            "failed": "failed",
            "blocked": "blocked",
        }.get(status, "idle")
        if agent is not None:
            o.set_agent_status(agent.id, agent_status, current_task_id=None if status == "completed" else task.id)
            if status == "completed":
                o.bump_metric(agent.id, "tasks_completed")
            elif status == "failed":
                o.bump_metric(agent.id, "tasks_failed")
        return task

    def _propagate_blocks(self, tasks: list[Task], by_id: dict[str, Task]) -> None:
        changed = True
        while changed:
            changed = False
            for t in tasks:
                if t.status != "pending":
                    continue
                bad = [by_id[d] for d in t.depends_on if by_id[d].status in ("failed", "cancelled", "blocked")]
                if bad:
                    t.status = "blocked"
                    t.error = f"upstream task '{bad[0].title}' is {bad[0].status}"
                    self.office.save_task(t)
                    changed = True

    def _finish(self, workflow_id: str) -> None:
        o = self.office
        wf = o.store.get(Workflow, workflow_id)
        if wf is None:
            return
        tasks = self.tasks(workflow_id)
        if tasks and all(t.status == "completed" for t in tasks):
            status = "completed"
        elif any(t.status in ("failed", "blocked", "cancelled") for t in tasks) and not any(
            t.status in ("pending", "running", "waiting_approval") for t in tasks
        ):
            status = "stalled"
        else:
            status = "active"
        if wf.status != status:
            wf.status = status
            wf.updated_at = o.clock.iso()
            o.store.put(wf, wf.updated_at)
            mission = o.store.get(Mission, wf.mission_id)
            if mission is not None and status == "completed" and mission.status == "active":
                mission.status = "completed"
                mission.updated_at = wf.updated_at
                o.store.put(mission, mission.updated_at)
                o.log("system.office", "system", "mission.completed", mission.id, {"title": mission.title})
