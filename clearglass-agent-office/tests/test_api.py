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
