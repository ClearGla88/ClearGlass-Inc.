"""Authenticated control API (FastAPI).

Two kinds of caller. Sensors sign each request with their own HMAC key and can
only submit events. People use bearer tokens mapped to one role each:
analyst (read, mark false positive, request recovery), approver (read, decide
proposals), admin (read, emergency stop, circuit reset, sensor trust, audit
verification). Tokens are never stored; the configuration holds their SHA-256.

This module imports no adapter and holds no containment credential.
"""

# No `from __future__ import annotations` here: FastAPI must resolve the
# dependency annotations defined inside create_app at runtime.

import hashlib
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Path, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from . import __version__
from .config import Bundle, Principal
from .engine import Engine
from .errors import DomainError
from .operations import Operations
from .store import Store
from .util import Clock

ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$"
IdPath = Annotated[str, Path(pattern=ID_PATTERN)]


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DecisionIn(Body):
    decision: Literal["approved", "rejected"]
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_version: str = Field(pattern=ID_PATTERN)
    reason: str = Field(min_length=1, max_length=1000)


class FalsePositiveIn(Body):
    rationale: str = Field(min_length=1, max_length=1000)


class RecoveryIn(Body):
    criteria: dict[str, str] = Field(max_length=20)
    reason: str = Field(min_length=1, max_length=1000)


class ToggleIn(Body):
    engaged: bool
    reason: str = Field(min_length=1, max_length=1000)


class ReasonIn(Body):
    reason: str = Field(min_length=1, max_length=1000)


class TrustIn(Body):
    trusted: bool
    reason: str = Field(min_length=1, max_length=1000)


def create_app(bundle: Bundle, store: Store, clock: Clock | None = None) -> FastAPI:
    clock = clock or Clock()
    engine = Engine(store, bundle, clock)
    ops = Operations(engine)
    prod = bundle.config.environment == "production"
    app = FastAPI(
        title="ClearGlass Active Defense control API",
        version=__version__,
        docs_url=None if prod else "/docs",
        redoc_url=None,
        openapi_url=None if prod else "/openapi.json",
    )
    app.state.engine = engine
    app.state.ops = ops

    @app.exception_handler(DomainError)
    async def _domain(_request: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={"status": "refused", "reason": exc.reason})

    def principal(request: Request) -> Principal:
        header = request.headers.get("authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise HTTPException(401, "bearer token required", headers={"WWW-Authenticate": "Bearer"})
        found = bundle.principals_by_token_hash.get(hashlib.sha256(token.encode()).hexdigest())
        if found is None:
            raise HTTPException(401, "unknown token", headers={"WWW-Authenticate": "Bearer"})
        return found

    Who = Annotated[Principal, Depends(principal)]

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/ready")
    def ready() -> JSONResponse:
        try:
            store.connect().execute("SELECT 1").fetchone()
        except Exception:  # noqa: BLE001 - readiness reports, it does not raise
            return JSONResponse(status_code=503, content={"status": "unavailable", "database": False})
        return JSONResponse({"status": "ready", "database": True, "mode": bundle.config.mode,
                             "environment": bundle.config.environment, "policy_version": bundle.config.policy_version})

    @app.post("/v1/events")
    async def ingest(request: Request) -> JSONResponse:
        limit = bundle.config.ingest.max_body_bytes
        declared = request.headers.get("content-length")
        if declared is not None and (not declared.isdigit() or int(declared) > limit):
            return JSONResponse(status_code=413, content={"status": "rejected", "reason": "body too large"})
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > limit:
                return JSONResponse(status_code=413, content={"status": "rejected", "reason": "body too large"})
            chunks.append(chunk)
        try:
            result = await run_in_threadpool(engine.ingest, dict(request.headers), b"".join(chunks))
        except DomainError as exc:
            return JSONResponse(status_code=exc.status, content={"status": "rejected", "reason": exc.reason})
        return JSONResponse(result)

    @app.get("/v1/cases")
    def cases(who: Who, state: str | None = None) -> list[dict]:
        return ops.list_cases(who, state=state)

    @app.get("/v1/cases/{case_id}")
    def case(who: Who, case_id: IdPath) -> dict:
        return ops.case(who, case_id)

    @app.get("/v1/cases/{case_id}/evidence")
    def evidence(who: Who, case_id: IdPath) -> dict:
        return ops.evidence(who, case_id)

    @app.post("/v1/cases/{case_id}/false-positive")
    def false_positive(who: Who, case_id: IdPath, body: FalsePositiveIn) -> dict:
        return ops.false_positive(who, case_id, rationale=body.rationale)

    @app.post("/v1/cases/{case_id}/recovery-request")
    def recovery(who: Who, case_id: IdPath, body: RecoveryIn) -> dict:
        return ops.request_recovery(who, case_id, criteria=body.criteria, reason=body.reason)

    @app.get("/v1/proposals")
    def proposals(who: Who, status: str | None = None) -> list[dict]:
        return ops.list_proposals(who, status=status)

    @app.get("/v1/proposals/{proposal_id}")
    def proposal(who: Who, proposal_id: IdPath) -> dict:
        return ops.proposal(who, proposal_id)

    @app.post("/v1/proposals/{proposal_id}/decision")
    def decide(who: Who, proposal_id: IdPath, body: DecisionIn) -> dict:
        return ops.decide(who, proposal_id, decision=body.decision, plan_hash=body.plan_hash,
                          policy_version=body.policy_version, reason=body.reason)

    @app.post("/v1/controls/emergency-stop")
    def estop(who: Who, body: ToggleIn) -> dict:
        return ops.set_emergency_stop(who, engaged=body.engaged, reason=body.reason)

    @app.post("/v1/controls/circuit-breaker/reset")
    def breaker(who: Who, body: ReasonIn) -> dict:
        return ops.reset_circuit(who, reason=body.reason)

    @app.post("/v1/sensors/{sensor_id}/trust")
    def trust(who: Who, sensor_id: IdPath, body: TrustIn) -> dict:
        return ops.set_sensor_trust(who, sensor_id, trusted=body.trusted, reason=body.reason)

    @app.get("/v1/audit/verify")
    def audit(who: Who) -> dict:
        return ops.verify_audit(who)

    @app.get("/v1/metrics")
    def metrics(who: Who) -> dict:
        return ops.metrics(who)

    return app
