import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from apps.api.main import create_app
from apps.api.security import Settings, require_operator
from tests.conftest import make_office

OP = "o" * 40
VW = "v" * 40
H_OP = {"Authorization": f"Bearer {OP}"}
H_VW = {"Authorization": f"Bearer {VW}"}


@pytest.fixture
def client():
    app = create_app(make_office(), Settings(env="test", operator_token=OP, viewer_token=VW))
    return TestClient(app)


def test_production_fails_closed_without_operator_token():
    with pytest.raises(RuntimeError, match="refusing to start"):
        create_app(make_office(), Settings(env="production"))
    with pytest.raises(RuntimeError, match="at least 32"):
        create_app(make_office(), Settings(env="production", operator_token="short"))


def test_every_mutating_route_requires_operator(client):
    for route in client.app.routes:
        if isinstance(route, APIRoute) and route.methods & {"POST", "PATCH", "PUT", "DELETE"}:
            deps = {d.call for d in route.dependant.dependencies}
            assert require_operator in deps, f"{route.path} is not operator-gated"


def test_auth_matrix(client):
    assert client.get("/health").status_code == 200
    assert client.get("/snapshot").status_code == 401
    assert client.get("/snapshot", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/snapshot", headers=H_VW).status_code == 200
    assert client.post("/daily-loop/run", headers=H_VW).status_code == 403
    assert client.post("/emergency-stop", headers=H_VW, json={"reason": "viewer tries to stop it"}).status_code == 403


def test_unknown_fields_are_rejected(client):
    r = client.post("/emergency-stop", headers=H_OP, json={"reason": "valid reason here", "force": True})
    assert r.status_code == 422


def test_full_operator_flow(client):
    loop = client.post("/daily-loop/run", headers=H_OP).json()
    aid = loop["approvals_pending"][0]
    approval = client.get(f"/approvals/{aid}", headers=H_VW).json()
    assert approval["status"] == "pending" and approval["risk_tier"] == "high"
    assert (
        client.post(
            f"/approvals/{aid}/decision", headers=H_OP, json={"decision": "approve", "reason": "short"}
        ).status_code
        == 409
    )
    done = client.post(
        f"/approvals/{aid}/decision",
        headers=H_OP,
        json={"decision": "approve", "reason": "Checked the text against the brief."},
    ).json()
    assert done["status"] == "executed" and done["execution"]["receipt"]["mode"] == "dry_run"
    snap = client.get("/snapshot", headers=H_VW).json()
    assert snap["kpis"]["content"]["published"] == 1
    assert snap["kpis"]["risk"]["external_actions_without_approval"] == 0
    assert client.get("/audit/verify", headers=H_VW).json()["ok"]


def test_dry_run_evaluation_has_no_side_effects(client):
    before = client.get("/audit/verify", headers=H_VW).json()["count"]
    r = client.post(
        "/policy/evaluate",
        headers=H_OP,
        json={"agent_id": "eng.backend", "action_type": "deploy.production", "params": {}},
    )
    assert r.json()["outcome"] == "deny"
    assert client.get("/audit/verify", headers=H_VW).json()["count"] == before


def test_readiness_reports_a_broken_chain(client):
    office = client.app.state.office
    assert client.get("/ready").status_code == 200
    office.store.conn.execute("DROP TRIGGER audit_events_no_update")
    office.store.conn.execute("UPDATE audit_events SET subject = 'tampered' WHERE seq = 1")
    r = client.get("/ready")
    assert r.status_code == 503 and r.json()["checks"]["audit_chain"] is False


def test_emergency_stop_over_http(client):
    client.post("/daily-loop/run", headers=H_OP)
    state = client.post("/emergency-stop", headers=H_OP, json={"reason": "Drill over the API"}).json()
    assert state["halted"]
    pending = client.get("/approvals?status=pending", headers=H_VW).json()
    assert pending == []
    assert client.post("/daily-loop/run", headers=H_OP).json()["skipped"]
    released = client.post("/emergency-stop/release", headers=H_OP, json={"reason": "Drill finished cleanly"}).json()
    assert released["halted"] is False


def test_simulation_endpoint(client):
    ex = client.get("/simulations/scenarios", headers=H_VW).json()["incident"]["example"]
    r = client.post("/simulations", headers=H_OP, json={"scenario_type": "incident", **ex})
    assert r.status_code == 201
    assert r.json()["result"]["recommendation"]["direction"] == "minimize"


def test_rate_limit_on_mutations():
    app = create_app(make_office(), Settings(env="test", operator_token=OP, mutations_per_minute=2))
    c = TestClient(app)
    codes = [
        c.post("/emergency-stop/release", headers=H_OP, json={"reason": "nothing to release"}).status_code
        for _ in range(3)
    ]
    assert codes == [200, 200, 429]


def test_open_dev_mode_is_labelled():
    c = TestClient(create_app(make_office(), Settings(env="development")))
    r = c.get("/session")
    assert r.status_code == 200 and r.headers["X-Office-Auth"] == "development-open"


def test_grant_and_revoke_over_http(client):
    r = client.post(
        "/agents/revenue.sales-strategist/grants",
        headers=H_OP,
        json={
            "domain": "outreach",
            "level": "execute",
            "constraints": {"payload_allowlist": {"channel": ["email"]}, "spend_limit_cents": 0},
        },
    )
    assert r.status_code == 201 and r.json()["constraints"]["spend_limit_cents"] == 0
    assert (
        client.post(
            "/agents/revenue.sales-strategist/grants", headers=H_OP, json={"domain": "outreach", "level": "approve"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/agents/revenue.sales-strategist/grants/outreach/revoke",
            headers=H_VW,
            json={"reason": "viewer tries to revoke"},
        ).status_code
        == 403
    )
    r = client.post(
        "/agents/revenue.sales-strategist/grants/outreach/revoke",
        headers=H_OP,
        json={"reason": "Outreach paused until the list is cleaned."},
    )
    assert r.status_code == 200 and r.json()["revoked_at"]
    grants = client.get("/agents/revenue.sales-strategist/grants", headers=H_VW).json()
    assert any(g["domain"] == "outreach" and g["revoked_at"] for g in grants)


def test_mission_lifecycle_over_http(client):
    client.post("/daily-loop/run", headers=H_OP)
    mission = next(m for m in client.get("/missions", headers=H_VW).json() if m["status"] == "active")
    done = next(m for m in client.get("/missions", headers=H_VW).json() if m["status"] == "completed")
    assert client.post(f"/missions/{done['id']}/pause", headers=H_OP, json={"reason": "x" * 20}).status_code == 400
    r = client.post(f"/missions/{mission['id']}/pause", headers=H_OP, json={"reason": "Waiting on the client."})
    assert r.status_code == 200 and r.json()["status"] == "paused"
    assert client.post(f"/missions/{mission['id']}/explode", headers=H_OP, json={"reason": "x" * 20}).status_code == 422
    r = client.post(f"/missions/{mission['id']}/resume", headers=H_OP, json={"reason": "Client replied today."})
    assert r.json()["status"] == "active"


def test_shadow_report_and_idempotent_simulation(client):
    report = client.get("/policy/shadow-report", headers=H_VW).json()
    assert report["enforced"] is False and report["rules"]
    ex = client.get("/simulations/scenarios", headers=H_VW).json()["rollout"]["example"]
    body = {"scenario_type": "rollout", **ex}
    first = client.post("/simulations", headers={**H_OP, "Idempotency-Key": "sim-1"}, json=body)
    second = client.post("/simulations", headers={**H_OP, "Idempotency-Key": "sim-1"}, json=body)
    assert first.status_code == second.status_code == 201
    assert second.json()["replayed"] is True and len(client.get("/simulations", headers=H_VW).json()) == 1
