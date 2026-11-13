"""TCP listener inventory from /proc/net/tcp and /proc/net/tcp6.

Scope: TCP sockets in LISTEN state on this host. Not UDP, not packet
inspection, not traffic monitoring. A listener on all interfaces is not proof
of exposure: firewalls, NAT and cloud security groups decide reachability.

Kernel format: the address column is the raw 32-bit words printed as hex in
the host's native byte order, so 127.0.0.1 appears as 0100007F on
little-endian machines. Decoding uses native order ("=I").

Process attribution maps the socket inode to a PID by reading
/proc/<pid>/fd/*. Reading another user's fd directory requires privilege; when
it is denied the listener is still reported, marked ``unattributed``.
"""

from __future__ import annotations

import ipaddress
import os
import re
import struct
import time
from typing import Any, Callable

LISTEN = "0A"
_SOCKET_LINK = re.compile(r"\Asocket:\[(\d+)\]\Z")


def _decode_v4(hexaddr: str) -> ipaddress.IPv4Address:
    return ipaddress.IPv4Address(struct.pack("=I", int(hexaddr, 16)))


def _decode_v6(hexaddr: str) -> ipaddress.IPv6Address:
    words = [int(hexaddr[i:i + 8], 16) for i in range(0, 32, 8)]
    return ipaddress.IPv6Address(b"".join(struct.pack("=I", w) for w in words))


