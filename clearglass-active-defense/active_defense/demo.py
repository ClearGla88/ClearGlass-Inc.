"""End-to-end lab demonstration over real loopback sockets.

It starts the control API (uvicorn), a real HTTP decoy and a real TCP
tripwire on 127.0.0.1, sends signed synthetic events, and walks one case
through: tripwire -> correlation -> case -> exact approval -> mock isolation
-> verification -> approved recovery. Nothing leaves the machine. All data is
synthetic and lives in a temporary directory unless --keep names one.
"""

from __future__ import annotations

import json
import socket
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import uvicorn

from . import honeytokens
from .adapters import MockNetworkAdapter
from .api import create_app
from .config import load_bundle
from .executor import Executor
from .lab import make_lab_deployment
from .sensors.client import AsyncSender, SignedClient
from .sensors.http_honeypot import HttpHoneypot
from .sensors.tcp_tripwire import TcpTripwire
from .simulate import scenario_events
from .store import Store
from .util import Clock


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _Api:
    def __init__(self, app, port: int) -> None:
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning",
                                                    lifespan="off"))
        self.thread = threading.Thread(target=self.server.run, name="api", daemon=True)

    def __enter__(self) -> _Api:
        self.thread.start()
        deadline = time.time() + 10
        while not self.server.started:
            if time.time() > deadline:
                raise RuntimeError("API did not start")
            time.sleep(0.05)
        return self

    def __exit__(self, *_exc) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10)


