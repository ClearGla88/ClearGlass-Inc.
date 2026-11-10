# Workflow engine design

Code: `packages/agent_core/workflow.py`. Tests: `tests/test_workflow.py`, `tests/test_daily_loop.py`.

## Model

A **mission** owns one **workflow**: a directed acyclic graph of **tasks**. Each task names one assignee and one
action (`type` + `params`) from the policy catalog.

```json
{"key": "review", "title": "Review the patch", "assignee": "eng.qa", "depends_on": ["patch", "testplan"],
 "action": {"type": "code.review", "params": {"patch": {"$from": "patch", "path": "artifact"}}}}
```

## Build (at mission creation)

1. Keys present and unique; every `depends_on` names a task in the same mission; every assignee exists.
2. Cycle check with Kahn's algorithm. A cycle rejects the mission.
3. **Waves:** a task's wave is the longest dependency path to it. Tasks in the same wave are independent.
4. Tasks are persisted `pending`; the mission is `active`; the creation is audited.

```
Engineering demo mission
wave 1: design (Architect)
wave 2: patch (Backend) | testplan (QA)      <- parallel
wave 3: review (QA)                          <- waits for both
wave 4: rollout (Architect)
```

## Run loop

```
repeat until no task becomes ready (max 50 rounds), the office is halted, or the mission stops being active:
  block every pending task with a failed, cancelled, or blocked upstream (transitively)
  ready = pending tasks whose dependencies are all completed
  for each ready task, in (wave, id) order:
     resolve {"$from", "path"} inputs from upstream outputs     # before the gate, so the digest covers real values
     task -> running; agent -> working
     result = GovernedExecutor.perform(request)                # the nine steps; key task:<id>:attempt:<n>
     completed         -> store output + trace; post handoffs to downstream assignees; write task memory
     waiting_approval  -> task holds; escalation to the operator and the agent's manager
     denied            -> task failed; dependents blocked; escalation + policy decision record
     failed            -> retry up to max_attempts (default 2), then failed + escalation
when every task is completed, the workflow and mission complete
```

Input references may point at any upstream ancestor, never a sibling, so a task cannot read an output that has not
been produced yet.

## Mission lifecycle and modes

The operator can pause, resume, or cancel a mission with a reason of 12 or more characters (`POST
/missions/{id}/{pause|resume|cancel}`). An agent cannot. Pause is allowed from `active`, resume from `paused`,
cancel from either. The run loop stops at a mission that is not active, and the gate refuses any request that names
one (step 1). An approval for a paused mission cannot be decided either: the decision is refused, the approval stays
pending, and it can be decided after the mission resumes. Cancel also cancels the mission's pending, blocked, and
held tasks and its pending or approved approvals.

A mission created with `mode: simulation` runs the same graph, but the gate refuses any external action and any
action that targets production (step 4).

## Approval hand-back

When the operator approves, the approved parameters (edited ones, after "modify") replace the task's resolved action,
the task returns to `pending` with its `approval_id`, and the workflow runs again. The executor then checks that the
payload digest equals the approval's `approved_digest`, and consumes the approval before the tool runs. A rejection
cancels the task and blocks everything downstream.

## Parallelism

Waves define what may run concurrently. The MVP worker runs a wave's tasks one after another in a fixed order, which
keeps the audit chain reproducible in tests and demos. Every task request already carries the idempotency key
`task:<id>:attempt:<n>`: a completed attempt delivered twice replays its stored result instead of acting again. The
queue-based worker (roadmap week 2) dispatches each ready task as a job with that key; the graph semantics and the
gate do not change.

## Failure modes

| Failure | Behavior |
|---|---|
| Policy denial | Task failed, not retried (retrying a denial cannot change the answer); downstream blocked |
| Tool error | Retried up to `max_attempts`; then failed with the error text |
| Unregistered internal action (`code.commit_branch`, `data.update_internal`) | Fails with "no handler" instead of pretending to work |
| Sandbox test suite fails or times out | Task failed (`tests_passed` verification); a production deploy citing it is denied |
| Mission paused or cancelled | Run loop stops; the gate refuses the mission's requests until it is active again |
| Duplicate delivery of a completed attempt | Stored result returned (`action.replayed`); nothing runs twice |
| Missing upstream output | Task failed with "input resolution failed" |
| Verification failure (no citations, no rollback, receipt not bound to the approval) | Task failed; failure sealed in the ledger |
| Emergency stop | Run loop exits; held tasks become blocked; nothing new starts |

## The Daily Operations Loop

`apps/worker/daily_loop.py` drives the office once per day:

| Step | What happens | Who |
|---|---|---|
| 1 | Load objectives and active missions (demo missions created once, saved as workflow templates in the vault) | system |
| 2 | Collect department status | system |
| 3 | Executive briefing (`briefing.compile`, through the gate) | Chief of Staff |
| 4 | Blockers, risks, opportunities: part of the briefing | Chief of Staff |
| 5 | Priority assignments to each ready task's agent (`message.internal`) | Chief of Staff |
| 6 | Missions run, highest priority first | all assignees |
| 7 | Each pending approval gets a risk note | Risk & Compliance |
| 8 | End-of-day report (`report.compile`) and stand-down summary | Chief of Staff |

The demo run touches 8 agents in 4 departments, completes 11 tasks, and holds 1 (`content.publish`) for approval.
