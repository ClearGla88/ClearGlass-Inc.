"""Shared lab harness. Every test runs against a fresh synthetic deployment in tmp_path."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from active_defense import signing  # noqa: E402
from active_defense.adapters import MockNetworkAdapter  # noqa: E402
from active_defense.config import load_bundle  # noqa: E402
from active_defense.engine import Engine  # noqa: E402
from active_defense.executor import Executor  # noqa: E402
from active_defense.lab import make_lab_deployment  # noqa: E402
from active_defense.operations import Operations  # noqa: E402
from active_defense.sensors.client import build_event, encode  # noqa: E402
from active_defense.simulate import scenario_events  # noqa: E402
from active_defense.store import Store  # noqa: E402
from active_defense.util import FixedClock  # noqa: E402

T0 = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)


class Lab:
    def __init__(self, root: Path, *, mode: str = "recommend", response: dict | None = None,
                 ingest: dict | None = None) -> None:
        self.root = root
        self.dep = make_lab_deployment(root, mode=mode, response=response, ingest=ingest)
        self.bundle = load_bundle(self.dep.config_path)
        self.store = Store(self.bundle.database_path)
        self.store.init()
        self.clock = FixedClock(T0)
        self.engine = Engine(self.store, self.bundle, self.clock)
        self.ops = Operations(self.engine)
        self.adapter = MockNetworkAdapter(root / "var" / "mock_network.db")
        self.executor = Executor(self.store, self.bundle, self.adapter, self.clock, worker_id="worker-a")
        self.p = {p.principal: p for p in self.bundle.principals_by_token_hash.values()}

    # ---------------------------------------------------------------- events

    def event(self, sensor: str, **kw) -> dict:
        kw.setdefault("occurred_at", self.clock.now())
        return build_event(sensor_id=sensor, environment=self.bundle.config.environment,
                           scope=self.bundle.config.authorization_scope, **kw)

    def signed(self, sensor: str, event: dict, *, key: bytes | None = None, ts: int | None = None,
               nonce: str | None = None, body: bytes | None = None) -> tuple[dict, bytes]:
        body = encode(event) if body is None else body
        headers = signing.signed_headers(key or self.dep.sensor_keys[sensor], sensor, body,
                                         unix_time=ts if ts is not None else int(self.clock.now().timestamp()),
                                         nonce=nonce)
        return headers, body

    def send_event(self, sensor: str, event: dict, **sign_kw) -> dict:
        headers, body = self.signed(sensor, event, **sign_kw)
        return self.engine.ingest(headers, body)

    def send(self, sensor: str, **kw) -> dict:
        return self.send_event(sensor, self.event(sensor, **kw))

    def scenario(self, name: str) -> list[dict]:
        cfg = self.bundle.config
        return [self.send_event(s, e) for s, e in
                scenario_events(name, environment=cfg.environment, scope=cfg.authorization_scope, at=self.clock.now())]

    def decoy(self, ip: str = "10.66.10.21") -> dict:
        return self.send("sensor-tcp-01", category="tripwire.tcp.connect", src_ip=ip, dst_port=2222)

    def edr(self, asset: str = "lab-ws-001", behavior: str = "suspicious_process", verdict: str = "suspicious",
            **kw) -> dict:
        return self.send("sensor-edr-01", category="endpoint.alert", severity="high", asset_id=asset,
                         attributes={"verdict": verdict, "behavior": behavior}, **kw)

    def corroborate(self, asset: str = "lab-ws-001", ip: str = "10.66.10.21") -> str:
        self.decoy(ip)
        return self.edr(asset)["cases"][0]

    # ---------------------------------------------------------------- operator helpers

    def case(self, case_id: str) -> dict:
        return self.ops.case(self.p["analyst-1"], case_id)

    def proposal(self, case_id: str, kind: str = "isolate") -> dict:
        return [p for p in self.case(case_id)["proposals"] if p["kind"] == kind][-1]

    def decide(self, proposal: dict, who: str = "approver-1", decision: str = "approved", **override) -> dict:
        args = {"decision": decision, "plan_hash": proposal["plan_hash"],
                "policy_version": self.bundle.config.policy_version, "reason": "test decision"}
        args.update(override)
        return self.ops.decide(self.p[who], proposal["proposal_id"], **args)

    def criteria(self) -> dict[str, str]:
        return {c.id: "evidence recorded in test" for c in self.bundle.playbooks["PB-07-recovery"].recovery_criteria}

    def contain(self, asset: str = "lab-ws-001", ip: str = "10.66.10.21") -> str:
        case_id = self.corroborate(asset, ip)
        self.decide(self.proposal(case_id))
        result = self.executor.run_once()
        assert result[-1]["status"] == "verified", result
        return case_id

    def recover(self, case_id: str) -> list[dict]:
        rel = self.ops.request_recovery(self.p["analyst-1"], case_id, criteria=self.criteria(), reason="fixed")
        self.decide(rel, who="approver-2")
        return self.executor.run_once()

    def state(self, case_id: str) -> str:
        return self.case(case_id)["case"]["state"]

    def sql(self, query: str, *args) -> list:
        return self.store.connect().execute(query, args).fetchall()

    def audit_actions(self) -> list[str]:
        return [r["action"] for r in self.sql("SELECT action FROM audit ORDER BY seq")]


@pytest.fixture
def lab(tmp_path: Path) -> Lab:
    return Lab(tmp_path)


@pytest.fixture
def make_lab(tmp_path: Path):
    counter = {"n": 0}

    def factory(**kw) -> Lab:
        counter["n"] += 1
        return Lab(tmp_path / f"lab{counter['n']}", **kw)

    return factory
