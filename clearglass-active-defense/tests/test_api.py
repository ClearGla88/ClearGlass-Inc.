"""Control API: authentication, role separation, ingestion over HTTP, and the decision flow."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from active_defense.api import create_app


@pytest.fixture
def api(lab):
    client = TestClient(create_app(lab.bundle, lab.store, lab.clock), raise_server_exceptions=True)
    client.lab = lab
    return client


def auth(lab, who):
    return {"Authorization": f"Bearer {lab.dep.tokens[who]}"}


def test_health_and_ready(api):
    assert api.get("/health").json() == {"status": "ok"}
    body = api.get("/ready").json()
    assert body["database"] is True and body["mode"] == "recommend"


def test_authentication_required(api):
    assert api.get("/v1/cases").status_code == 401
    assert api.get("/v1/cases", headers={"Authorization": "Bearer not-a-token"}).status_code == 401
    assert api.get("/v1/cases", headers={"Authorization": "Basic abc"}).status_code == 401


def test_role_separation(api):
    lab = api.lab
    for who in ("analyst-1", "approver-1", "admin-1"):
        assert api.get("/v1/cases", headers=auth(lab, who)).status_code == 200
    assert api.get("/v1/audit/verify", headers=auth(lab, "analyst-1")).status_code == 403
    assert api.get("/v1/audit/verify", headers=auth(lab, "admin-1")).json()["ok"] is True
    stop = {"engaged": True, "reason": "x"}
    assert api.post("/v1/controls/emergency-stop", json=stop, headers=auth(lab, "approver-1")).status_code == 403
    assert api.post("/v1/sensors/sensor-tcp-01/trust", json={"trusted": False, "reason": "x"},
                    headers=auth(lab, "analyst-1")).status_code == 403


def test_ingest_over_http(api):
    lab = api.lab
    headers, body = lab.signed("sensor-tcp-01", lab.event("sensor-tcp-01", category="tripwire.tcp.connect",
                                                           src_ip="10.66.10.21"))
    r = api.post("/v1/events", content=body, headers=headers)
    assert r.status_code == 200 and r.json()["subject"] == "asset:lab-ws-001"
    r = api.post("/v1/events", content=body, headers=headers)
    assert r.status_code == 409 and r.json()["status"] == "rejected"


def test_ingest_size_limit_and_bad_signature(api):
    lab = api.lab
    r = api.post("/v1/events", content=b"x" * 70000, headers={"Content-Type": "application/json"})
    assert r.status_code == 413
    headers, body = lab.signed("sensor-tcp-01", lab.event("sensor-tcp-01", category="tripwire.tcp.connect",
                                                           src_ip="10.66.10.21"), key=b"k" * 43)
    assert api.post("/v1/events", content=body, headers=headers).status_code == 401


def test_decision_and_recovery_over_http(api):
    lab = api.lab
    case_id = lab.corroborate()
    prop = api.get(f"/v1/cases/{case_id}", headers=auth(lab, "analyst-1")).json()["proposals"][0]
    body = {"decision": "approved", "plan_hash": prop["plan_hash"], "policy_version": "pv-lab-1", "reason": "ok"}
    url = f"/v1/proposals/{prop['proposal_id']}/decision"
    assert api.post(url, json=body, headers=auth(lab, "analyst-1")).status_code == 403
    assert api.post(url, json={**body, "extra": 1}, headers=auth(lab, "approver-1")).status_code == 422
    assert api.post(url, json=body, headers=auth(lab, "approver-1")).json()["status"] == "approved"
    assert api.post(url, json=body, headers=auth(lab, "approver-1")).status_code == 409
    assert lab.executor.run_once()[0]["status"] == "verified"
    r = api.post(f"/v1/cases/{case_id}/recovery-request", json={"criteria": lab.criteria(), "reason": "fixed"},
                 headers=auth(lab, "analyst-1"))
    rel = r.json()
    assert r.status_code == 200 and rel["kind"] == "release"
    body = {**body, "plan_hash": rel["plan_hash"]}
    assert api.post(f"/v1/proposals/{rel['proposal_id']}/decision", json=body,
                    headers=auth(lab, "approver-2")).status_code == 200
    lab.executor.run_once()
    assert api.get(f"/v1/cases/{case_id}", headers=auth(lab, "analyst-1")).json()["case"]["state"] == "closed"
    ev = api.get(f"/v1/cases/{case_id}/evidence", headers=auth(lab, "analyst-1")).json()
    assert ev["verification"]["ok"] is True


def test_path_parameters_are_validated(api):
    assert api.get("/v1/cases/..%2Fetc", headers=auth(api.lab, "analyst-1")).status_code in (404, 422)
    assert api.get("/v1/cases/no-such-case", headers=auth(api.lab, "analyst-1")).status_code == 404


def test_production_hides_interactive_docs(make_lab, tmp_path):
    from active_defense.config import load_bundle
    from active_defense.lab import make_lab_deployment
    from active_defense.store import Store
    dep = make_lab_deployment(tmp_path / "prod", environment="production")
    b = load_bundle(dep.config_path)
    s = Store(b.database_path)
    s.init()
    client = TestClient(create_app(b, s))
    assert client.get("/docs").status_code == 404 and client.get("/openapi.json").status_code == 404
