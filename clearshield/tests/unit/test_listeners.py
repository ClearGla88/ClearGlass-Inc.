"""TCP listener parsing, attribution and comparison (unit).

The fixture tables use the little-endian layout the kernel prints on x86/ARM
little-endian hosts; 127.0.0.1 as 0100007F was observed on a live kernel."""

from __future__ import annotations

import os
import socket
import sys

import pytest

from clearshield_core import listeners

pytestmark = pytest.mark.skipif(sys.byteorder != "little", reason="fixtures use little-endian layout")

HEADER = "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
TCP4 = HEADER + (
    "   0: 0100007F:0277 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 1001 1\n"
    "   1: 00000000:0016 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 1002 1\n"
    "   2: 0302010A:1F90 00000000:0000 0A 00000000:00000000 00:00000000 00000000  1000        0 1003 1\n"
    "   3: 0100007F:0277 0100007F:C350 01 00000000:00000000 00:00000000 00000000     0        0 1004 1\n"
    "   4: garbage\n"
)
TCP6 = HEADER + (
    "   0: 00000000000000000000000000000000:0016 00000000000000000000000000000000:0000 0A "
    "00000000:00000000 00:00000000 00000000     0        0 2001 1\n"
    "   1: 00000000000000000000000001000000:0277 00000000000000000000000000000000:0000 0A "
    "00000000:00000000 00:00000000 00000000     0        0 2002 1\n"
    "   2: 0000000000000000FFFF00000100007F:1F91 00000000000000000000000000000000:0000 0A "
    "00000000:00000000 00:00000000 00000000     0        0 2003 1\n"
)


def test_ipv4_little_endian_decoding_and_scope():
    rows, malformed = listeners.parse_table(TCP4, "tcp4")
    got = {r["id"]: r["scope"] for r in rows}
    assert got == {
        "tcp4/127.0.0.1:631": "loopback",
        "tcp4/0.0.0.0:22": "all_interfaces",
        "tcp4/10.1.2.3:8080": "specific_address",
    }
    assert malformed == 1  # established connection (state 01) is skipped, garbage is counted


def test_ipv6_decoding_including_mapped_loopback():
    rows, _ = listeners.parse_table(TCP6, "tcp6")
    got = {r["id"]: r["scope"] for r in rows}
    assert got == {
        "tcp6/[::]:22": "all_interfaces",
        "tcp6/[::1]:631": "loopback",
        "tcp6/[::ffff:127.0.0.1]:8081": "loopback",
    }


def make_proc(root, tcp4=TCP4, tcp6=None, owners=None):
    net = root / "net"
    net.mkdir(parents=True)
    (net / "tcp").write_text(tcp4)
    if tcp6 is not None:
        (net / "tcp6").write_text(tcp6)
    for pid, (inode, exe) in (owners or {}).items():
        fd = root / str(pid) / "fd"
        fd.mkdir(parents=True)
        os.symlink(f"socket:[{inode}]", fd / "3")
        os.symlink("/dev/null", fd / "0")
        os.symlink(exe, root / str(pid) / "exe")
        (root / str(pid) / "comm").write_text(os.path.basename(exe) + "\n")
    return str(root)


def test_collect_with_attribution_and_missing_ipv6(tmp_path):
    proc = make_proc(tmp_path / "proc", owners={123: (1002, "/usr/sbin/sshd")})
    result = listeners.collect(proc, attribute=True, budget_s=5)
    assert result["sources"] == {"tcp4": "ok", "tcp6": "unavailable"}
    by_id = {e["id"]: e for e in result["listeners"]}
    assert by_id["tcp4/0.0.0.0:22"]["attribution"] == "ok"
    assert by_id["tcp4/0.0.0.0:22"]["processes"][0] == {"pid": 123, "exe": "/usr/sbin/sshd", "comm": "sshd"}
    assert by_id["tcp4/127.0.0.1:631"]["attribution"] == "unattributed: no owning process found"


