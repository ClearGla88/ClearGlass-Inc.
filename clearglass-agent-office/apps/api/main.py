"""ClearGlass Agent Office API (FastAPI).

Run: ``python office.py serve`` (or ``uvicorn apps.api.main:app`` with
``packages/`` and the project root on PYTHONPATH). OpenAPI docs at /docs.

Every mutating route depends on ``require_operator``; every read on
``require_viewer``. ``tests/test_api.py::test_every_mutating_route_requires_operator``
fails if a new POST/PATCH route is added without the operator gate.
"""

from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "packages", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fastapi import Depends, FastAPI, HTTPException, Query, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from pydantic import BaseModel, ConfigDict, Field  # noqa: E402

from agent_core.approvals import ApprovalError, Principal  # noqa: E402
from agent_core.models import Decision, Report, Simulation  # noqa: E402
from agent_core.office import Office, OfficeError  # noqa: E402
from agent_core.providers import provider_from_env  # noqa: E402
from agent_core.reports import compute_kpis  # noqa: E402
from apps.api.security import RateLimiter, Settings, require_operator, require_viewer  # noqa: E402
from apps.api.snapshot import build_snapshot  # noqa: E402
from memory_vault.vault import MemoryError_  # noqa: E402
from policy_engine.engine import ActionRequest  # noqa: E402
from simulation.sandbox import SCENARIOS, SimulationError  # noqa: E402

log = logging.getLogger("office.api")

Viewer = Depends(require_viewer)
Operator = Depends(require_operator)


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReasonBody(Body):
    reason: str = Field(min_length=1, max_length=2000)


class DecisionBody(Body):
    decision: Literal["approve", "reject", "modify"]
    reason: str = Field(min_length=1, max_length=2000)
    modifications: dict[str, Any] | None = None


class AgentSpec(Body):
    id: str = Field(pattern=r"^[a-z]+\.[a-z0-9-]{2,40}$")
    callsign: str = Field(pattern=r"^CG-[A-Z]{2}-\d{2,3}$")
    name: str = Field(min_length=2, max_length=80)
    department: str
    reports_to: str
    objective: str = Field(min_length=5, max_length=500)
    success_criteria: list[str] = Field(default_factory=list, max_length=10)
    skills: list[str] = Field(default_factory=list, max_length=20)
    permissions: dict[str, str] = Field(default_factory=dict)
    tools: list[str] = Field(default_factory=list, max_length=20)
    memory_scopes: list[str] = Field(default_factory=lambda: ["company"], max_length=10)
    clearance: Literal["public", "internal", "confidential", "restricted"] = "internal"
    room: str | None = None


class AgentPatch(Body):
    name: str | None = Field(default=None, min_length=2, max_length=80)
    objective: str | None = Field(default=None, min_length=5, max_length=500)
    success_criteria: list[str] | None = None
    skills: list[str] | None = None
    room: str | None = None
    memory_scopes: list[str] | None = None
    clearance: Literal["public", "internal", "confidential", "restricted"] | None = None
    reports_to: str | None = None
    tools: list[str] | None = None
    permissions: dict[str, str] | None = None
    boundaries: list[str] | None = None


class CloneBody(Body):
    new_id: str = Field(pattern=r"^[a-z]+\.[a-z0-9-]{2,40}$")
    callsign: str = Field(pattern=r"^CG-[A-Z]{2}-\d{2,3}$")


class LifecycleBody(Body):
    reason: str = Field(default="", max_length=500)


class TaskSpec(Body):
    key: str = Field(pattern=r"^[a-z0-9-]{1,40}$")
    title: str = Field(min_length=1, max_length=200)
    assignee: str
    action: dict[str, Any]
    depends_on: list[str] = Field(default_factory=list)
    max_attempts: int = Field(default=2, ge=1, le=5)


class MissionSpec(Body):
    key: str = Field(default="", max_length=60)
    title: str = Field(min_length=3, max_length=200)
    objective: str = Field(min_length=5, max_length=1000)
    department: str
    owner: str
    priority: int = Field(default=3, ge=1, le=5)
    deadline: str | None = None
    deadline_days: int | None = Field(default=None, ge=0, le=365)
    deliverables: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    approval_rules: list[str] = Field(default_factory=list)
    goal_ids: list[str] = Field(default_factory=list)
    tasks: list[TaskSpec] = Field(min_length=1, max_length=50)


class MemoryBody(Body):
    scope: str = Field(default="company", max_length=80)
    title: str = Field(min_length=2, max_length=200)
    content: str = Field(min_length=1, max_length=20000)
    source: str = Field(min_length=2, max_length=300)
    classification: Literal["public", "internal", "confidential", "restricted"] = "internal"
    tags: list[str] = Field(default_factory=list, max_length=10)


