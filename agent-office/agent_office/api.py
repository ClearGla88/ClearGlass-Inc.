"""HTTP API and operator console.

Every ``/api/v1`` route except ``/health`` requires an authenticated human
operator. Agents do not use this API; they act only through the gate, inside
the mission runner.

Authentication
--------------
``AGENT_OFFICE_OPERATOR_TOKENS`` lists operators as ``id:sha256hex`` pairs,
comma separated, where the hash is the SHA-256 of that operator's bearer
token. With ``AGENT_OFFICE_ENV=production`` and no operators configured, the
app refuses to start. In development with no operators configured, the
operator is taken from the ``X-Operator-Id`` header (default ``operator-1``);
that mode is for local use only and is labelled as such in every response.

Every POST and DELETE needs an ``Idempotency-Key`` header. A repeated key with
the same request replays the stored response; with a different request it is
refused. Mutations are serialised.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import re
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .daily_ops import compute_status, run_daily_ops
from .db import new_id, row_to_dict, rows_to_dicts, transaction
from .models import AgentStatus, GovernanceError, MissionStatus, NotFound, PermissionAction, iso, sha256_hex
from .office import Office

STATIC_DIR = Path(__file__).with_name("static")
OPERATOR_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")
MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}


class ConfigError(RuntimeError):
    pass


def parse_operator_tokens(raw: str) -> dict[str, str]:
    """``id:sha256hex,...`` -> {sha256hex: id}."""
    out: dict[str, str] = {}
    for item in filter(None, (p.strip() for p in raw.split(","))):
        op, _, digest = item.partition(":")
        if not OPERATOR_ID.match(op) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ConfigError("AGENT_OFFICE_OPERATOR_TOKENS entries must be operator_id:sha256hex")
        out[digest] = op
    return out


class DecisionBody(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)
    modified_payload: dict[str, Any] | None = None


class ReasonBody(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class GrantBody(BaseModel):
    tool_key: str
    action: PermissionAction
    constraints: dict[str, Any] = Field(default_factory=dict)
    expires_at: datetime | None = None


def create_app(
    *,
    db_path: str = ":memory:",
    office: Office | None = None,
    environ: Mapping[str, str] | None = None,
) -> FastAPI:
    env = environ if environ is not None else os.environ
    production = env.get("AGENT_OFFICE_ENV", "development").lower() == "production"
    tokens = parse_operator_tokens(env.get("AGENT_OFFICE_OPERATOR_TOKENS", ""))
    if production and not tokens:
        raise ConfigError("AGENT_OFFICE_ENV=production requires AGENT_OFFICE_OPERATOR_TOKENS; refusing to start")
    if production and db_path == ":memory:" and office is None:
        raise ConfigError("production needs a persistent database path")
    dev_header_mode = not tokens

    office = office or Office(db_path)
    app = FastAPI(title="ClearGlass Agent Office", version="0.1.0", docs_url="/api/docs", redoc_url=None)
    app.state.office = office
    mutation_lock = asyncio.Lock()

    def authenticate(request: Request) -> str | None:
        if dev_header_mode:
            op = request.headers.get("x-operator-id", "operator-1").strip().lower()
            return op if OPERATOR_ID.match(op) else None
        header = request.headers.get("authorization", "")
        if not header.lower().startswith("bearer "):
            return None
        digest = hashlib.sha256(header[7:].strip().encode()).hexdigest()
        for known, op in tokens.items():
            if hmac.compare_digest(known, digest):
                return op
        return None

    def error(status: int, code: str, detail: str, corr: str) -> JSONResponse:
        return JSONResponse({"code": code, "detail": detail}, status_code=status,
                            headers={"X-Correlation-Id": corr, **SECURITY_HEADERS})

    @app.middleware("http")
    async def governance_http(request: Request, call_next):
        corr = new_id()
        request.state.correlation_id = corr
        path = request.url.path
        if not path.startswith("/api/v1") or path == "/api/v1/health":
            response = await call_next(request)
            for k, v in {"X-Correlation-Id": corr, **SECURITY_HEADERS}.items():
                response.headers.setdefault(k, v)
            return response

        operator = authenticate(request)
        if operator is None:
            return error(401, "unauthenticated", "a valid operator credential is required", corr)
        request.state.operator = operator

        if request.method not in MUTATING:
            response = await call_next(request)
        else:
            key = request.headers.get("idempotency-key", "").strip()
            if not key or len(key) > 200:
                return error(400, "idempotency_key_required", "mutating requests need an Idempotency-Key", corr)
            body = await request.body()
            req_hash = sha256_hex(f"{request.method} {path}?{request.url.query}\n" + body.decode("utf-8", "replace"))
            async with mutation_lock:
                stored = office.conn.execute(
                    "SELECT * FROM idempotency_keys WHERE operator_id = ? AND key = ?", (operator, key)
                ).fetchone()
                if stored is not None:
                    if stored["request_hash"] != req_hash:
                        return error(422, "idempotency_key_reused", "this key was used for a different request", corr)
                    return Response(stored["response_body"], status_code=stored["status_code"],
                                    media_type="application/json",
                                    headers={"Idempotent-Replayed": "true", "X-Correlation-Id": corr,
                                             **SECURITY_HEADERS})
                response = await call_next(request)
                chunks = [chunk async for chunk in response.body_iterator]
                payload = b"".join(c if isinstance(c, bytes) else c.encode() for c in chunks)
                if response.status_code < 500:
                    office.conn.execute(
                        """INSERT INTO idempotency_keys (operator_id, key, request_hash, status_code,
                               response_body, created_at) VALUES (?,?,?,?,?,?)""",
                        (operator, key, req_hash, response.status_code, payload.decode("utf-8", "replace"),
                         iso(office.clock())),
                    )
                headers = {k: v for k, v in response.headers.items() if k.lower() != "content-length"}
                response = Response(payload, status_code=response.status_code, headers=headers,
                                    media_type=response.media_type)
        response.headers["X-Correlation-Id"] = corr
        response.headers["X-Operator-Id"] = operator
        response.headers["X-Auth-Mode"] = "dev-header" if dev_header_mode else "bearer"
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        return response

    @app.exception_handler(GovernanceError)
    async def governance_error(request: Request, exc: GovernanceError):
        return JSONResponse({"code": exc.code, "detail": exc.message}, status_code=exc.status_code)

    def op(request: Request) -> str:
        return request.state.operator

    # ------------------------------------------------------------- system
    @app.get("/api/v1/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/v1/session")
    async def session(request: Request):
        return {"operator": op(request), "auth_mode": "dev-header" if dev_header_mode else "bearer",
                "production": production, "policy": office.policy.describe()}

    # -------------------------------------------------------- headquarters
    @app.get("/api/v1/headquarters")
    async def headquarters():
        status = compute_status(office)
        agents = office.identity.list()
        floors = []
        for dept in office.departments():
            floor = next(d for d in status["departments"] if d["key"] == dept["key"])
            floors.append({
                **floor,
                "floor_index": dept["floor_index"],
                "description": dept["description"],
                "agents": [
                    {"id": a["id"], "name": a["name"], "role": a["role"], "status": a["status"]}
                    for a in agents if a["department_id"] == dept["id"]
                ],
            })
        return {
            "company": office.company(),
            "floors": floors,
            "missions": status["missions"],
            "pending_approvals": len(status["pending_approvals"]),
            "governance": status["governance"],
            "emergency": office.emergency.status(),
        }

    # ------------------------------------------------------------- agents
    @app.get("/api/v1/agents")
    async def list_agents():
        rows = office.identity.list()
        for a in rows:
            current = office.conn.execute(
                """SELECT t.title, t.status FROM tasks t WHERE t.assigned_agent_id = ?
                   AND t.status IN ('in_progress','waiting_for_approval','blocked')
                   ORDER BY t.created_at LIMIT 1""",
                (a["id"],),
            ).fetchone()
            a["current_task"] = dict(current) if current else None
            a["grants"] = len(office.permissions.grants_for(a["id"]))
        return rows

    @app.get("/api/v1/agents/{agent_id}")
    async def agent_detail(agent_id: str):
        agent = office.identity.get(agent_id)
        return {
            **agent,
            "grants": office.permissions.grants_for(agent_id, include_inactive=True),
            "effective_permissions": office.permissions.effective_permissions(agent_id, agent["department_key"]),
            "recent_audit": office.ledger.events(actor_id=agent_id, limit=25),
        }

    @app.get("/api/v1/agents/{agent_id}/effective-permissions")
    async def effective_permissions(agent_id: str):
        agent = office.identity.get(agent_id)
        return office.permissions.effective_permissions(agent_id, agent["department_key"])

    @app.post("/api/v1/agents/{agent_id}/pause")
    async def pause_agent(agent_id: str, body: ReasonBody, request: Request):
        return office.identity.set_status(agent_id, AgentStatus.PAUSED, actor_type="human",
                                          actor_id=op(request), reason=body.reason)

    @app.post("/api/v1/agents/{agent_id}/resume")
    async def resume_agent(agent_id: str, body: ReasonBody, request: Request):
        if office.emergency.is_halted():
            raise GovernanceError("emergency_stop", "resume the office before resuming agents")
        agent = office.identity.get(agent_id)
        if agent["status"] != AgentStatus.PAUSED:
            raise GovernanceError("not_paused", f"agent is {agent['status']}")
        return office.identity.set_status(agent_id, AgentStatus.IDLE, actor_type="human",
                                          actor_id=op(request), reason=body.reason)

    @app.post("/api/v1/agents/{agent_id}/retire")
    async def retire_agent(agent_id: str, body: ReasonBody, request: Request):
        return office.identity.retire(agent_id, actor_id=op(request), reason=body.reason)

    @app.post("/api/v1/agents/{agent_id}/grants", status_code=201)
    async def create_grant(agent_id: str, body: GrantBody, request: Request):
        return office.permissions.grant(agent_id, body.tool_key, body.action, granted_by=op(request),
                                        constraints=body.constraints, expires_at=body.expires_at)

    @app.delete("/api/v1/agents/{agent_id}/grants/{grant_id}")
    async def revoke_grant(agent_id: str, grant_id: str, request: Request):
        grant = office.permissions.get_grant(grant_id)
        if grant["agent_id"] != agent_id:
            raise NotFound("grant", grant_id)
        return office.permissions.revoke(grant_id, revoked_by=op(request))

    # ----------------------------------------------------------- missions
    @app.get("/api/v1/missions")
    async def list_missions():
        return office.missions.list()

    @app.get("/api/v1/missions/{mission_id}")
    async def mission_detail(mission_id: str):
        return office.missions.detail(mission_id)

    @app.post("/api/v1/missions/{mission_id}/run")
    async def run_mission(mission_id: str, request: Request):
        return office.runner.run(mission_id, triggered_by=op(request))

    @app.post("/api/v1/missions/{mission_id}/pause")
    async def pause_mission(mission_id: str, body: ReasonBody, request: Request):
        return office.missions.set_status(mission_id, MissionStatus.PAUSED, actor_type="human",
                                          actor_id=op(request), operator=True, reason=body.reason)

    @app.post("/api/v1/missions/{mission_id}/resume")
    async def resume_mission(mission_id: str, body: ReasonBody, request: Request):
        office.missions.set_status(mission_id, MissionStatus.ACTIVE, actor_type="human",
                                   actor_id=op(request), operator=True, reason=body.reason)
        return office.runner.run(mission_id, triggered_by=op(request))

    @app.post("/api/v1/missions/{mission_id}/cancel")
    async def cancel_mission(mission_id: str, body: ReasonBody, request: Request):
        return office.missions.set_status(mission_id, MissionStatus.CANCELLED, actor_type="human",
                                          actor_id=op(request), operator=True, reason=body.reason)

    # ---------------------------------------------------------- approvals
    def _approval_view(a: dict[str, Any]) -> dict[str, Any]:
        return {**a, "seconds_left": office.approvals.seconds_left(a, office.clock())}

    @app.get("/api/v1/approvals")
    async def list_approvals(status: str | None = None):
        return [_approval_view(a) for a in office.approvals.list(status)]

    @app.get("/api/v1/approvals/{approval_id}")
    async def approval_detail(approval_id: str):
        return _approval_view(office.approvals.get(approval_id))

    @app.get("/api/v1/approvals/{approval_id}/history")
    async def approval_history(approval_id: str):
        return office.approvals.history(approval_id)

    def _decide(approval_id: str, decision: str, body: DecisionBody, request: Request) -> dict[str, Any]:
        approval = office.approvals.decide(
            approval_id, decision=decision, decider_id=op(request), decider_type="human",
            reason=body.reason, modified_payload=body.modified_payload,
        )
        return _approval_view(approval)

    @app.post("/api/v1/approvals/{approval_id}/approve")
    async def approve(approval_id: str, body: DecisionBody, request: Request):
        return _decide(approval_id, "approve", body, request)

    @app.post("/api/v1/approvals/{approval_id}/reject")
    async def reject(approval_id: str, body: DecisionBody, request: Request):
        return _decide(approval_id, "reject", body, request)

    @app.post("/api/v1/approvals/{approval_id}/modify")
    async def modify(approval_id: str, body: DecisionBody, request: Request):
        return _decide(approval_id, "modify", body, request)

    # -------------------------------------------------- audit and policy
    @app.get("/api/v1/audit/events")
    async def audit_events(actor_id: str | None = None, correlation_id: str | None = None,
                           approval_id: str | None = None, action: str | None = None,
                           outcome: str | None = None, limit: int = 100):
        return office.ledger.events(actor_id=actor_id, correlation_id=correlation_id, approval_id=approval_id,
                                    action_prefix=action, outcome=outcome, limit=limit)

    @app.get("/api/v1/audit/verify")
    async def audit_verify():
        return office.ledger.verify().to_dict()

    @app.get("/api/v1/policies")
    async def policies():
        return office.policy.describe()

    @app.get("/api/v1/policies/shadow-report")
    async def shadow_report():
        rows = rows_to_dicts(office.conn.execute(
            """SELECT tool_key, action, enforced_effect, shadow_effect, shadow_policy_ids, COUNT(*) AS n,
                      MAX(created_at) AS last_seen
               FROM policy_shadow_divergences
               GROUP BY tool_key, action, enforced_effect, shadow_effect, shadow_policy_ids ORDER BY n DESC"""
        ).fetchall())
        evaluated = office.conn.execute(
            "SELECT COUNT(*) FROM audit_events WHERE policy_decision IS NOT NULL"
        ).fetchone()[0]
        return {"shadow_policies": office.policy.describe()["shadow"], "decisions_evaluated": evaluated,
                "divergences": sum(r["n"] for r in rows), "by_request": rows,
                "promotion": "Move the policy file from policies/shadow/ to policies/ in a reviewed pull request."}

    # --------------------------------------------------- vault and memory
    @app.get("/api/v1/vault/documents")
    async def vault_documents():
        return rows_to_dicts(office.conn.execute(
            """SELECT k.id, k.title, k.doc_type, k.source, k.checksum, k.approved, k.created_at,
                      substr(k.content, 1, 400) AS preview, a.name AS created_by
               FROM knowledge_documents k LEFT JOIN agents a ON a.id = k.created_by_agent_id
               ORDER BY k.approved DESC, k.created_at DESC"""
        ).fetchall())

    @app.get("/api/v1/memory")
    async def memory_records():
        return rows_to_dicts(office.conn.execute(
            """SELECT m.*, a.name AS proposed_by FROM memory_records m
               LEFT JOIN agents a ON a.id = m.created_by_agent_id ORDER BY m.approved, m.created_at DESC"""
        ).fetchall())

    @app.post("/api/v1/memory/{record_id}/approve")
    async def approve_memory(record_id: str, body: ReasonBody, request: Request):
        if len(body.reason.strip()) < 8:
            raise GovernanceError("reason_required", "approving memory needs a reason", status_code=422)
        record = row_to_dict(office.conn.execute("SELECT * FROM memory_records WHERE id = ?", (record_id,)).fetchone())
        if record is None:
            raise NotFound("memory record", record_id)
        if record["approved"]:
            raise GovernanceError("already_approved", "memory record is already approved")
        with transaction(office.conn):
            office.conn.execute(
                """UPDATE memory_records SET approved = 1, scope = 'company_approved', approved_by = ?,
                       approved_at = ? WHERE id = ?""",
                (op(request), iso(office.clock()), record_id),
            )
            office.ledger.append(
                actor_type="human", actor_id=op(request), action="memory.approve", resource_type="memory_record",
                resource_id=record_id, outcome="success", correlation_id=request.state.correlation_id,
                payload={"content": record["content"], "source": record["source"]},
                metadata={"reason": body.reason.strip()},
            )
        return row_to_dict(office.conn.execute("SELECT * FROM memory_records WHERE id = ?", (record_id,)).fetchone())

    # ------------------------------------------------------ collaboration
    @app.get("/api/v1/collaboration")
    async def collaboration(limit: int = 100):
        return rows_to_dicts(office.conn.execute(
            """SELECT msg.*, s.name AS sender, r.name AS recipient, m.code AS mission_code
               FROM messages msg LEFT JOIN agents s ON s.id = msg.sender_agent_id
               LEFT JOIN agents r ON r.id = msg.recipient_agent_id LEFT JOIN missions m ON m.id = msg.mission_id
               ORDER BY msg.created_at DESC LIMIT ?""",
            (max(1, min(limit, 500)),),
        ).fetchall())

    # ------------------------------------------------- briefings, reports
    @app.post("/api/v1/briefings/daily")
    async def daily(request: Request):
        result = run_daily_ops(office, triggered_by=op(request))
        return {k: result[k] for k in ("briefing", "red_team", "ledger", "reports_written")}

    def _latest(report_type: str) -> dict[str, Any]:
        row = row_to_dict(office.conn.execute(
            "SELECT * FROM reports WHERE report_type = ? ORDER BY created_at DESC LIMIT 1", (report_type,)
        ).fetchone())
        if row is None:
            raise NotFound("report", report_type)
        return row

    @app.get("/api/v1/briefings/latest")
    async def latest_briefing():
        return _latest("executive_briefing")

    @app.get("/api/v1/reports/latest")
    async def latest_report(type: str = "operations_report"):
        return _latest(type)

    # ---------------------------------------------------------- emergency
    @app.get("/api/v1/emergency/status")
    async def emergency_status():
        return office.emergency.status()

    @app.post("/api/v1/emergency/stop")
    async def emergency_stop(body: ReasonBody, request: Request):
        return office.emergency.stop(operator_id=op(request), reason=body.reason)

    @app.post("/api/v1/emergency/resume")
    async def emergency_resume(body: ReasonBody, request: Request):
        return office.emergency.resume(operator_id=op(request), reason=body.reason)

    # ------------------------------------------------------------ console
    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

        @app.get("/", include_in_schema=False)
        async def console():
            return FileResponse(STATIC_DIR / "index.html")

    return app

