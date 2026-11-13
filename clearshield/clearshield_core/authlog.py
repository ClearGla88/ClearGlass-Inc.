"""SSH authentication-failure monitoring from log files or the systemd journal.

Scope (v1): OpenSSH server messages only ("Failed <method> for ...",
"Invalid user ...", "Accepted <method> for ..."). sudo, su, console logins and
PAM-only messages are not analysed. Check the patterns against your own logs:
message wording can differ between OpenSSH versions and distributions.

Untrusted input: the username in these messages is whatever the remote client
sent. Parsing therefore anchors on the *last* "from <ip> port <n>" in the
message and validates the address, so a username such as
"x from 10.0.0.5 port 22" cannot redirect blame to 10.0.0.5. Usernames are
escaped before display.

Privacy: people sometimes type a password into the username prompt, so the
attempted name of an invalid user is a possible credential. By default only
names of accounts that exist on this host are recorded; invalid usernames are
counted, not stored (``auth.record_invalid_usernames``).

Counting: failures = "Failed ..." lines + "Invalid user" connections that
produced no "Failed" line. Thresholds count events per source address inside a
sliding window. Crossing a threshold is suspicious activity, not proof of
intrusion; a successful login from an address with recent failures is reported
separately and is also not proof.
"""

from __future__ import annotations

import ipaddress
import json
import os
import pwd
import re
import selectors
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable

from .report import sanitize

_TAIL = r" from (?P<ip>[0-9A-Fa-f:.]{2,45}) port (?P<port>\d{1,5})(?: ssh2)?(?: \[preauth\])?\s*\Z"
FAILED_RE = re.compile(r"\AFailed (?P<method>[\w-]+) for (?P<invalid>invalid user )?(?P<user>.*)" + _TAIL, re.S)
INVALID_RE = re.compile(r"\AInvalid user (?P<user>.*)" + _TAIL, re.S)
ACCEPTED_RE = re.compile(r"\AAccepted (?P<method>[\w-]+) for (?P<user>.*)" + _TAIL, re.S)
SYSLOG_RE = re.compile(
    r"\A(?P<ts>\d{4}-\d{2}-\d{2}T\S+|[A-Z][a-z]{2} [ \d]\d \d{2}:\d{2}:\d{2}) "
    r"(?P<host>\S+) (?P<prog>sshd(?:-session)?)(?:\[\d+\])?: (?P<msg>.*)\Z",
    re.S,
)
DEFAULT_FILES = ("/var/log/auth.log", "/var/log/secure")
SSH_IDENTIFIERS = ("sshd", "sshd-session")
MAX_LINE = 16 * 1024


# ------------------------------------------------------------------ parsing

def _valid_ip(text: str) -> str | None:
    try:
        return str(ipaddress.ip_address(text))
    except ValueError:
        return None


def parse_message(msg: str) -> dict | None:
    """Classify one sshd message. Returns None for anything not monitored."""
    for kind, regex in (("failed", FAILED_RE), ("invalid_user", INVALID_RE), ("accepted", ACCEPTED_RE)):
        m = regex.match(msg)
        if not m:
            continue
        ip = _valid_ip(m.group("ip"))
        port = int(m.group("port"))
        if ip is None or not 0 < port < 65536:
            return None
        user = m.group("user")
        invalid = kind == "invalid_user" or bool(m.groupdict().get("invalid"))
        return {"kind": kind, "ip": ip, "port": port, "user": user, "invalid_user": invalid,
                "method": m.groupdict().get("method")}
    return None


def parse_syslog_ts(text: str, now: datetime) -> float | None:
    """RFC 3339 timestamps, or classic 'Mon DD HH:MM:SS' (local time, no year)."""
    try:
        if text[:4].isdigit():
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.astimezone()
            return dt.timestamp()
        local_now = now.astimezone()
        dt = datetime.strptime(f"{local_now.year} {text}", "%Y %b %d %H:%M:%S")
        dt = dt.replace(tzinfo=local_now.tzinfo)
        if dt > local_now + timedelta(days=1):  # December line read in January
            dt = dt.replace(year=dt.year - 1)
        return dt.timestamp()
    except ValueError:
        return None


def parse_syslog_line(line: str, now: datetime) -> dict | None:
    m = SYSLOG_RE.match(line)
    if not m:
        return None
    event = parse_message(m.group("msg"))
    if event is None:
        return None
    ts = parse_syslog_ts(m.group("ts"), now)
    if ts is None:
        return None
    event["ts"] = ts
    return event


