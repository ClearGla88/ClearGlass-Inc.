"""Watched-file snapshots and comparison (unit)."""

from __future__ import annotations

import hashlib
import os
import signal

import pytest

from clearshield_core import integrity

MAX = 1 << 20


def kinds(findings):
    return [f["kind"] for f in findings]


def snap(path):
    return integrity.snapshot(str(path), MAX)


def test_regular_file_hash_and_metadata(tmp_path):
    p = tmp_path / "a"
    p.write_bytes(b"content")
    s = snap(p)
    assert s["status"] == "ok" and s["kind"] == "file"
    assert s["sha256"] == hashlib.sha256(b"content").hexdigest()
    assert s["mode"] == format(os.stat(p).st_mode & 0o7777, "04o")


def test_unchanged_file_has_no_findings(tmp_path):
    p = tmp_path / "a"
    p.write_text("x")
    assert integrity.compare_one(str(p), snap(p), snap(p)) == []


def test_content_change(tmp_path):
    p = tmp_path / "a"
    p.write_text("x")
    base = snap(p)
    p.write_text("y")
    findings = integrity.compare_one(str(p), base, snap(p))
    assert kinds(findings) == ["content_changed"] and findings[0]["severity"] == "high"


def test_missing_file(tmp_path):
    p = tmp_path / "a"
    p.write_text("x")
    base = snap(p)
    p.unlink()
    assert kinds(integrity.compare_one(str(p), base, snap(p))) == ["missing"]


def test_still_missing_is_quiet_and_appearance_is_reported(tmp_path):
    p = tmp_path / "a"
    base = snap(p)
    assert integrity.compare_one(str(p), base, snap(p)) == []
    p.write_text("new")
    assert kinds(integrity.compare_one(str(p), base, snap(p))) == ["appeared"]


def test_unreadable_is_a_collection_error_not_a_change(tmp_path, monkeypatch):
    p = tmp_path / "a"
    p.write_text("x")
    base = snap(p)

    def denied(*a, **k):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(integrity.os, "open", denied)
    findings = integrity.compare_one(str(p), base, snap(p))
    assert kinds(findings) == ["unreadable"] and findings[0]["severity"] == "medium"


@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses file permission checks")
def test_unreadable_real_permissions(tmp_path):
    p = tmp_path / "a"
    p.write_text("x")
    base = snap(p)
    os.chmod(p, 0)
    try:
        assert kinds(integrity.compare_one(str(p), base, snap(p))) == ["unreadable"]
    finally:
        os.chmod(p, 0o600)


def test_permission_change_reported_as_metadata(tmp_path):
    p = tmp_path / "a"
    p.write_text("x")
    os.chmod(p, 0o644)
    base = snap(p)
    os.chmod(p, 0o666)
    findings = integrity.compare_one(str(p), base, snap(p))
    assert kinds(findings) == ["metadata_changed"]
    assert findings[0]["detail"]["fields"] == {"mode": {"baseline": "0644", "current": "0666"}}


def test_replaced_with_identical_content_is_info(tmp_path):
    p = tmp_path / "a"
    p.write_text("same")
    os.chmod(p, 0o644)
    base = snap(p)
    tmp = tmp_path / "a.new"
    tmp.write_text("same")
    os.chmod(tmp, 0o644)
    os.replace(tmp, p)
    findings = integrity.compare_one(str(p), base, snap(p))
    assert kinds(findings) == ["replaced"] and findings[0]["severity"] == "info"


def test_symlink_recorded_not_followed(tmp_path):
    target_a = tmp_path / "ta"
    target_a.write_text("A")
    target_b = tmp_path / "tb"
    target_b.write_text("B")
    link = tmp_path / "link"
    link.symlink_to(target_a)
    base = snap(link)
    assert base["kind"] == "symlink" and "sha256" not in base
    link.unlink()
    link.symlink_to(target_b)
    assert kinds(integrity.compare_one(str(link), base, snap(link))) == ["symlink_target_changed"]


def test_fifo_is_not_opened(tmp_path):
    fifo = tmp_path / "pipe"
    os.mkfifo(fifo)
    signal.alarm(5)  # fail instead of hanging if the FIFO were opened for reading
    try:
        s = snap(fifo)
    finally:
        signal.alarm(0)
    assert s["status"] == "ok" and s["kind"] == "fifo" and "sha256" not in s


def test_type_change_file_to_directory(tmp_path):
    p = tmp_path / "a"
    p.write_text("x")
    base = snap(p)
    p.unlink()
    p.mkdir()
    assert kinds(integrity.compare_one(str(p), base, snap(p))) == ["type_changed"]


def test_size_cap(tmp_path):
    p = tmp_path / "big"
    p.write_bytes(b"x" * 100)
    s = integrity.snapshot(str(p), 10)
    assert s["status"] == "too_large" and "sha256" not in s


def test_swap_between_lstat_and_open_is_detected(tmp_path, monkeypatch):
    p = tmp_path / "a"
    p.write_text("x")
    other = tmp_path / "other"
    other.write_text("attacker")
    real_open = os.open
    monkeypatch.setattr(integrity.os, "open", lambda path, flags: real_open(str(other), flags))
    s = snap(p)
    assert s["status"] == "raced"


def test_symlink_swapped_in_before_open_is_refused(tmp_path, monkeypatch):
    p = tmp_path / "a"
    p.write_text("x")
    real_lstat = os.lstat
    stat_before = real_lstat(p)

    def lstat_then_swap(path):
        result = stat_before
        p.unlink()
        p.symlink_to(tmp_path / "secret")
        return result

    (tmp_path / "secret").write_text("do not read")
    monkeypatch.setattr(integrity.os, "lstat", lstat_then_swap)
    s = snap(p)
    assert s["status"] == "raced" and "symlink" in s["error"]


def test_compare_reports_paths_removed_from_watch_and_new_paths(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.write_text("1")
    b.write_text("2")
    baseline = integrity.snapshot_all([str(a)], MAX)
    current = integrity.snapshot_all([str(b)], MAX)
    findings = integrity.compare(baseline, [str(b)], current)
    assert sorted(kinds(findings)) == ["not_in_baseline", "removed_from_watch"]