def scope_of(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str:
    mapped = getattr(ip, "ipv4_mapped", None)
    effective = mapped if mapped is not None else ip
    if effective.is_loopback:
        return "loopback"
    if effective.is_unspecified:
        return "all_interfaces"
    return "specific_address"


def addr_text(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str:
    """Stable text form. IPv4-mapped IPv6 is spelled ::ffff:a.b.c.d explicitly because
    CPython versions disagree (3.12.3 prints ::ffff:7f00:1, 3.11.18/3.13.18 print
    ::ffff:127.0.0.1); baseline identities must not change with the interpreter."""
    mapped = getattr(ip, "ipv4_mapped", None)
    return f"::ffff:{mapped}" if mapped is not None else str(ip)


def listener_id(family: str, ip: Any, port: int) -> str:
    text = addr_text(ip)
    host = f"[{text}]" if family == "tcp6" else text
    return f"{family}/{host}:{port}"


def parse_table(text: str, family: str) -> tuple[list[dict], int]:
    """Parse one /proc/net/tcp{,6} table. Returns (listeners, malformed_line_count)."""
    decode = _decode_v4 if family == "tcp4" else _decode_v6
    width = 8 if family == "tcp4" else 32
    out: list[dict] = []
    malformed = 0
    for line in text.splitlines()[1:]:
        fields = line.split()
        if len(fields) < 10:
            if fields:
                malformed += 1
            continue
        if fields[3] != LISTEN:
            continue
        try:
            addr_hex, port_hex = fields[1].split(":")
            if len(addr_hex) != width:
                raise ValueError("address width")
            ip = decode(addr_hex)
            port = int(port_hex, 16)
            uid = int(fields[7])
            inode = int(fields[9])
        except (ValueError, struct.error):
            malformed += 1
            continue
        out.append({
            "id": listener_id(family, ip, port),
            "family": family,
            "address": addr_text(ip),
            "port": port,
            "scope": scope_of(ip),
            "uid": uid,
            "inode": inode,
        })
    return out, malformed


def _read_text(path: str, limit: int = 32 * 1024 * 1024) -> str:
    with open(path, "rb") as fh:
        data = fh.read(limit + 1)
    if len(data) > limit:
        raise OSError(f"{path} exceeds {limit} bytes")
    return data.decode("ascii", "replace")


def inode_owners(
    proc_root: str, wanted: set[int], budget_s: float, clock: Callable[[], float] = time.monotonic
) -> tuple[dict[int, list[int]], dict[str, Any]]:
    """Map socket inodes to PIDs. Bounded by a time budget."""
    owners: dict[int, list[int]] = {}
    stats = {"pids_scanned": 0, "pids_denied": 0, "partial": False}
    deadline = clock() + budget_s
    try:
        entries = os.listdir(proc_root)
    except OSError:
        stats["partial"] = True
        return owners, stats
    for name in entries:
        if not name.isdigit():
            continue
        if clock() > deadline:
            stats["partial"] = True
            break
        fd_dir = os.path.join(proc_root, name, "fd")
        try:
            fds = os.listdir(fd_dir)
        except PermissionError:
            stats["pids_denied"] += 1
            continue
        except OSError:
            continue  # process exited
        stats["pids_scanned"] += 1
        for fd in fds:
            try:
                target = os.readlink(os.path.join(fd_dir, fd))
            except OSError:
                continue
            match = _SOCKET_LINK.match(target)
            if match:
                inode = int(match.group(1))
                if inode in wanted:
                    owners.setdefault(inode, []).append(int(name))
    return owners, stats


def _proc_detail(proc_root: str, pid: int) -> dict[str, Any]:
    detail: dict[str, Any] = {"pid": pid, "exe": None, "comm": None}
    try:
        detail["exe"] = os.readlink(os.path.join(proc_root, str(pid), "exe"))
    except OSError:
        pass
    try:
        with open(os.path.join(proc_root, str(pid), "comm"), "rb") as fh:
            detail["comm"] = fh.read(64).decode("utf-8", "replace").strip()
    except OSError:
        pass
    return detail


def collect(proc_root: str = "/proc", attribute: bool = True, budget_s: float = 5.0) -> dict:
    """Current TCP listeners plus a description of what could and could not be read."""
    sources: dict[str, str] = {}
    raw: list[dict] = []
    malformed = 0
    for family, name in (("tcp4", "tcp"), ("tcp6", "tcp6")):
        path = os.path.join(proc_root, "net", name)
        try:
            text = _read_text(path)
        except FileNotFoundError:
            sources[family] = "unavailable"
            continue
        except OSError as exc:
            sources[family] = f"error: {exc}"
            continue
        rows, bad = parse_table(text, family)
        raw.extend(rows)
        malformed += bad
        sources[family] = "ok"

    # SO_REUSEPORT and multiple processes can yield several sockets per identity.
    merged: dict[str, dict] = {}
    for row in raw:
        entry = merged.setdefault(row["id"], {**row, "inodes": []})
        entry["inodes"].append(row.pop("inode"))
        entry.pop("inode", None)

    attribution: dict[str, Any] = {"enabled": attribute}
    if attribute and merged:
        wanted = {i for e in merged.values() for i in e["inodes"]}
        owners, stats = inode_owners(proc_root, wanted, budget_s)
        attribution.update(stats)
        for entry in merged.values():
            pids = sorted({p for i in entry["inodes"] for p in owners.get(i, [])})
            if pids:
                entry["processes"] = [_proc_detail(proc_root, p) for p in pids[:16]]
                entry["attribution"] = "ok"
            elif stats["pids_denied"] or stats["partial"]:
                entry["processes"] = []
                entry["attribution"] = "unattributed: insufficient permission or time budget"
            else:
                entry["processes"] = []
                entry["attribution"] = "unattributed: no owning process found"
    else:
        for entry in merged.values():
            entry["processes"] = []
            entry["attribution"] = "disabled"
    for entry in merged.values():
        entry.pop("inodes", None)
    return {
        "listeners": sorted(merged.values(), key=lambda e: e["id"]),
        "sources": sources,
        "malformed_lines": malformed,
        "attribution": attribution,
    }


# ------------------------------------------------------------------ comparison

def parse_allow(entries: list[str]) -> list[tuple[str, int]]:
    """'127.0.0.1:631', '[::1]:631', '*:22' -> [(address or '*', port)]."""
    out: list[tuple[str, int]] = []
    for entry in entries:
        host, sep, port = entry.rpartition(":")
        if not sep or not port.isdigit() or not 0 < int(port) < 65536:
            raise ValueError(f"listeners.allow entry {entry!r} must look like ADDRESS:PORT")
        host = host[1:-1] if host.startswith("[") and host.endswith("]") else host
        if host != "*":
            host = addr_text(ipaddress.ip_address(host))
        out.append((host, int(port)))
    return out


def _allowed(entry: dict, allow: list[tuple[str, int]]) -> bool:
    return any(port == entry["port"] and host in ("*", entry["address"]) for host, port in allow)


SCOPE_SEVERITY = {"all_interfaces": "high", "specific_address": "medium", "loopback": "low"}


def compare(baseline_ids: list[str], current: dict, allow: list[tuple[str, int]]) -> list[dict]:
    base = set(baseline_ids)
    now = {e["id"]: e for e in current["listeners"]}
    findings: list[dict] = []
    for lid in sorted(set(now) - base):
        entry = now[lid]
        if _allowed(entry, allow):
            continue
        findings.append({
            "layer": "listeners",
            "kind": "new_listener",
            "severity": SCOPE_SEVERITY[entry["scope"]],
            "listener": lid,
            "detail": {
                "scope": entry["scope"],
                "uid": entry["uid"],
                "attribution": entry["attribution"],
                "processes": entry["processes"],
                "note": "listening is not proof of external reachability",
            },
        })
    for lid in sorted(base - set(now)):
        findings.append({"layer": "listeners", "kind": "listener_gone", "severity": "info",
                         "listener": lid, "detail": {}})
    for family, status in current["sources"].items():
        if status != "ok":
            findings.append({"layer": "listeners", "kind": "source_unavailable",
                             "severity": "info", "listener": family, "detail": {"status": status}})
    return findings