# ------------------------------------------------------------------ sources

def read_file_source(path: str, cursor: dict | None, cfg: dict, now: datetime) -> tuple[list[dict], dict, dict]:
    """Read new lines since ``cursor``. Returns (events, new_cursor, status)."""
    status: dict[str, Any] = {"source": f"file:{path}", "status": "ok", "events": 0,
                              "truncated": False, "rotation_detected": False}
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        return [], cursor or {}, {**status, "status": "unavailable"}
    except PermissionError:
        return [], cursor or {}, {**status, "status": "permission_denied"}
    except OSError as exc:
        return [], cursor or {}, {**status, "status": f"error: {exc.strerror}"}
    with os.fdopen(fd, "rb") as fh:
        st = os.fstat(fh.fileno())
        offset = 0
        first_read = not cursor
        if cursor and cursor.get("inode") == st.st_ino and cursor.get("dev") == st.st_dev:
            offset = cursor.get("offset", 0)
            if offset > st.st_size:  # truncated in place (copytruncate)
                offset = 0
                status["rotation_detected"] = True
        elif cursor:
            status["rotation_detected"] = True
        limit = cfg["max_bytes_per_scan"]
        if st.st_size - offset > limit:
            offset = st.st_size - limit
            status["truncated"] = True
        fh.seek(offset)
        data = fh.read(limit)
    end = data.rfind(b"\n")
    if end < 0:
        return [], {"inode": st.st_ino, "dev": st.st_dev, "offset": offset}, status
    complete = data[: end + 1]
    new_offset = offset + end + 1
    lines = complete.split(b"\n")[:-1]
    if status["truncated"] and lines:
        lines = lines[1:]  # first line is probably partial
    cutoff = now.timestamp() - cfg["initial_lookback_seconds"] if first_read else None
    events = []
    for raw in lines:
        if len(raw) > MAX_LINE:
            continue
        event = parse_syslog_line(raw.decode("utf-8", "replace"), now)
        if event is None or (cutoff is not None and event["ts"] < cutoff):
            continue
        events.append(event)
    status["events"] = len(events)
    return events, {"inode": st.st_ino, "dev": st.st_dev, "offset": new_offset}, status


JournalRunner = Callable[[list[str], int, int], tuple[int, bytes, str]]