def test_attribution_denied_is_reported_not_dropped(tmp_path, monkeypatch):
    proc = make_proc(tmp_path / "proc", owners={123: (1002, "/usr/sbin/sshd")})
    real = os.listdir

    def listdir(path):
        if path.endswith(os.path.join("123", "fd")):
            raise PermissionError(13, "Permission denied")
        return real(path)

    monkeypatch.setattr(listeners.os, "listdir", listdir)
    result = listeners.collect(proc, attribute=True, budget_s=5)
    entry = {e["id"]: e for e in result["listeners"]}["tcp4/0.0.0.0:22"]
    assert entry["attribution"].startswith("unattributed: insufficient permission")
    assert entry["uid"] == 0  # the kernel table still says who owns the socket
    assert result["attribution"]["pids_denied"] == 1


def test_reuseport_duplicates_merge(tmp_path):
    dup = TCP4 + "   5: 00000000:0016 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 1009 1\n"
    proc = make_proc(tmp_path / "proc", tcp4=dup)
    ids = [e["id"] for e in listeners.collect(proc, attribute=False)["listeners"]]
    assert ids.count("tcp4/0.0.0.0:22") == 1


def test_compare_new_listener_severity_allowlist_and_gone(tmp_path):
    proc = make_proc(tmp_path / "proc", tcp6=TCP6)
    current = listeners.collect(proc, attribute=False)
    baseline = ["tcp4/127.0.0.1:631", "tcp4/192.0.2.1:25"]
    allow = listeners.parse_allow(["*:8081", "[::1]:631"])
    findings = listeners.compare(baseline, current, allow)
    got = {(f["kind"], f["listener"]): f["severity"] for f in findings}
    assert got == {
        ("new_listener", "tcp4/0.0.0.0:22"): "high",
        ("new_listener", "tcp6/[::]:22"): "high",
        ("new_listener", "tcp4/10.1.2.3:8080"): "medium",
        ("listener_gone", "tcp4/192.0.2.1:25"): "info",
    }
    new = [f for f in findings if f["kind"] == "new_listener"][0]
    assert "not proof of external reachability" in new["detail"]["note"]


@pytest.mark.parametrize("bad", ["8080", "localhost:22", "1.2.3.4:0", "1.2.3.4:99999", "[::1]:x"])
def test_parse_allow_rejects_bad_entries(bad):
    with pytest.raises(ValueError):
        listeners.parse_allow([bad])


def _ipv6_loopback_available() -> bool:
    if not socket.has_ipv6 or not os.path.exists("/proc/net/tcp6"):
        return False
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as probe:
            probe.bind(("::1", 0))
        return True
    except OSError:
        return False


@pytest.mark.skipif(not _ipv6_loopback_available(), reason="needs IPv6 loopback and /proc/net/tcp6")
def test_live_kernel_ipv6_listener_is_decoded():
    sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        sock.bind(("::1", 0))
        sock.listen()
        port = sock.getsockname()[1]
        result = listeners.collect("/proc", attribute=False)
        assert result["sources"]["tcp6"] == "ok" and result["malformed_lines"] == 0
        entry = {e["id"]: e for e in result["listeners"]}[f"tcp6/[::1]:{port}"]
        assert entry["scope"] == "loopback" and entry["address"] == "::1"
    finally:
        sock.close()


@pytest.mark.skipif(not os.path.exists("/proc/net/tcp"), reason="needs Linux /proc")
def test_live_kernel_listener_is_seen():
    sock = socket.socket()
    try:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        port = sock.getsockname()[1]
        result = listeners.collect("/proc", attribute=True, budget_s=5)
        entry = {e["id"]: e for e in result["listeners"]}[f"tcp4/127.0.0.1:{port}"]
        assert entry["scope"] == "loopback"
        if os.geteuid() == 0:
            assert os.getpid() in [p["pid"] for p in entry["processes"]]
    finally:
        sock.close()
