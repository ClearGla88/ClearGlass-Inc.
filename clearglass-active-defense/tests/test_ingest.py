"""Ingestion: authentication, replay, deduplication, schema, scope, time, redaction, inert content."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from active_defense import honeytokens
from active_defense.errors import Rejected
from active_defense.sensors.client import encode
from active_defense.simulate import INJECTION_TEXT


def test_normal_traffic_creates_no_case(lab):
    out = lab.scenario("normal")[0]
    assert out["status"] == "accepted" and out["cases"] == [] and out["note"] == "no detection rule matched"
    assert lab.sql("SELECT COUNT(*) FROM cases")[0][0] == 0
    assert lab.sql("SELECT COUNT(*) FROM proposals")[0][0] == 0


def test_forged_signature_is_rejected_and_recorded(lab):
    with pytest.raises(Rejected) as exc:
        lab.send_event("sensor-tcp-01", lab.event("sensor-tcp-01", category="tripwire.tcp.connect",
                                                  src_ip="10.66.10.21"), key=b"x" * 43)
    assert exc.value.status == 401 and "signature" in exc.value.reason
    assert lab.sql("SELECT COUNT(*) FROM events")[0][0] == 0
    assert "ingest.rejected" in lab.audit_actions()


def test_unknown_sensor_and_missing_headers_are_rejected(lab):
    ev = lab.event("sensor-tcp-01", category="tripwire.tcp.connect", src_ip="10.66.10.21")
    headers, body = lab.signed("sensor-tcp-01", ev)
    headers["X-CG-Sensor"] = "sensor-ghost-01"
    with pytest.raises(Rejected) as exc:
        lab.engine.ingest(headers, body)
    assert exc.value.reason == "unknown sensor"
    with pytest.raises(Rejected) as exc:
        lab.engine.ingest({}, body)
    assert exc.value.status == 401


def test_stale_and_future_request_timestamps_are_rejected(lab):
    ev = lab.event("sensor-tcp-01", category="tripwire.tcp.connect", src_ip="10.66.10.21")
    now = int(lab.clock.now().timestamp())
    for ts in (now - 301, now + 301):
        with pytest.raises(Rejected) as exc:
            lab.send_event("sensor-tcp-01", ev, ts=ts)
        assert "clock skew" in exc.value.reason


def test_replayed_request_is_rejected(lab):
    headers, body = lab.signed("sensor-tcp-01", lab.event("sensor-tcp-01", category="tripwire.tcp.connect",
                                                           src_ip="10.66.10.21"))
    assert lab.engine.ingest(headers, body)["status"] == "accepted"
    with pytest.raises(Rejected) as exc:
        lab.engine.ingest(headers, body)
    assert exc.value.status == 409 and "replayed" in exc.value.reason


def test_duplicate_event_is_accepted_once(lab):
    ev = lab.event("sensor-tcp-01", category="tripwire.tcp.connect", src_ip="10.66.10.21")
    first = lab.send_event("sensor-tcp-01", ev)
    second = lab.send_event("sensor-tcp-01", ev)  # sensor retry: new nonce, same event_id
    assert first["status"] == "accepted" and second["status"] == "duplicate"
    assert second["cases"] == first["cases"]
    assert lab.sql("SELECT COUNT(*) FROM events")[0][0] == 1
    assert lab.sql("SELECT COUNT(*) FROM signals")[0][0] == 1


def test_duplicate_corroborating_event_does_not_duplicate_actions(lab):
    lab.decoy()
    edr = lab.event("sensor-edr-01", category="endpoint.alert", severity="high", asset_id="lab-ws-001",
                    attributes={"verdict": "suspicious", "behavior": "suspicious_process"})
    for _ in range(3):
        lab.send_event("sensor-edr-01", edr)
    assert lab.sql("SELECT COUNT(*) FROM proposals")[0][0] == 1


@pytest.mark.parametrize("mutate, status", [
    (lambda e: e.update(category="exploit.run"), 422),
    (lambda e: e.update(extra_field="x"), 422),
    (lambda e: e.update(src_ip="not-an-ip"), 422),
    (lambda e: e.update(event_id="short"), 422),
    (lambda e: e["attributes"].update({"BadKey": "x"}), 422),
    (lambda e: e["attributes"].update({f"k{i}": i for i in range(40)}), 422),
    (lambda e: e.update(occurred_at="2026-11-17T12:00:00"), 422),
])
def test_malformed_events_are_rejected(lab, mutate, status):
    ev = lab.event("sensor-tcp-01", category="tripwire.tcp.connect", src_ip="10.66.10.21")
    mutate(ev)
    with pytest.raises(Rejected) as exc:
        lab.send_event("sensor-tcp-01", ev)
    assert exc.value.status == status


def test_non_json_and_oversized_bodies_are_rejected(lab):
    with pytest.raises(Rejected) as exc:
        lab.send_event("sensor-tcp-01", {}, body=b"{not json")
    assert exc.value.status == 422
    with pytest.raises(Rejected) as exc:
        lab.send_event("sensor-tcp-01", {}, body=b"x" * 70000)
    assert exc.value.status == 413


def test_sensor_cannot_impersonate_another_or_report_foreign_categories(lab):
    ev = lab.event("sensor-edr-01", category="endpoint.alert", asset_id="lab-ws-001",
                   attributes={"verdict": "malicious", "behavior": "suspicious_process"})
    with pytest.raises(Rejected) as exc:  # signed by the tripwire, claims to be the EDR
        lab.send_event("sensor-tcp-01", ev)
    assert exc.value.status == 403
    ev = lab.event("sensor-tcp-01", category="endpoint.alert", asset_id="lab-ws-001",
                   attributes={"verdict": "malicious", "behavior": "suspicious_process"})
    with pytest.raises(Rejected) as exc:
        lab.send_event("sensor-tcp-01", ev)
    assert exc.value.status == 403 and "may not report" in exc.value.reason


def test_environment_and_scope_must_match(lab):
    ev = lab.event("sensor-tcp-01", category="tripwire.tcp.connect", src_ip="10.66.10.21")
    ev["environment"] = "production"
    with pytest.raises(Rejected) as exc:
        lab.send_event("sensor-tcp-01", ev)
    assert "environment" in exc.value.reason
    ev = lab.event("sensor-tcp-01", category="tripwire.tcp.connect", src_ip="10.66.10.21")
    ev["authorization_scope"] = "someone-else"
    with pytest.raises(Rejected) as exc:
        lab.send_event("sensor-tcp-01", ev)
    assert "scope" in exc.value.reason


def test_event_times(lab):
    now = lab.clock.now()
    with pytest.raises(Rejected, match="future"):
        lab.send("sensor-tcp-01", category="tripwire.tcp.connect", src_ip="10.66.10.21",
                 occurred_at=now + timedelta(hours=1))
    with pytest.raises(Rejected, match="older"):
        lab.send("sensor-tcp-01", category="tripwire.tcp.connect", src_ip="10.66.10.21",
                 occurred_at=now - timedelta(days=2))
    out = lab.send("sensor-tcp-01", category="tripwire.tcp.connect", src_ip="10.66.10.21",
                   occurred_at=now - timedelta(hours=1))
    assert lab.sql("SELECT late FROM events WHERE event_pk=?", out["event_pk"])[0][0] == 1


def test_out_of_order_events_still_correlate_on_occurrence_time(lab):
    now = lab.clock.now()
    case_id = lab.edr()["cases"][0]
    assert lab.state(case_id) == "enriched"  # endpoint alert alone: no decoy corroboration yet
    lab.send("sensor-tcp-01", category="tripwire.tcp.connect", src_ip="10.66.10.21",
             occurred_at=now - timedelta(minutes=10))
    assert lab.state(case_id) == "awaiting_approval"


def test_signature_failure_burst_recommends_but_does_not_distrust(lab):
    ev = lab.event("sensor-tcp-01", category="tripwire.tcp.connect", src_ip="10.66.10.21")
    for _ in range(5):
        with pytest.raises(Rejected):
            lab.send_event("sensor-tcp-01", ev, key=b"wrong-key-" * 5)
    cases = lab.sql("SELECT case_id FROM cases WHERE subject='sensor:sensor-tcp-01'")
    assert len(cases) == 1
    assert "sensor.distrust_recommended" in lab.audit_actions()
    assert lab.sql("SELECT COUNT(*) FROM sensor_trust")[0][0] == 0


def test_authorized_scanner_is_stored_but_raises_no_signal(lab):
    out = lab.decoy("10.66.0.50")
    assert out["identity"] == "AUTHORIZED_SCANNER" and out["cases"] == []
    assert lab.sql("SELECT COUNT(*) FROM events")[0][0] == 1


def test_prompt_injection_in_telemetry_stays_inert(lab):
    out = lab.scenario("injection")[0]
    assert out["subject"] == "ip:192.0.2.44"
    stored = json.loads(lab.sql("SELECT attributes_json FROM events")[0][0])
    assert stored["user_agent"] == INJECTION_TEXT[:256]  # kept verbatim as data
    assert lab.sql("SELECT COUNT(*) FROM proposals")[0][0] == 0
    assert lab.sql("SELECT COUNT(*) FROM actions")[0][0] == 0
    assert lab.sql("SELECT state FROM cases")[0][0] == "enriched"
    view = lab.case(out["cases"][0])
    assert {s["signal"] for s in view["signals"]} == {"decoy_interaction"}


def test_honeytoken_match_is_server_side_and_values_are_redacted(lab):
    token = honeytokens.mint()
    with lab.store.tx() as c:
        token_id = honeytokens.register(c, token, label="t", placement="test", at=lab.clock.now())
    out = lab.send("sensor-http-01", category="honeypot.http.request", src_ip="192.0.2.10",
                   attributes={"honeytoken_fingerprints": [honeytokens.fingerprint(token)],
                               "password": "hunter2", "user_agent": f"x {token} y"})
    assert {s["signal"] for s in out["signals"]} == {"decoy_interaction", "honeytoken_use"}
    attrs = json.loads(lab.sql("SELECT attributes_json FROM events")[0][0])
    derived = json.loads(lab.sql("SELECT derived_json FROM events")[0][0])
    assert attrs["password"] == "[REDACTED]" and token not in attrs["user_agent"]
    assert derived == {"honeytoken_match": True, "honeytoken_ids": [token_id]}
    assert token not in json.dumps([dict(r) for r in lab.sql("SELECT * FROM audit")])


def test_unregistered_fingerprint_does_not_raise_honeytoken_signal(lab):
    out = lab.send("sensor-http-01", category="honeypot.http.request", src_ip="192.0.2.10",
                   attributes={"honeytoken_fingerprints": ["a" * 64]})
    assert {s["signal"] for s in out["signals"]} == {"decoy_interaction"}


def test_encode_is_canonical():
    assert encode({"b": 1, "a": 2}) == b'{"a":2,"b":1}'