def run_command_bounded(argv: list[str], timeout_s: int, max_bytes: int) -> tuple[int, bytes, str]:
    """Run without a shell, minimal environment, bounded output and time."""
    env = {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "SYSTEMD_PAGER": "", "SYSTEMD_COLORS": "0"}
    with tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=err, stdin=subprocess.DEVNULL,
                                env=env, close_fds=True, bufsize=0)
        chunks: list[bytes] = []
        total = 0
        deadline = time.monotonic() + timeout_s
        assert proc.stdout is not None
        fd = proc.stdout.fileno()
        selector = selectors.DefaultSelector()
        selector.register(fd, selectors.EVENT_READ)
        try:
            while total < max_bytes:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise subprocess.TimeoutExpired(argv, timeout_s)
                chunk = os.read(fd, min(65536, max_bytes - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
        finally:
            selector.close()
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=5)
            proc.stdout.close()
        err.seek(0)
        stderr = err.read(4096).decode("utf-8", "replace")
    return proc.returncode, b"".join(chunks), stderr


JOURNAL_ROOTS = ("/var/log/journal", "/run/log/journal")


def journal_access(roots: tuple[str, ...] = JOURNAL_ROOTS) -> str:
    """'ok', 'unavailable' (no system journal files) or 'permission_denied'.

    Needed because ``journalctl --output=json`` exits 0 with empty stderr both
    when no journal exists and when the caller may read only its own user
    journal, which would otherwise look like "no SSH failures".
    """
    found = readable = False
    for root in roots:
        try:
            machines = os.listdir(root)
        except OSError:
            continue
        for machine in machines:
            try:
                names = os.listdir(os.path.join(root, machine))
            except PermissionError:
                found = True
                continue
            except OSError:
                continue
            for name in names:
                if name.startswith("system") and name.endswith(".journal"):
                    found = True
                    if os.access(os.path.join(root, machine, name), os.R_OK):
                        readable = True
    if readable:
        return "ok"
    return "permission_denied" if found else "unavailable"


def read_journal_source(cursor: dict | None, cfg: dict, now: datetime,
                        runner: JournalRunner = run_command_bounded,
                        roots: tuple[str, ...] = JOURNAL_ROOTS) -> tuple[list[dict], dict, dict]:
    status: dict[str, Any] = {"source": "journal", "status": "ok", "events": 0, "truncated": False}
    exe = shutil.which("journalctl", path="/usr/bin:/bin")
    if exe is None and runner is run_command_bounded:
        return [], cursor or {}, {**status, "status": "unavailable: journalctl not installed"}
    access = journal_access(roots)
    if access != "ok":
        detail = ("no system journal files" if access == "unavailable"
                  else "system journal not readable; add this user to systemd-journal or adm")
        return [], cursor or {}, {**status, "status": f"{access}: {detail}"}
    argv = [exe or "journalctl", "--no-pager", "--output=json"]
    if cursor and cursor.get("cursor"):
        argv.append(f"--after-cursor={cursor['cursor']}")
    else:
        argv.append(f"--since=@{int(now.timestamp()) - cfg['initial_lookback_seconds']}")
    argv += [f"SYSLOG_IDENTIFIER={ident}" for ident in SSH_IDENTIFIERS]
    try:
        code, out, err = runner(argv, cfg["journal_timeout_seconds"], cfg["max_bytes_per_scan"])
    except subprocess.TimeoutExpired:
        return [], cursor or {}, {**status, "status": "timeout"}
    except OSError as exc:
        return [], cursor or {}, {**status, "status": f"error: {exc.strerror}"}
    if code not in (0, None) and not out:
        lowered = err.lower()
        state = "permission_denied" if "permission" in lowered or "insufficient" in lowered else f"error: exit {code}"
        return [], cursor or {}, {**status, "status": state}
    if len(out) >= cfg["max_bytes_per_scan"]:
        status["truncated"] = True
    events: list[dict] = []
    new_cursor = dict(cursor or {})
    for raw in out.split(b"\n"):
        if not raw.strip() or len(raw) > MAX_LINE * 4:
            continue
        try:
            entry = json.loads(raw)
        except ValueError:
            continue  # "-- cursor: ..." trailer or a truncated final line
        if not isinstance(entry, dict):
            continue
        if isinstance(entry.get("__CURSOR"), str):
            new_cursor["cursor"] = entry["__CURSOR"]
        msg = entry.get("MESSAGE")
        if isinstance(msg, list):  # journald encodes non-UTF-8 messages as byte arrays
            msg = bytes(b & 0xFF for b in msg if isinstance(b, int)).decode("utf-8", "replace")
        if not isinstance(msg, str) or entry.get("SYSLOG_IDENTIFIER") not in SSH_IDENTIFIERS:
            continue
        event = parse_message(msg)
        if event is None:
            continue
        try:
            event["ts"] = int(entry["__REALTIME_TIMESTAMP"]) / 1_000_000
        except (KeyError, ValueError, TypeError):
            continue
        events.append(event)
    status["events"] = len(events)
    return events, new_cursor, status


def gather(cfg: dict, cursors: dict, now: datetime, runner: JournalRunner = run_command_bounded,
           roots: tuple[str, ...] = JOURNAL_ROOTS) -> tuple[list[dict], dict, list[dict]]:
    """Collect events from configured sources. 'auto' = first existing log file, else journal."""
    sources: list[str] = []
    for src in cfg["sources"]:
        if src == "auto":
            existing = [f for f in DEFAULT_FILES if os.path.exists(f)]
            sources.append(f"file:{existing[0]}" if existing else "journal")
        else:
            sources.append(src)
    events: list[dict] = []
    new_cursors = dict(cursors)
    statuses = []
    for src in dict.fromkeys(sources):
        if src == "journal":
            ev, cur, st = read_journal_source(cursors.get(src), cfg, now, runner, roots)
        else:
            ev, cur, st = read_file_source(src[len("file:"):], cursors.get(src), cfg, now)
        events.extend(ev)
        new_cursors[src] = cur
        statuses.append(st)
    events.sort(key=lambda e: e["ts"])
    return events, new_cursors, statuses


# ------------------------------------------------------------------ analysis

def _account_exists(name: str) -> bool:
    try:
        pwd.getpwnam(name)
        return True
    except (KeyError, ValueError, OSError):
        return False


def analyze(events: Iterable[dict], memory: dict, cfg: dict, now: datetime,
            account_exists: Callable[[str], bool] = _account_exists) -> list[dict]:
    """Apply sliding-window thresholds. ``memory`` (from state) is updated in place.

    memory = {"recent": {ip: [failure timestamps]}, "alerted": {ip: last alert ts}}
    """
    threshold, window = cfg["failure_threshold"], cfg["window_seconds"]
    recent: dict[str, list[float]] = memory.setdefault("recent", {})
    alerted: dict[str, float] = memory.setdefault("alerted", {})
    events = list(events)
    failed_conns = {(e["ip"], e["port"]) for e in events if e["kind"] == "failed"}
    detail: dict[str, dict[str, Any]] = {}
    findings: list[dict] = []

    for e in events:
        if e["kind"] == "invalid_user" and (e["ip"], e["port"]) in failed_conns:
            continue  # the "Failed ... invalid user" lines already count this connection
        if e["kind"] in ("failed", "invalid_user"):
            info = detail.setdefault(e["ip"], {"valid_users": set(), "invalid_attempts": 0,
                                               "invalid_names": set()})
            series = recent.setdefault(e["ip"], [])
            series.append(e["ts"])
            if e["invalid_user"]:
                info["invalid_attempts"] += 1
                if cfg["record_invalid_usernames"]:
                    info["invalid_names"].add(sanitize(e["user"], 64))
            elif account_exists(e["user"]):
                info["valid_users"].add(e["user"])
        elif e["kind"] == "accepted":
            prior = [t for t in recent.get(e["ip"], []) if e["ts"] - window <= t <= e["ts"]]
            if prior:
                findings.append({
                    "layer": "auth", "kind": "login_success_after_failures", "severity": "high",
                    "source_ip": e["ip"],
                    "detail": {"user": sanitize(e["user"], 64), "failures_in_window": len(prior),
                               "window_seconds": window, "at": _iso(e["ts"]),
                               "note": "suspicious; not proof of compromise. Confirm with the account owner."},
                })

    horizon = now.timestamp() - window
    for ip, series in list(recent.items()):
        series.sort()
        latest = series[-1] if series else 0
        in_window = [t for t in series if t >= latest - window]
        recent[ip] = [t for t in in_window if t >= horizon][-threshold * 2:]
        if not recent[ip]:
            del recent[ip]
        if ip in detail and len(in_window) >= threshold and alerted.get(ip, 0) < latest - window:
            alerted[ip] = latest
            info = detail[ip]
            payload: dict[str, Any] = {
                "failures_in_window": len(in_window), "threshold": threshold,
                "window_seconds": window, "first": _iso(in_window[0]), "last": _iso(latest),
                "existing_accounts_targeted": sorted(info["valid_users"])[:10],
                "invalid_user_attempts": info["invalid_attempts"],
                "note": "suspicious activity, not a confirmed intrusion",
            }
            if cfg["record_invalid_usernames"]:
                payload["invalid_usernames_sample"] = sorted(info["invalid_names"])[:5]
            findings.append({"layer": "auth", "kind": "repeated_auth_failures", "severity": "medium",
                             "source_ip": ip, "detail": payload})
    for ip, ts in list(alerted.items()):
        if ts < horizon - window:
            del alerted[ip]
    _cap(recent, cfg["max_tracked_sources"])
    return findings


def _cap(recent: dict[str, list[float]], limit: int) -> None:
    if len(recent) > limit:
        for ip in sorted(recent, key=lambda k: recent[k][-1])[: len(recent) - limit]:
            del recent[ip]


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


def source_findings(statuses: list[dict]) -> list[dict]:
    findings = []
    if not any(s["status"] == "ok" for s in statuses):
        findings.append({"layer": "auth", "kind": "auth_source_unavailable", "severity": "medium",
                         "source_ip": None,
                         "detail": {"sources": statuses,
                                    "note": "no authentication source could be read; zero failures "
                                            "means nothing here"}})
    for s in statuses:
        if s.get("truncated"):
            findings.append({"layer": "auth", "kind": "auth_read_truncated", "severity": "low",
                             "source_ip": None, "detail": {"source": s["source"]}})
    return findings
