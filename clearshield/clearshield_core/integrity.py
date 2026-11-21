"""Watched-file integrity: SHA-256 plus metadata, compared with an approved baseline.

Snapshot rules:
  * ``lstat`` first; a symlink is recorded as a symlink with its target and is
    never followed. Watch the target path itself if its content matters.
  * Only regular files are hashed. Directories, FIFOs, sockets and device files
    are recorded by type and metadata, never opened (a FIFO would block and a
    device such as /dev/zero would never end).
  * Regular files are opened with O_NOFOLLOW | O_NONBLOCK, then ``fstat`` on the
    open descriptor must match the ``lstat`` identity; otherwise the path was
    swapped between the two calls and the snapshot reports ``raced``.
  * Size is capped (``integrity.max_file_bytes``) and reads are chunked.

Limits (also in SECURITY.md): scans are periodic. A change made and reverted
between two scans is not seen. O_NOFOLLOW protects only the final path
component; a symlink swapped into a parent directory is followed. Root can
defeat all of this.
"""

from __future__ import annotations

import errno
import hashlib
import os
import stat
from typing import Any

_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_NONBLOCK", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
CHUNK = 1 << 20

SEVERITY = {
    "content_changed": "high",
    "missing": "high",
    "appeared": "high",
    "type_changed": "high",
    "symlink_target_changed": "high",
    "metadata_changed": "medium",
    "unreadable": "medium",
    "collection_error": "medium",
    "too_large": "medium",
    "replaced": "info",
    "not_in_baseline": "info",
    "removed_from_watch": "medium",
}


def _kind(mode: int) -> str:
    for test, name in (
        (stat.S_ISREG, "file"),
        (stat.S_ISDIR, "dir"),
        (stat.S_ISLNK, "symlink"),
        (stat.S_ISFIFO, "fifo"),
        (stat.S_ISSOCK, "socket"),
        (stat.S_ISCHR, "char_device"),
        (stat.S_ISBLK, "block_device"),
    ):
        if test(mode):
            return name
    return "unknown"


def _meta(st: os.stat_result) -> dict[str, Any]:
    return {
        "kind": _kind(st.st_mode),
        "mode": format(stat.S_IMODE(st.st_mode), "04o"),
        "uid": st.st_uid,
        "gid": st.st_gid,
        "size": st.st_size,
        "inode": st.st_ino,
        "dev": st.st_dev,
    }


def snapshot(path: str, max_bytes: int) -> dict[str, Any]:
    """Collect the current state of one watched path. Never raises for I/O errors."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return {"status": "missing"}
    except PermissionError:
        return {"status": "unreadable", "error": "permission denied on lstat"}
    except OSError as exc:
        return {"status": "error", "error": exc.strerror or str(exc)}

    snap: dict[str, Any] = {"status": "ok", **_meta(st)}
    if stat.S_ISLNK(st.st_mode):
        try:
            snap["target"] = os.readlink(path)
        except OSError as exc:
            return {**snap, "status": "error", "error": exc.strerror or str(exc)}
        return snap
    if not stat.S_ISREG(st.st_mode):
        return snap
    if st.st_size > max_bytes:
        return {**snap, "status": "too_large"}

    try:
        fd = os.open(path, _FLAGS)
    except PermissionError:
        return {**snap, "status": "unreadable", "error": "permission denied on open"}
    except FileNotFoundError:
        return {**snap, "status": "raced", "error": "removed during scan"}
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            return {**snap, "status": "raced", "error": "replaced by a symlink during scan"}
        return {**snap, "status": "error", "error": exc.strerror or str(exc)}
    try:
        fst = os.fstat(fd)
        if (fst.st_dev, fst.st_ino) != (st.st_dev, st.st_ino) or not stat.S_ISREG(fst.st_mode):
            return {**snap, "status": "raced", "error": "path replaced between lstat and open"}
        digest = hashlib.sha256()
        total = 0
        while True:
            try:
                chunk = os.read(fd, CHUNK)
            except OSError as exc:
                return {**snap, "status": "error", "error": exc.strerror or str(exc)}
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                return {**snap, "status": "too_large"}
            digest.update(chunk)
        after = os.fstat(fd)
        if after.st_size != fst.st_size or after.st_mtime_ns != fst.st_mtime_ns:
            return {**snap, "status": "raced", "error": "file changed while being read"}
    finally:
        os.close(fd)
    snap["sha256"] = digest.hexdigest()
    return snap


def snapshot_all(paths: list[str], max_bytes: int) -> dict[str, dict]:
    return {p: snapshot(p, max_bytes) for p in sorted(set(paths))}


def _finding(kind: str, path: str, **detail: Any) -> dict[str, Any]:
    return {"layer": "integrity", "kind": kind, "severity": SEVERITY[kind], "path": path,
            "detail": detail}


def compare_one(path: str, base: dict | None, cur: dict) -> list[dict]:
    """Findings for one path. Content changes are kept apart from collection errors."""
    if base is None:
        return [_finding("not_in_baseline", path, current_status=cur["status"])]

    b_status, c_status = base["status"], cur["status"]
    if c_status in ("unreadable", "error", "raced"):
        kind = "unreadable" if c_status == "unreadable" else "collection_error"
        return [_finding(kind, path, status=c_status, error=cur.get("error"))]
    if c_status == "too_large" or b_status == "too_large":
        if c_status == b_status == "too_large" and base.get("size") == cur.get("size"):
            return []
        return [_finding("too_large", path, baseline_status=b_status, current_status=c_status)]
    if b_status == "missing" and c_status == "missing":
        return []
    if c_status == "missing":
        return [_finding("missing", path)]
    if b_status == "missing":
        return [_finding("appeared", path, file_type=cur.get("kind"))]
    if b_status in ("unreadable", "error", "raced"):
        # The baseline itself is incomplete; report what can be said.
        return [_finding("collection_error", path, status=f"baseline was {b_status}")]

    if base.get("kind") != cur.get("kind"):
        return [_finding("type_changed", path, baseline=base.get("kind"), current=cur.get("kind"))]

    findings: list[dict] = []
    if cur["kind"] == "symlink" and base.get("target") != cur.get("target"):
        findings.append(_finding("symlink_target_changed", path,
                                 baseline=base.get("target"), current=cur.get("target")))
    if cur["kind"] == "file" and base.get("sha256") != cur.get("sha256"):
        findings.append(_finding("content_changed", path,
                                 baseline_sha256=base.get("sha256"), current_sha256=cur.get("sha256"),
                                 baseline_size=base.get("size"), current_size=cur.get("size")))
    changed = {f: {"baseline": base.get(f), "current": cur.get(f)}
               for f in ("mode", "uid", "gid") if base.get(f) != cur.get(f)}
    if changed:
        findings.append(_finding("metadata_changed", path, fields=changed))
    if not findings and (base.get("inode"), base.get("dev")) != (cur.get("inode"), cur.get("dev")):
        findings.append(_finding("replaced", path, note="same content and metadata, new inode"))
    return findings


def compare(baseline_files: dict[str, dict], watch: list[str], current: dict[str, dict]) -> list[dict]:
    findings: list[dict] = []
    for path in sorted(set(watch) | set(baseline_files)):
        if path not in watch:
            findings.append(_finding("removed_from_watch", path))
            continue
        findings.extend(compare_one(path, baseline_files.get(path), current[path]))
    return findings
