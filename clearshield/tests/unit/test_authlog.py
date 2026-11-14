"""SSH authentication monitoring: parsing hostile input, windows, sources (unit)."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone

import pytest

from clearshield_core import authlog
from clearshield_core.config import default_config

NOW = datetime(2026, 11, 13, 12, 0, 0, tzinfo=timezone.utc)
T0 = NOW.timestamp() - 300


def cfg(**over):
    c = default_config()["auth"]
    c.update(over)
    return c


def fail(ip="203.0.113.9", ts=T0, port=50000, user="root", invalid=False):
    return {"kind": "failed", "ip": ip, "port": port, "user": user, "invalid_user": invalid, "ts": ts}


# ------------------------------------------------------------------ parsing

def test_parse_failed_password_valid_and_invalid_user():
    e = authlog.parse_message("Failed password for root from 203.0.113.9 port 50022 ssh2")
    assert e == {"kind": "failed", "ip": "203.0.113.9", "port": 50022, "user": "root",
                 "invalid_user": False, "method": "password"}
    e = authlog.parse_message("Failed password for invalid user admin from 2001:db8::7 port 4 ssh2")
    assert e["invalid_user"] and e["ip"] == "2001:db8::7" and e["user"] == "admin"


def test_parse_invalid_and_accepted():
    assert authlog.parse_message("Invalid user test from 198.51.100.4 port 1234")["kind"] == "invalid_user"
    e = authlog.parse_message("Accepted publickey for alice from 198.51.100.4 port 1234 ssh2")
    assert e["kind"] == "accepted" and e["method"] == "publickey"


def test_username_cannot_frame_another_address():
    msg = "Invalid user x from 10.0.0.5 port 22 from 203.0.113.9 port 51234"
    e = authlog.parse_message(msg)
    assert e["ip"] == "203.0.113.9" and e["user"] == "x from 10.0.0.5 port 22"


def test_garbage_address_is_rejected():
    assert authlog.parse_message("Failed password for root from 999.1.1.1 port 22 ssh2") is None
    assert authlog.parse_message("Failed password for root from 1.2.3.4 port 0 ssh2") is None
    assert authlog.parse_message("Connection closed by 1.2.3.4 port 22") is None


def test_syslog_line_formats():
    rfc = "2026-11-13T11:58:00.123456+00:00 host sshd[99]: Failed password for root from 203.0.113.9 port 5 ssh2"
    e = authlog.parse_syslog_line(rfc, NOW)
    assert e["ts"] == datetime(2026, 11, 13, 11, 58, 0, 123456, tzinfo=timezone.utc).timestamp()
    session = "2026-11-13T11:58:00Z host sshd-session[7]: Invalid user a from 203.0.113.9 port 6"
    assert authlog.parse_syslog_line(session, NOW)["kind"] == "invalid_user"
    assert authlog.parse_syslog_line("2026-11-13T11:58:00Z host cron[1]: Failed password for", NOW) is None


def test_classic_timestamp_year_rollover():
    jan2 = datetime(2027, 1, 2, 0, 0, 0, tzinfo=timezone.utc)
    ts = authlog.parse_syslog_ts("Dec 31 23:00:00", jan2)
    assert datetime.fromtimestamp(ts).year == 2026


# ------------------------------------------------------------------ analysis

def test_below_threshold_no_alert():
    mem: dict = {}
    events = [fail(ts=T0 + i) for i in range(9)]
    assert authlog.analyze(events, mem, cfg(), NOW, lambda u: True) == []


def test_threshold_reached_alerts_once():
    mem: dict = {}
    events = [fail(ts=T0 + i, port=50000 + i) for i in range(10)]
    findings = authlog.analyze(events, mem, cfg(), NOW, lambda u: True)
    assert [f["kind"] for f in findings] == ["repeated_auth_failures"]
    d = findings[0]["detail"]
    assert d["failures_in_window"] == 10 and d["existing_accounts_targeted"] == ["root"]
    assert "not a confirmed intrusion" in d["note"]
    more = [fail(ts=T0 + 20 + i, port=60000 + i) for i in range(10)]
    assert authlog.analyze(more, mem, cfg(), NOW, lambda u: True) == []  # same window: no repeat


def test_failures_spread_beyond_window_do_not_alert():
    events = [fail(ts=T0 - 3000 + i * 120, port=i) for i in range(10)]  # 10 failures over 18 min
    assert authlog.analyze(events, {}, cfg(window_seconds=600), NOW, lambda u: True) == []


def test_memory_carries_failures_between_scans():
    mem: dict = {}
    authlog.analyze([fail(ts=T0 + i, port=i) for i in range(6)], mem, cfg(), NOW, lambda u: True)
    findings = authlog.analyze([fail(ts=T0 + 10 + i, port=100 + i) for i in range(4)], mem, cfg(), NOW,
                               lambda u: True)
    assert findings and findings[0]["detail"]["failures_in_window"] == 10


def test_invalid_user_line_and_failed_line_for_same_connection_count_once():
    pair = [{"kind": "invalid_user", "ip": "203.0.113.9", "port": 7, "user": "zz", "invalid_user": True, "ts": T0},
            fail(ts=T0 + 1, port=7, user="zz", invalid=True)]
    mem: dict = {}
    authlog.analyze(pair, mem, cfg(), NOW, lambda u: False)
    assert len(mem["recent"]["203.0.113.9"]) == 1


def test_invalid_user_without_failed_line_counts():
    events = [{"kind": "invalid_user", "ip": "203.0.113.9", "port": i, "user": "u", "invalid_user": True,
               "ts": T0 + i} for i in range(10)]
    findings = authlog.analyze(events, {}, cfg(), NOW, lambda u: False)
    assert findings[0]["detail"]["invalid_user_attempts"] == 10


def test_success_after_failures_is_high_but_not_proof():
    events = [fail(ts=T0 + i, port=i) for i in range(3)]
    events.append({"kind": "accepted", "ip": "203.0.113.9", "port": 99, "user": "root",
                   "invalid_user": False, "ts": T0 + 10})
    findings = authlog.analyze(events, {}, cfg(), NOW, lambda u: True)
    assert [f["kind"] for f in findings] == ["login_success_after_failures"]
    assert findings[0]["severity"] == "high" and "not proof" in findings[0]["detail"]["note"]


def test_attempted_invalid_usernames_not_stored_by_default():
    secret = "hunter2-typed-into-username"
    events = [fail(ts=T0 + i, port=i, user=secret, invalid=True) for i in range(10)]
    findings = authlog.analyze(events, {}, cfg(), NOW, lambda u: False)
    assert secret not in json.dumps(findings)


def test_invalid_usernames_stored_sanitized_when_opted_in():
    hostile = "\x1b[31mevil\x1b[0m"
    events = [fail(ts=T0 + i, port=i, user=hostile, invalid=True) for i in range(10)]
    findings = authlog.analyze(events, {}, cfg(record_invalid_usernames=True), NOW, lambda u: False)
    sample = findings[0]["detail"]["invalid_usernames_sample"]
    assert sample == ["\\x1b[31mevil\\x1b[0m"]


def test_nonexistent_account_names_not_recorded_even_if_sshd_says_valid():
    events = [fail(ts=T0 + i, port=i, user="ghost") for i in range(10)]
    findings = authlog.analyze(events, {}, cfg(), NOW, lambda u: False)
    assert findings[0]["detail"]["existing_accounts_targeted"] == []


def test_tracked_sources_are_capped():
    mem: dict = {}
    events = [fail(ip=f"198.51.100.{i}", ts=T0 + i, port=i) for i in range(50)]
    authlog.analyze(events, mem, cfg(max_tracked_sources=10), NOW, lambda u: True)
    assert len(mem["recent"]) == 10


# ------------------------------------------------------------------ file source

def line(ts, msg):
    return f"{ts} host sshd[1]: {msg}\n"


def test_file_source_reads_incrementally_and_detects_rotation(tmp_path):
    log = tmp_path / "auth.log"
    log.write_text(line("2026-11-13T11:59:00Z", "Failed password for root from 203.0.113.9 port 1 ssh2"))
    ev, cur, st = authlog.read_file_source(str(log), None, cfg(), NOW)
    assert len(ev) == 1 and st["status"] == "ok"
    with open(log, "a") as fh:
        fh.write(line("2026-11-13T11:59:30Z", "Failed password for root from 203.0.113.9 port 2 ssh2"))
        fh.write("2026-11-13T11:59:31Z host sshd[1]: partial line without newl")
    ev, cur, st = authlog.read_file_source(str(log), cur, cfg(), NOW)
    assert [e["port"] for e in ev] == [2]  # only the new complete line
    rotated = tmp_path / "auth.log.new"
    rotated.write_text(line("2026-11-13T11:59:40Z", "Invalid user q from 203.0.113.9 port 3"))
    os.replace(rotated, log)
    ev, cur, st = authlog.read_file_source(str(log), cur, cfg(), NOW)
    assert st["rotation_detected"] and [e["port"] for e in ev] == [3]


def test_file_source_first_read_respects_lookback(tmp_path):
    log = tmp_path / "auth.log"
    log.write_text(line("2026-11-12T00:00:00Z", "Failed password for root from 203.0.113.9 port 1 ssh2")
                   + line("2026-11-13T11:59:00Z", "Failed password for root from 203.0.113.9 port 2 ssh2"))
    ev, _, _ = authlog.read_file_source(str(log), None, cfg(), NOW)
    assert [e["port"] for e in ev] == [2]


def test_file_source_byte_cap(tmp_path):
    log = tmp_path / "auth.log"
    log.write_text("".join(line("2026-11-13T11:59:00Z", f"Failed password for root from 203.0.113.9 port {i} ssh2")
                           for i in range(1, 200)))
    ev, _, st = authlog.read_file_source(str(log), None, cfg(max_bytes_per_scan=1024), NOW)
    assert st["truncated"] and 0 < len(ev) < 20


def test_missing_file_source_is_reported(tmp_path):
    _, _, st = authlog.read_file_source(str(tmp_path / "none"), None, cfg(), NOW)
    assert st["status"] == "unavailable"
    assert [f["kind"] for f in authlog.source_findings([st])] == ["auth_source_unavailable"]


# ------------------------------------------------------------------ journal source

def journal_roots(tmp_path, readable=True):
    d = tmp_path / "journal" / "machineid"
    d.mkdir(parents=True)
    (d / "system.journal").write_bytes(b"")
    return (str(tmp_path / "journal"),)


def test_journal_source_parses_json_and_resumes_from_cursor(tmp_path):
    entries = [
        {"__CURSOR": "c1", "__REALTIME_TIMESTAMP": str(int(T0 * 1e6)), "SYSLOG_IDENTIFIER": "sshd",
         "MESSAGE": "Failed password for root from 203.0.113.9 port 9 ssh2"},
        {"__CURSOR": "c2", "__REALTIME_TIMESTAMP": str(int(T0 * 1e6) + 1), "SYSLOG_IDENTIFIER": "sshd-session",
         "MESSAGE": list(b"Invalid user b from 203.0.113.9 port 10")},
        {"__CURSOR": "c3", "__REALTIME_TIMESTAMP": "1", "SYSLOG_IDENTIFIER": "cron",
         "MESSAGE": "Failed password for root from 203.0.113.9 port 11 ssh2"},
    ]
    calls = []

    def runner(argv, timeout, max_bytes):
        calls.append(argv)
        return 0, "\n".join(json.dumps(e) for e in entries).encode(), ""

    roots = journal_roots(tmp_path)
    ev, cur, st = authlog.read_journal_source(None, cfg(), NOW, runner, roots)
    assert [e["port"] for e in ev] == [9, 10] and cur["cursor"] == "c3" and st["status"] == "ok"
    assert any(a.startswith("--since=@") for a in calls[0])
    assert "SYSLOG_IDENTIFIER=sshd" in calls[0] and "SYSLOG_IDENTIFIER=sshd-session" in calls[0]
    authlog.read_journal_source(cur, cfg(), NOW, runner, roots)
    assert "--after-cursor=c3" in calls[1]
    assert not any("shell" in str(a) for a in calls[0])


def test_journal_without_files_is_unavailable_not_zero_failures(tmp_path):
    _, _, st = authlog.read_journal_source(None, cfg(), NOW, lambda *a: (0, b"", ""),
                                           (str(tmp_path / "empty"),))
    assert st["status"].startswith("unavailable")


def test_journal_unreadable_is_permission_denied(tmp_path, monkeypatch):
    roots = journal_roots(tmp_path)
    monkeypatch.setattr(authlog.os, "access", lambda *a: False)
    _, _, st = authlog.read_journal_source(None, cfg(), NOW, lambda *a: (0, b"", ""), roots)
    assert st["status"].startswith("permission_denied")


def test_journal_timeout(tmp_path):
    def runner(*a):
        raise subprocess.TimeoutExpired("journalctl", 1)

    _, _, st = authlog.read_journal_source(None, cfg(), NOW, runner, journal_roots(tmp_path))
    assert st["status"] == "timeout"


# ------------------------------------------------------------------ bounded subprocess

def test_bounded_runner_enforces_timeout_on_silent_process():
    with pytest.raises(subprocess.TimeoutExpired):
        authlog.run_command_bounded(["/bin/sleep", "10"], 1, 1024)


def test_bounded_runner_caps_output():
    code, out, _ = authlog.run_command_bounded(["/usr/bin/yes"], 10, 4096)
    assert len(out) == 4096


def test_bounded_runner_uses_minimal_environment(monkeypatch):
    monkeypatch.setenv("CLEARSHIELD_SECRET_PROBE", "leak")
    _, out, _ = authlog.run_command_bounded(["/usr/bin/env"], 5, 65536)
    assert b"CLEARSHIELD_SECRET_PROBE" not in out and b"LC_ALL=C" in out
