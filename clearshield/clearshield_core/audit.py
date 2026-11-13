"""Tamper-evident audit log: HMAC-SHA256 chained JSON lines.

Record layout (one JSON object per line, canonical encoding)::

    {"v":1,"seq":N,"ts":"...","type":"...","data":{...},"prev":"<tag of seq N-1>",
     "kid":"<key id>","tag":"<HMAC-SHA256 over every other field>"}

What the chain detects, given the key is secret:
  * a modified record (tag mismatch);
  * a deleted, inserted, duplicated (replayed) or reordered record
    (sequence gap or ``prev`` mismatch).

What it cannot detect on its own:
  * removal of the newest records (the remaining prefix is still a valid chain);
  * replacement of the whole log and state with an older, self-consistent copy;
  * anything done by someone who holds the key (the monitoring user or root).

The first two are caught only by comparing against a head recorded somewhere
the attacker cannot rewrite: the state file (weak: same directory) or an
exported checkpoint stored off the host (``checkpoint`` / ``verify --checkpoint``).

An HMAC tag is a shared-secret authenticator, not a digital signature: anyone
who can verify a tag can also forge one. See SECURITY.md.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
from datetime import datetime, timezone
from typing import Any, Iterator

from . import fsutil
from .errors import ClearShieldError, IntegrityFailure, KeyFileError

RECORD_VERSION = 1
GENESIS = "0" * 64
KEY_BYTES = 32
MAX_LINE_BYTES = 256 * 1024
REQUIRED_FIELDS = ("v", "seq", "ts", "type", "data", "prev", "kid", "tag")
_KID_RE = re.compile(r"\A[0-9a-f]{16}\Z")
_TAG_RE = re.compile(r"\A[0-9a-f]{64}\Z")


def canonical(obj: Any) -> bytes:
    """Deterministic JSON bytes: sorted keys, no whitespace, ASCII, no NaN/Infinity."""
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("ascii")


def compute_tag(key: bytes, obj: Any) -> str:
    return hmac.new(key, canonical(obj), hashlib.sha256).hexdigest()


def key_id(key: bytes) -> str:
    """Public identifier for a key. Derived with HMAC, so it reveals nothing about the key."""
    return hmac.new(key, b"clearshield-key-id-v1", hashlib.sha256).hexdigest()[:16]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- keys


class Keyring:
    """Active key plus retired keys, addressed by key id."""

    def __init__(self, active: bytes, retired: dict[str, bytes]) -> None:
        self.active = active
        self.active_kid = key_id(active)
        self.keys = dict(retired)
        self.keys[self.active_kid] = active

    def get(self, kid: str) -> bytes | None:
        return self.keys.get(kid)


def keys_dir(state_dir: str) -> str:
    return os.path.join(state_dir, "keys")


def active_key_path(state_dir: str) -> str:
    return os.path.join(keys_dir(state_dir), "hmac.key")


def retired_dir(state_dir: str) -> str:
    return os.path.join(keys_dir(state_dir), "retired")


def generate_key(state_dir: str) -> bytes:
    fsutil.make_private_dir(keys_dir(state_dir))
    key = secrets.token_bytes(KEY_BYTES)
    fsutil.create_exclusive(active_key_path(state_dir), key, 0o600)
    return key


def _read_key(path: str) -> bytes:
    try:
        data = fsutil.read_private_file(path, KEY_BYTES)
    except FileNotFoundError:
        raise KeyFileError(
            f"HMAC key not found at {path}. Without it, records cannot be verified or added."
        ) from None
    if len(data) != KEY_BYTES:
        raise KeyFileError(f"HMAC key at {path} is {len(data)} bytes; expected {KEY_BYTES}.")
    return data


def load_keyring(state_dir: str) -> Keyring:
    fsutil.check_private_dir(keys_dir(state_dir))
    active = _read_key(active_key_path(state_dir))
    retired: dict[str, bytes] = {}
    rdir = retired_dir(state_dir)
    if os.path.lexists(rdir):
        fsutil.check_private_dir(rdir)
        for name in sorted(os.listdir(rdir)):
            if name.endswith(".key"):
                key = _read_key(os.path.join(rdir, name))
                retired[key_id(key)] = key
    return Keyring(active, retired)


def rotate_key(state_dir: str, keyring: Keyring) -> Keyring:
    """Retire the active key (kept for verifying old segments) and create a new one."""
    rdir = retired_dir(state_dir)
    fsutil.make_private_dir(rdir)
    old_path = active_key_path(state_dir)
    os.replace(old_path, os.path.join(rdir, f"{keyring.active_kid}.key"))
    fsutil.fsync_dir(rdir)
    fsutil.fsync_dir(keys_dir(state_dir))
    new = secrets.token_bytes(KEY_BYTES)
    fsutil.create_exclusive(old_path, new, 0o600)
    retired = {k: v for k, v in keyring.keys.items()}
    return Keyring(new, retired)


# ------------------------------------------------------------------------ records


def make_record(
    key: bytes, seq: int, prev: str, rtype: str, data: dict, ts: str | None = None
) -> dict:
    body = {
        "v": RECORD_VERSION,
        "seq": seq,
        "ts": ts or utc_now(),
        "type": rtype,
        "data": data,
        "prev": prev,
        "kid": key_id(key),
    }
    body["tag"] = compute_tag(key, body)
    return body


def check_record_tag(keyring: Keyring, record: dict) -> str | None:
    """Return None if the record authenticates, else a reason string."""
    for field in REQUIRED_FIELDS:
        if field not in record:
            return f"missing field '{field}'"
    if record["v"] != RECORD_VERSION:
        return f"unsupported record version {record['v']!r}"
    if not isinstance(record["seq"], int) or isinstance(record["seq"], bool):
        return "seq is not an integer"
    if not isinstance(record["kid"], str) or not _KID_RE.match(record["kid"]):
        return "malformed key id"
    if not isinstance(record["tag"], str) or not _TAG_RE.match(record["tag"]):
        return "malformed tag"
    key = keyring.get(record["kid"])
    if key is None:
        return f"unknown key id {record['kid']} (key missing or wrong key loaded)"
    body = {k: v for k, v in record.items() if k != "tag"}
    if not hmac.compare_digest(compute_tag(key, body), record["tag"]):
        return "authentication tag mismatch (record modified or wrong key)"
    return None


# ---------------------------------------------------------------------- log files


def log_path(state_dir: str) -> str:
    return os.path.join(state_dir, "audit.jsonl")


def archive_dir(state_dir: str) -> str:
    return os.path.join(state_dir, "archive")


def archive_path(state_dir: str, segment: int) -> str:
    return os.path.join(archive_dir(state_dir), f"audit-{segment:06d}.jsonl")


def iter_lines(path: str) -> Iterator[tuple[int, bytes, bool]]:
    """Yield (line_number, raw_line_without_newline, complete) with a per-line size cap."""
    with open(path, "rb") as fh:
        number = 0
        while True:
            raw = fh.readline(MAX_LINE_BYTES + 1)
            if not raw:
                return
            number += 1
            complete = raw.endswith(b"\n")
            if not complete and len(raw) > MAX_LINE_BYTES:
                yield number, b"", False
                return
            yield number, raw.rstrip(b"\n"), complete


def read_last_record(path: str) -> dict:
    """Read and parse the final line of a log file (tail read, bounded)."""
    try:
        size = os.path.getsize(path)
    except FileNotFoundError:
        raise IntegrityFailure(f"audit log {path} is missing.") from None
    if size == 0:
        raise IntegrityFailure(f"audit log {path} is empty.")
    with open(path, "rb") as fh:
        start = max(0, size - MAX_LINE_BYTES - 1)
        fh.seek(start)
        tail = fh.read()
    if not tail.endswith(b"\n"):
        raise IntegrityFailure(
            f"audit log {path} ends with an incomplete line (interrupted write or tampering). "
            "Run 'verify' and see README troubleshooting."
        )
    last = tail[:-1].rsplit(b"\n", 1)[-1]
    try:
        record = json.loads(last)
    except ValueError:
        raise IntegrityFailure(f"final record of {path} is not valid JSON.") from None
    if not isinstance(record, dict):
        raise IntegrityFailure(f"final record of {path} is not a JSON object.")
    return record


def verify_file(path: str, keyring: Keyring, expect_prev: str | None = None) -> dict:
    """Verify one segment file. Stops at the first failure.

    Returns {"ok", "records", "first", "last", "error": {"line","reason"} | None}.
    """
    result: dict[str, Any] = {"ok": False, "records": 0, "first": None, "last": None, "error": None}
    prev_tag: str | None = expect_prev
    prev_seq: int | None = None
    if not os.path.isfile(path):
        result["error"] = {"line": 0, "reason": "file missing"}
        return result
    for number, raw, complete in iter_lines(path):
        if not complete:
            reason = "line exceeds size limit" if not raw else "incomplete final line"
            result["error"] = {"line": number, "reason": reason}
            return result
        try:
            record = json.loads(raw)
        except ValueError:
            result["error"] = {"line": number, "reason": "invalid JSON"}
            return result
        if not isinstance(record, dict):
            result["error"] = {"line": number, "reason": "record is not a JSON object"}
            return result
        problem = check_record_tag(keyring, record)
        if problem:
            result["error"] = {"line": number, "reason": problem}
            return result
        if prev_seq is None:
            if record["seq"] != 0 or record["type"] != "segment_start":
                result["error"] = {
                    "line": number,
                    "reason": "segment does not begin with a segment_start record at seq 0",
                }
                return result
        elif record["seq"] != prev_seq + 1:
            result["error"] = {
                "line": number,
                "reason": f"sequence break: expected seq {prev_seq + 1}, found {record['seq']} "
                "(records deleted, inserted, replayed, or reordered)",
            }
            return result
        if prev_tag is not None and record["prev"] != prev_tag:
            result["error"] = {
                "line": number,
                "reason": "chain break: prev does not match the preceding record's tag",
            }
            return result
        prev_seq = record["seq"]
        prev_tag = record["tag"]
        result["records"] += 1
        if result["first"] is None:
            result["first"] = record
        result["last"] = record
    if result["records"] == 0:
        result["error"] = {"line": 0, "reason": "file is empty"}
        return result
    result["ok"] = True
    return result


def head_of(record: dict, segment: int) -> dict:
    return {"segment": segment, "seq": record["seq"], "tag": record["tag"], "kid": record["kid"]}


class AuditLog:
    """Append-only writer for the active segment."""

    def __init__(self, state_dir: str, keyring: Keyring, head: dict) -> None:
        self.state_dir = state_dir
        self.keyring = keyring
        self.head = dict(head)
        self.path = log_path(state_dir)

    def append(self, rtype: str, data: dict) -> dict:
        record = make_record(
            self.keyring.active, self.head["seq"] + 1, self.head["tag"], rtype, data
        )
        fsutil.append_line(self.path, canonical(record) + b"\n")
        self.head = head_of(record, self.head["segment"])
        return record

    @staticmethod
    def start_segment(
        state_dir: str, keyring: Keyring, segment: int, previous: dict | None
    ) -> dict:
        prev = previous["tag"] if previous else GENESIS
        record = make_record(
            keyring.active, 0, prev, "segment_start", {"segment": segment, "previous": previous}
        )
        path = log_path(state_dir)
        if os.path.lexists(path):
            raise ClearShieldError(f"{path} already exists; refusing to overwrite it.")
        fsutil.append_line(path, canonical(record) + b"\n")
        fsutil.fsync_dir(state_dir)
        return head_of(record, segment)


def reconcile_head(state_dir: str, keyring: Keyring, state_head: dict) -> tuple[dict, bool]:
    """Compare the log's final record with the head stored in state.

    Returns (head, recovered). ``recovered`` is True when the log is exactly one
    valid record ahead of state, which happens if a command was interrupted
    between appending to the log and saving state.
    """
    last = read_last_record(log_path(state_dir))
    problem = check_record_tag(keyring, last)
    if problem:
        raise IntegrityFailure(f"final audit record failed verification: {problem}. Run 'verify'.")
    segment = state_head["segment"]
    if last["seq"] == state_head["seq"] and hmac.compare_digest(last["tag"], state_head["tag"]):
        return head_of(last, segment), False
    if last["seq"] == state_head["seq"] + 1 and hmac.compare_digest(
        last["prev"], state_head["tag"]
    ):
        return head_of(last, segment), True
    raise IntegrityFailure(
        f"audit log ends at seq {last['seq']} but state records seq {state_head['seq']}: "
        "possible truncation, rollback, or tampering. Run 'verify' before continuing."
    )


# --------------------------------------------------------------------- checkpoints


def make_checkpoint(head: dict, host_label: str | None = None) -> dict:
    cp = {
        "clearshield_checkpoint": 1,
        "segment": head["segment"],
        "seq": head["seq"],
        "tag": head["tag"],
        "kid": head["kid"],
        "exported_at": utc_now(),
    }
    if host_label:
        cp["host"] = host_label
    return cp


def parse_checkpoint(raw: bytes) -> dict:
    try:
        cp = json.loads(raw)
    except ValueError:
        raise ClearShieldError("checkpoint file is not valid JSON.") from None
    if not isinstance(cp, dict) or cp.get("clearshield_checkpoint") != 1:
        raise ClearShieldError("not a ClearShield checkpoint file.")
    for field in ("segment", "seq"):
        if not isinstance(cp.get(field), int) or isinstance(cp.get(field), bool):
            raise ClearShieldError(f"checkpoint field '{field}' must be an integer.")
    if not isinstance(cp.get("tag"), str) or not _TAG_RE.match(cp["tag"]):
        raise ClearShieldError("checkpoint tag is malformed.")
    return cp