class MemoryDecision(Body):
    approve: bool
    reason: str = Field(min_length=1, max_length=2000)


class SimulationBody(Body):
    agent_id: str = "sim.scenario-designer"
    scenario_type: str
    title: str = Field(default="", max_length=200)
    assumptions: dict[str, Any]
    options: list[dict[str, Any]] = Field(min_length=1, max_length=6)
    seed: int = Field(default=7, ge=0, le=2**31)
    runs: int = Field(default=2000, ge=100, le=20000)


class EvaluateBody(Body):
    agent_id: str
    action_type: str
    params: dict[str, Any] = Field(default_factory=dict)
    sandbox: bool = False


def _office(request: Request) -> Office:
    return request.app.state.office


def create_app(office: Office | None = None, settings: Settings | None = None) -> FastAPI:
    holder: dict[str, Any] = {}

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # noqa: ANN202
        yield
        if holder.get("owned"):
            app.state.office.store.close()

    if office is None:
        office = Office(
            ROOT, db_path=os.environ.get("OFFICE_DB", str(ROOT / "var" / "office.db")), provider=provider_from_env()
        )
        holder["owned"] = True
    settings = settings or Settings.from_env(office.company().operator["id"])
    settings.validate()

    app = FastAPI(
        title="ClearGlass Agent Office API",
        version="0.1.0",
        lifespan=lifespan,
        description="Governed operations API. Every agent action passes the nine-step policy pipeline.",
    )
    app.state.office = office
    app.state.settings = settings
    app.state.limiter = RateLimiter(settings.mutations_per_minute)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST", "PATCH"],
            allow_headers=["Authorization", "Content-Type"],
        )

    @app.middleware("http")
    async def headers(request: Request, call_next):  # noqa: ANN001, ANN202
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        if settings.open_mode:
            response.headers["X-Office-Auth"] = "development-open"
        return response

    @app.exception_handler(OfficeError)
    async def office_error(_: Request, exc: OfficeError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(ApprovalError)
    async def approval_error(_: Request, exc: ApprovalError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(MemoryError_)
    async def memory_error(_: Request, exc: MemoryError_) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(SimulationError)
    async def sim_error(_: Request, exc: SimulationError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error")
        return JSONResponse({"detail": "internal error"}, status_code=500)

    # -- health ------------------------------------------------------------------
    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready", tags=["health"])
    def ready(request: Request) -> JSONResponse:
        result = _office(request).readiness()
        return JSONResponse(result, status_code=200 if result["ready"] else 503)

    @app.get("/session", tags=["health"])
    def session(p: Principal = Viewer) -> dict[str, Any]:
        return {"principal": p.to_dict(), "mode": "development-open" if settings.open_mode else settings.env}

    # -- headquarters ---------------------------------------------------------------
    @app.get("/snapshot", tags=["headquarters"])
    def snapshot(request: Request, _: Principal = Viewer) -> dict[str, Any]:
        return build_snapshot(_office(request))

    @app.get("/kpis", tags=["headquarters"])
    def kpis(request: Request, _: Principal = Viewer) -> dict[str, Any]:
        return compute_kpis(_office(request))

    @app.get("/departments", tags=["headquarters"])
    def departments(request: Request, _: Principal = Viewer) -> list[dict[str, Any]]:
        return [d.to_dict() for d in _office(request).departments()]

    # -- agents -------------------------------------------------------------------------
    @app.get("/agents", tags=["agents"])
    def agents(request: Request, _: Principal = Viewer) -> list[dict[str, Any]]:
        return [a.to_dict() for a in _office(request).agents()]

    @app.get("/agents/{agent_id}", tags=["agents"])
    def agent(agent_id: str, request: Request, _: Principal = Viewer) -> dict[str, Any]:
        o = _office(request)
        a = o.agent(agent_id)
        if a is None:
            raise HTTPException(404, "unknown agent")
        return {"agent": a.to_dict(), "audit": o.audit.events(subject=agent_id, limit=50)}

    @app.post("/agents", tags=["agents"], status_code=201)
    def hire(body: AgentSpec, request: Request, p: Principal = Operator) -> dict[str, Any]:
        spec = body.model_dump(exclude_none=True)
        return _office(request).hire_agent(spec, p).to_dict()

    @app.post("/agents/{agent_id}/clone", tags=["agents"], status_code=201)
    def clone(agent_id: str, body: CloneBody, request: Request, p: Principal = Operator) -> dict[str, Any]:
        return _office(request).clone_agent(agent_id, body.new_id, body.callsign, p).to_dict()

    @app.patch("/agents/{agent_id}", tags=["agents"])
    def edit(agent_id: str, body: AgentPatch, request: Request, p: Principal = Operator) -> dict[str, Any]:
        return _office(request).update_agent(agent_id, body.model_dump(exclude_none=True), p).to_dict()

    @app.post("/agents/{agent_id}/{action}", tags=["agents"])
    def lifecycle(
        agent_id: str,
        action: Literal["pause", "resume", "retire"],
        body: LifecycleBody,
        request: Request,
        p: Principal = Operator,
    ) -> dict[str, Any]:
        return _office(request).set_agent_lifecycle(agent_id, action, p, body.reason).to_dict()

    # -- missions -----------------------------------------------------------------------
    @app.get("/missions", tags=["missions"])
    def missions(request: Request, _: Principal = Viewer) -> list[dict[str, Any]]:
        return [m.to_dict() for m in _office(request).missions()]

    @app.post("/missions", tags=["missions"], status_code=201)
    def create_mission(body: MissionSpec, request: Request, p: Principal = Operator) -> dict[str, Any]:
        return _office(request).create_mission(body.model_dump(), created_by=p.id).to_dict()

    @app.get("/missions/{mission_id}", tags=["missions"])
    def mission(mission_id: str, request: Request, _: Principal = Viewer) -> dict[str, Any]:
        try:
            return _office(request).mission_detail(mission_id)
        except OfficeError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/missions/{mission_id}/run", tags=["missions"])
    def run_mission(mission_id: str, request: Request, _: Principal = Operator) -> dict[str, Any]:
        return _office(request).run_mission(mission_id)

    @app.post("/daily-loop/run", tags=["missions"])
    def daily_loop(request: Request, _: Principal = Operator) -> dict[str, Any]:
        from apps.worker.daily_loop import run_daily_loop

        return run_daily_loop(_office(request), ROOT / "demo" / "missions.json")

    # -- collaboration ------------------------------------------------------------------
    @app.get("/messages", tags=["collaboration"])
    def messages(
        request: Request,
        thread_id: str | None = None,
        kind: str | None = None,
        limit: int = Query(200, ge=1, le=1000),
        _: Principal = Viewer,
    ) -> list[dict[str, Any]]:
        return [m.to_dict() for m in _office(request).messages(thread_id=thread_id, kind=kind, limit=limit)]

    @app.get("/decisions", tags=["collaboration"])
    def decisions(request: Request, _: Principal = Viewer) -> list[dict[str, Any]]:
        return [d.to_dict() for d in _office(request).store.list(Decision, newest_first=True)]

    # -- approvals ------------------------------------------------------------------------
    @app.get("/approvals", tags=["approvals"])
    def approvals(
        request: Request, status_: str | None = Query(None, alias="status"), _: Principal = Viewer
    ) -> list[dict[str, Any]]:
        return [a.to_dict() for a in _office(request).desk.list(status_)]

    @app.get("/approvals/{approval_id}", tags=["approvals"])
    def approval(approval_id: str, request: Request, _: Principal = Viewer) -> dict[str, Any]:
        a = _office(request).desk.get(approval_id)
        if a is None:
            raise HTTPException(404, "unknown approval")
        return a.to_dict()

    @app.post("/approvals/{approval_id}/decision", tags=["approvals"])
    def decide(approval_id: str, body: DecisionBody, request: Request, p: Principal = Operator) -> dict[str, Any]:
        return (
            _office(request).decide_approval(approval_id, p, body.decision, body.reason, body.modifications).to_dict()
        )

    # -- knowledge vault ----------------------------------------------------------------------
    @app.get("/memory", tags=["knowledge"])
    def memory(request: Request, layer: str | None = None, _: Principal = Viewer) -> list[dict[str, Any]]:
        return [r.to_dict() for r in _office(request).memory.all(layer)]

    @app.post("/memory", tags=["knowledge"], status_code=201)
    def add_memory(body: MemoryBody, request: Request, p: Principal = Operator) -> dict[str, Any]:
        b = body.model_dump()
        return (
            _office(request)
            .memory.add_approved(
                p.id, b["scope"], b["title"], b["content"], b["source"], b["classification"], b["tags"]
            )
            .to_dict()
        )

    @app.post("/memory/{record_id}/decision", tags=["knowledge"])
    def decide_memory(
        record_id: str, body: MemoryDecision, request: Request, p: Principal = Operator
    ) -> dict[str, Any]:
        return _office(request).memory.decide(record_id, p.id, body.approve, body.reason).to_dict()

    # -- simulation chamber ----------------------------------------------------------------------
    @app.get("/simulations/scenarios", tags=["simulation"])
    def scenarios(_: Principal = Viewer) -> dict[str, Any]:
        return {
            k: {
                "description": s.description,
                "objective": s.objective,
                "direction": s.direction,
                "metrics": list(s.metrics),
                "example": s.example,
            }
            for k, s in SCENARIOS.items()
        }

    @app.get("/simulations", tags=["simulation"])
    def simulations(request: Request, _: Principal = Viewer) -> list[dict[str, Any]]:
        return [s.to_dict() for s in _office(request).simulations()]

    @app.get("/simulations/{sim_id}", tags=["simulation"])
    def simulation(sim_id: str, request: Request, _: Principal = Viewer) -> dict[str, Any]:
        s = _office(request).store.get(Simulation, sim_id)
        if s is None:
            raise HTTPException(404, "unknown simulation")
        return s.to_dict()

    @app.post("/simulations", tags=["simulation"], status_code=201)
    def run_simulation(body: SimulationBody, request: Request, _: Principal = Operator) -> dict[str, Any]:
        spec = body.model_dump()
        result = _office(request).run_simulation(spec.pop("agent_id"), spec)
        if result.status != "completed":
            raise HTTPException(400, result.error or result.status)
        return {"status": result.status, "trace": result.trace(), "result": result.output["artifact"]}  # type: ignore[index]

    # -- briefing room ---------------------------------------------------------------------------
    @app.get("/reports", tags=["reports"])
    def reports(request: Request, kind: str | None = None, _: Principal = Viewer) -> list[dict[str, Any]]:
        items = _office(request).store.list(Report, lambda r: kind is None or r.kind == kind, newest_first=True)
        return [
            {"id": r.id, "kind": r.kind, "title": r.title, "period": r.period, "generated_at": r.generated_at}
            for r in items
        ]

    @app.get("/reports/latest/{kind}", tags=["reports"])
    def latest_report(kind: str, request: Request, _: Principal = Viewer) -> dict[str, Any]:
        r = _office(request).latest_report(kind)
        if r is None:
            raise HTTPException(404, "no report of that kind yet")
        return r.to_dict()

    @app.get("/reports/{report_id}", tags=["reports"])
    def report(report_id: str, request: Request, _: Principal = Viewer) -> dict[str, Any]:
        r = _office(request).store.get(Report, report_id)
        if r is None:
            raise HTTPException(404, "unknown report")
        return r.to_dict()

    # -- audit and policy -----------------------------------------------------------------------
    @app.get("/audit", tags=["audit"])
    def audit(
        request: Request,
        limit: int = Query(100, ge=1, le=1000),
        offset: int = Query(0, ge=0),
        subject: str | None = None,
        event_type: str | None = None,
        _: Principal = Viewer,
    ) -> list[dict[str, Any]]:
        return _office(request).audit.events(limit=limit, offset=offset, subject=subject, event_type=event_type)

    @app.get("/audit/verify", tags=["audit"])
    def audit_verify(request: Request, _: Principal = Viewer) -> dict[str, Any]:
        return _office(request).audit.verify().to_dict()

    @app.get("/policy", tags=["policy"])
    def policy(request: Request, _: Principal = Viewer) -> dict[str, Any]:
        return _office(request).policy.raw

    @app.post("/policy/evaluate", tags=["policy"])
    def evaluate(body: EvaluateBody, request: Request, _: Principal = Operator) -> dict[str, Any]:
        """Dry run: steps 1-6 only. Nothing executes and nothing is written."""
        gate = _office(request).evaluate(
            ActionRequest(
                agent_id=body.agent_id, action_type=body.action_type, params=body.params, sandbox=body.sandbox
            )
        )
        return gate.to_dict()

    @app.get("/tools", tags=["policy"])
    def tools(request: Request, _: Principal = Viewer) -> list[dict[str, Any]]:
        return [t.to_dict() for t in _office(request).tool_list()]

    @app.get("/vault", tags=["policy"])
    def vault(request: Request, _: Principal = Viewer) -> list[dict[str, Any]]:
        o = _office(request)
        return o.vault.describe(o.tool_list())

    # -- emergency stop ---------------------------------------------------------------------------
    @app.get("/emergency-stop", tags=["emergency"])
    def emergency_state(request: Request, _: Principal = Viewer) -> dict[str, Any]:
        return _office(request).halt_state()

    @app.post("/emergency-stop", tags=["emergency"])
    def emergency_stop(body: ReasonBody, request: Request, p: Principal = Operator) -> dict[str, Any]:
        return _office(request).emergency_stop(p, body.reason)

    @app.post("/emergency-stop/release", tags=["emergency"])
    def emergency_release(body: ReasonBody, request: Request, p: Principal = Operator) -> dict[str, Any]:
        return _office(request).release_emergency_stop(p, body.reason)

    return app


def __getattr__(name: str) -> Any:
    # ``uvicorn apps.api.main:app`` builds the app on first access, not at import,
    # so importing this module in tests never opens the default database.
    if name == "app":
        globals()["app"] = create_app()
        return globals()["app"]
    raise AttributeError(name)