def _http(base: str, method: str, path: str, token: str | None = None, body: dict | None = None) -> tuple[int, Any]:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)  # noqa: S310 - loopback
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 - loopback only
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def run(keep: str | None = None, *, quiet: bool = False) -> dict:
    root = Path(keep) if keep else Path(tempfile.mkdtemp(prefix="cg-active-defense-demo-"))
    dep = make_lab_deployment(root, mode="recommend")
    bundle = load_bundle(dep.config_path)
    store = Store(bundle.database_path)
    store.init()
    clock = Clock()
    adapter = MockNetworkAdapter(bundle.state_dir / "mock_network.db")
    worker = Executor(store, bundle, adapter, clock, worker_id="demo-worker")
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    tok = dep.tokens
    env, scope = bundle.config.environment, bundle.config.authorization_scope
    log: list[dict] = []

    def step(name: str, **detail: Any) -> None:
        log.append({"step": name, **detail})
        if not quiet:
            extras = ", ".join(f"{k}={v}" for k, v in detail.items())
            print(f"[{len(log):02d}] {name}" + (f": {extras}" if extras else ""))

    with store.tx() as c:
        token = honeytokens.mint()
        token_id = honeytokens.register(c, token, label="demo decoy credential", placement="demo HTTP request",
                                        at=clock.now())
    step("honeytoken minted and registered", token_id=token_id, stored="fingerprint only")

    with _Api(create_app(bundle, store, clock), port):
        step("control API listening", url=base, bind="127.0.0.1 only")
        senders = {sid: AsyncSender(SignedClient(base, sid, dep.sensor_keys[sid])) for sid in
                   ("sensor-http-01", "sensor-tcp-01")}
        hp = HttpHoneypot("127.0.0.1", 0, sink=senders["sensor-http-01"].submit, sensor_id="sensor-http-01",
                          environment=env, scope=scope).start()
        tw = TcpTripwire("127.0.0.1", 0, sink=senders["sensor-tcp-01"].submit, sensor_id="sensor-tcp-01",
                         environment=env, scope=scope).start()
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{hp.port}/api/export", method="GET",
                                         headers={"Authorization": f"Bearer {token}", "User-Agent": "demo-client"})
            try:
                urllib.request.urlopen(req, timeout=5)  # noqa: S310 - loopback decoy
            except urllib.error.HTTPError as exc:
                step("HTTP decoy answered a request carrying the honeytoken", status=exc.code)
            with socket.create_connection(("127.0.0.1", tw.port), timeout=5):
                pass
            step("TCP tripwire connection made", port=tw.port)
            for s in senders.values():
                s.drain()
            results = [r for s in senders.values() for r in s.results]
            step("live decoy events accepted", count=sum(1 for code, _ in results if code == 200),
                 subjects=sorted({r[1].get("subject") for r in results}))
        finally:
            hp.stop()
            tw.stop()
            for s in senders.values():
                s.stop()
        _, loopback_cases = _http(base, "GET", "/v1/cases", tok["analyst-1"])
        step("loopback source is not an inventoried asset, so its case can only be investigated",
             cases=[(k["subject"], k["state"]) for k in loopback_cases])

        client = {sid: SignedClient(base, sid, key) for sid, key in dep.sensor_keys.items()}
        sid, ev = scenario_events("decoy-only", environment=env, scope=scope)[0]
        code, out = client[sid].send(ev)
        case_id = out["cases"][0]
        step("synthetic tripwire hit from 10.66.10.21", http=code, identity=out["identity"],
             subject=out["subject"], case=case_id)
        _, view = _http(base, "GET", f"/v1/cases/{case_id}", tok["analyst-1"])
        step("decoy alone: alert raised, no proposal", state=view["case"]["state"],
             proposals=len(view["proposals"]))

        sid, ev = scenario_events("corroborated", environment=env, scope=scope)[1]
        code, out = client[sid].send(ev)
        _, view = _http(base, "GET", f"/v1/cases/{case_id}", tok["analyst-1"])
        prop = view["proposals"][0]
        step("endpoint alert on lab-ws-001 corroborates the decoy hit", http=code,
             correlation=view["correlations"][0]["correlation_id"], state=view["case"]["state"])
        step("isolation proposal awaiting approval", proposal=prop["proposal_id"], plan_hash=prop["plan_hash"][:16],
             target=prop["target_asset_id"], preserved=prop["plan"]["preserved_access_paths"])

        decision = {"decision": "approved", "plan_hash": prop["plan_hash"],
                    "policy_version": bundle.config.policy_version, "reason": "demo: corroborated, single host"}
        code_a, _ = _http(base, "POST", f"/v1/proposals/{prop['proposal_id']}/decision", tok["analyst-1"], decision)
        code_b, out_b = _http(base, "POST", f"/v1/proposals/{prop['proposal_id']}/decision", tok["approver-1"],
                              {**decision, "plan_hash": "0" * 64})
        step("refused: analyst cannot approve; altered plan hash is rejected", analyst=code_a, tampered=code_b,
             reason=out_b.get("reason"))
        code, _ = _http(base, "POST", f"/v1/proposals/{prop['proposal_id']}/decision", tok["approver-1"], decision)
        code_r, out_r = _http(base, "POST", f"/v1/proposals/{prop['proposal_id']}/decision", tok["approver-1"],
                              decision)
        step("approver-1 approved the exact plan; a replayed approval is refused", http=code, replay=code_r,
             reason=out_r.get("reason"))

        result = worker.run_once()
        _, view = _http(base, "GET", f"/v1/cases/{case_id}", tok["analyst-1"])
        step("worker applied mock isolation and verified it", result=result[0]["status"],
             state=view["case"]["state"], adapter_rules=len(adapter.state("lab-ws-001", view["actions"][0]
                                                                          ["idempotency_key"])))

        criteria = {c.id: "demo: synthetic evidence note" for c in bundle.playbooks["PB-07-recovery"].recovery_criteria}
        code, rel = _http(base, "POST", f"/v1/cases/{case_id}/recovery-request", tok["analyst-1"],
                          {"criteria": criteria, "reason": "demo: host remediated"})
        step("analyst requested recovery with every criterion evidenced", http=code, proposal=rel["proposal_id"])
        rdecision = {"decision": "approved", "plan_hash": rel["plan_hash"],
                     "policy_version": bundle.config.policy_version, "reason": "demo: criteria reviewed"}
        code, _ = _http(base, "POST", f"/v1/proposals/{rel['proposal_id']}/decision", tok["approver-2"], rdecision)
        result = worker.run_once()
        _, view = _http(base, "GET", f"/v1/cases/{case_id}", tok["analyst-1"])
        step("approver-2 approved release; worker released and verified", http=code, result=result[0]["status"],
             state=view["case"]["state"], baseline_rules_untouched=adapter.baseline_rules() == 3)

        _, audit = _http(base, "GET", "/v1/audit/verify", tok["admin-1"])
        _, ev_check = _http(base, "GET", f"/v1/cases/{case_id}/evidence", tok["analyst-1"])
        _, metrics = _http(base, "GET", "/v1/metrics", tok["analyst-1"])
        step("audit chain verified", ok=audit["ok"], records=audit["records"])
        step("case evidence verified", ok=ev_check["verification"]["ok"],
             artifacts=ev_check["verification"]["artifacts"])
        step("metrics (lab, synthetic workload, single run; not a performance claim)",
             false_containment=metrics["false_containment_count"], recoveries=metrics["recoveries_verified"])
    return {"root": str(root), "steps": log, "metrics": metrics, "audit": audit}


def main_json(keep: str | None) -> None:
    print(json.dumps(run(keep, quiet=True), indent=2, default=str))


__all__ = ["run", "main_json"]
