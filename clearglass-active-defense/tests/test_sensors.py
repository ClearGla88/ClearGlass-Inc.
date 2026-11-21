"""Deception sensors over real loopback sockets. Nothing they receive is executed or echoed."""

from __future__ import annotations

import http.client
import os
import socket
import sys
import time

import pytest

from active_defense import honeytokens
from active_defense.sensors.client import SignedClient
from active_defense.sensors.honeyfile import HoneyfileWatcher, create_honeyfile
from active_defense.sensors.http_honeypot import HttpHoneypot
from active_defense.sensors.tcp_tripwire import TcpTripwire

COMMON = {"sensor_id": "sensor-x", "environment": "lab", "scope": "clearglass-lab-01"}


def wait_for(cond, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def honeypot():
    events = []
    hp = HttpHoneypot("127.0.0.1", 0, sink=events.append, max_capture_bytes=256, **COMMON).start()
    yield hp, events
    hp.stop()


def request(hp, method, path, body=b"", headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", hp.port, timeout=5)
    conn.request(method, path, body=body, headers=headers or {})
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp.status, data


def test_http_decoy_serves_fixed_content_and_records_metadata(honeypot):
    hp, events = honeypot
    status, data = request(hp, "GET", "/?user=MARKER123")
    assert status == 200 and b"Staff Portal" in data and b"MARKER123" not in data
    ev = events[0]
    assert ev["category"] == "honeypot.http.request" and ev["src_ip"] == "127.0.0.1"
    assert ev["attributes"]["query_keys"] == ["user"] and "MARKER123" not in str(ev)


def test_http_decoy_fingerprints_honeytokens_and_never_echoes(honeypot):
    hp, events = honeypot
    token = honeytokens.mint()
    status, data = request(hp, "POST", "/login", body=b"u=admin&p=$(id)&note=MARKER456",
                           headers={"Authorization": f"Bearer {token}"})
    assert status == 401 and b"MARKER456" not in data and token.encode() not in data
    attrs = events[0]["attributes"]
    assert attrs["honeytoken_fingerprints"] == [honeytokens.fingerprint(token)]
    assert attrs["has_authorization"] is True and token not in str(events[0])
    assert len(attrs["body_sha256"]) == 64


def test_http_decoy_bounds_capture(honeypot):
    hp, events = honeypot
    status, _ = request(hp, "POST", "/upload", body=b"A" * 5000)
    assert status == 413 and events[0]["attributes"]["body_oversized"] is True
    assert events[0]["attributes"]["body_sha256"] == ""  # the oversized body was never read


def test_tcp_tripwire_records_and_deduplicates():
    events = []
    tw = TcpTripwire("127.0.0.1", 0, sink=events.append, dedup_seconds=60, **COMMON).start()
    try:
        for _ in range(3):
            with socket.create_connection(("127.0.0.1", tw.port), timeout=2) as s:
                s.settimeout(2)
                assert s.recv(16) == b""  # no banner: the connection is closed at once
        assert wait_for(lambda: tw.suppressed.get("127.0.0.1") == 2)
        assert len(events) == 1 and events[0]["category"] == "tripwire.tcp.connect"
    finally:
        tw.stop()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="inotify is Linux-only")
def test_honeyfile_open_is_detected_with_inotify(tmp_path):
    path = tmp_path / "svc-credentials.ini"
    token = create_honeyfile(path)
    assert honeytokens.HONEYTOKEN_RE.fullmatch(token) and token in path.read_text()
    events = []
    w = HoneyfileWatcher([path], sink=events.append, coalesce_seconds=0, **COMMON).start()
    try:
        assert w.capabilities()["open_or_read"] is True and w.capabilities()["actor_identity"] is False
        path.read_text()
        assert wait_for(lambda: any(e["category"] == "honeyfile.access" for e in events))
        with path.open("a") as fh:
            fh.write("\n")
        assert wait_for(lambda: any(e["category"] == "honeyfile.modify" for e in events))
    finally:
        w.stop()


def test_honeyfile_polling_fallback_cannot_see_reads(tmp_path):
    path = tmp_path / "decoy.txt"
    create_honeyfile(path)
    events = []
    w = HoneyfileWatcher([path], sink=events.append, poll_seconds=0.05, **COMMON)
    w._lib = None  # simulate a platform without inotify
    w.start()
    try:
        assert w.capabilities() == {"mechanism": "polling", "open_or_read": False, "modify": True,
                                    "delete_or_move": True, "actor_identity": False}
        path.read_text()
        time.sleep(0.3)
        assert events == []
        path.unlink()
        assert wait_for(lambda: events and events[0]["attributes"]["change"] == "deleted")
    finally:
        w.stop()


def test_create_honeyfile_refuses_to_overwrite(tmp_path):
    path = tmp_path / "x.ini"
    path.write_text("real file")
    with pytest.raises(FileExistsError):
        create_honeyfile(path)
    assert path.read_text() == "real file"


def test_client_spools_when_api_is_unreachable(tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    client = SignedClient(f"http://127.0.0.1:{port}", "sensor-x", b"k" * 43, timeout=1, spool_dir=tmp_path / "spool")
    status, body = client.send({"event_id": "evt-spool-0001", "x": 1})
    files = list((tmp_path / "spool").glob("*.json"))
    assert status == 0 and body["status"] == "spooled" and len(files) == 1
    assert oct(os.stat(files[0]).st_mode & 0o777) == "0o600"
    assert client.flush_spool() == 0 and len(list((tmp_path / "spool").glob("*.json"))) == 1
