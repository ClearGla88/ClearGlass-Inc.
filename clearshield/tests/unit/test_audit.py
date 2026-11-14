"""HMAC chain, canonical encoding, keys (unit).

These tests also pin down what the chain CANNOT detect, so the documentation
cannot drift into overclaiming."""

from __future__ import annotations

import json
import os

import pytest

from clearshield_core import audit
from clearshield_core.errors import IntegrityFailure, InsecurePermissions, KeyFileError


@pytest.fixture
def chain(tmp_path):
    sd = str(tmp_path / "s")
    os.mkdir(sd, 0o700)
    os.chmod(sd, 0o700)
    key = audit.generate_key(sd)
    ring = audit.Keyring(key, {})
    head = audit.AuditLog.start_segment(sd, ring, 1, None)
    log = audit.AuditLog(sd, ring, head)
    for i in range(5):
        log.append("event", {"i": i})
    return sd, ring, log


def lines(sd):
    with open(audit.log_path(sd), "rb") as fh:
        return fh.read().splitlines(keepends=True)


def write(sd, rows):
    with open(audit.log_path(sd), "wb") as fh:
        fh.writelines(rows)


def test_canonical_is_order_independent_and_rejects_nan():
    assert audit.canonical({"b": 1, "a": 2}) == audit.canonical({"a": 2, "b": 1}) == b'{"a":2,"b":1}'
    with pytest.raises(ValueError):
        audit.canonical({"x": float("-inf")})


def test_canonical_escapes_non_ascii():
    assert audit.canonical({"u": "café‮"}) == b'{"u":"caf\\u00e9\\u202e"}'


def test_valid_chain_verifies(chain):
    sd, ring, log = chain
    result = audit.verify_file(audit.log_path(sd), ring)
    assert result["ok"] and result["records"] == 6 and result["last"]["seq"] == 5


def test_modified_record_detected(chain):
    sd, ring, _ = chain
    rows = lines(sd)
    rec = json.loads(rows[2])
    rec["data"]["i"] = 999  # keep the old tag
    rows[2] = audit.canonical(rec) + b"\n"
    write(sd, rows)
    result = audit.verify_file(audit.log_path(sd), ring)
    assert not result["ok"] and result["error"]["line"] == 3
    assert "tag mismatch" in result["error"]["reason"]


def test_reordered_records_detected(chain):
    sd, ring, _ = chain
    rows = lines(sd)
    rows[2], rows[3] = rows[3], rows[2]
    write(sd, rows)
    result = audit.verify_file(audit.log_path(sd), ring)
    assert not result["ok"] and "sequence break" in result["error"]["reason"]


def test_deleted_middle_record_detected(chain):
    sd, ring, _ = chain
    rows = lines(sd)
    del rows[3]
    write(sd, rows)
    assert "sequence break" in audit.verify_file(audit.log_path(sd), ring)["error"]["reason"]


def test_replayed_record_detected(chain):
    sd, ring, _ = chain
    rows = lines(sd)
    rows.append(rows[2])
    write(sd, rows)
    assert "sequence break" in audit.verify_file(audit.log_path(sd), ring)["error"]["reason"]


def test_spliced_record_with_valid_tag_detected(chain, tmp_path):
    """A correctly tagged record from a different chain (same key) breaks 'prev'."""
    sd, ring, _ = chain
    rows = lines(sd)
    forged = audit.make_record(ring.active, 3, "f" * 64, "event", {"i": "spliced"})
    rows[3] = audit.canonical(forged) + b"\n"
    write(sd, rows)
    assert "chain break" in audit.verify_file(audit.log_path(sd), ring)["error"]["reason"]


def test_truncating_newest_records_is_NOT_detectable_from_the_log_alone(chain):
    """Documented limitation: the remaining prefix is a valid chain."""
    sd, ring, _ = chain
    write(sd, lines(sd)[:-2])
    result = audit.verify_file(audit.log_path(sd), ring)
    assert result["ok"] is True and result["last"]["seq"] == 3


def test_truncation_detected_against_recorded_head(chain):
    sd, ring, log = chain
    head = dict(log.head)
    write(sd, lines(sd)[:-2])
    with pytest.raises(IntegrityFailure, match="truncation, rollback, or tampering"):
        audit.reconcile_head(sd, ring, head)


def test_log_one_record_ahead_is_recovered(chain):
    sd, ring, log = chain
    head = dict(log.head)
    log.append("event", {"i": "uncommitted"})
    new_head, recovered = audit.reconcile_head(sd, ring, head)
    assert recovered and new_head["seq"] == head["seq"] + 1


def test_incomplete_final_line(chain):
    sd, ring, log = chain
    with open(audit.log_path(sd), "ab") as fh:
        fh.write(b'{"v":1,"seq"')
    assert audit.verify_file(audit.log_path(sd), ring)["error"]["reason"] == "incomplete final line"
    with pytest.raises(IntegrityFailure, match="incomplete line"):
        audit.reconcile_head(sd, ring, log.head)


def test_wrong_key_rejected(chain):
    sd, _, _ = chain
    other = audit.Keyring(os.urandom(32), {})
    reason = audit.verify_file(audit.log_path(sd), other)["error"]["reason"]
    assert "unknown key id" in reason


def test_same_kid_wrong_key_material_fails_tag(chain):
    sd, ring, _ = chain
    fake = audit.Keyring(os.urandom(32), {})
    fake.keys = {ring.active_kid: os.urandom(32)}
    assert "tag mismatch" in audit.verify_file(audit.log_path(sd), fake)["error"]["reason"]


def test_missing_key(chain):
    sd, _, _ = chain
    os.unlink(audit.active_key_path(sd))
    with pytest.raises(KeyFileError, match="not found"):
        audit.load_keyring(sd)


def test_short_key_rejected(chain):
    sd, _, _ = chain
    path = audit.active_key_path(sd)
    with open(path, "wb") as fh:
        fh.write(b"short")
    with pytest.raises(KeyFileError, match="expected 32"):
        audit.load_keyring(sd)


def test_group_readable_key_rejected(chain):
    sd, _, _ = chain
    os.chmod(audit.active_key_path(sd), 0o640)
    with pytest.raises(InsecurePermissions, match="chmod 600"):
        audit.load_keyring(sd)


def test_symlinked_key_rejected(chain, tmp_path):
    sd, _, _ = chain
    path = audit.active_key_path(sd)
    real = tmp_path / "elsewhere.key"
    os.replace(path, real)
    os.symlink(real, path)
    with pytest.raises(InsecurePermissions, match="symlink"):
        audit.load_keyring(sd)


def test_key_rotation_keeps_old_records_verifiable(chain):
    sd, ring, _ = chain
    new_ring = audit.rotate_key(sd, ring)
    assert new_ring.active_kid != ring.active_kid
    reloaded = audit.load_keyring(sd)
    assert audit.verify_file(audit.log_path(sd), reloaded)["ok"]


def test_key_id_does_not_contain_key_material(chain):
    _, ring, _ = chain
    assert ring.active.hex()[:16] != ring.active_kid and len(ring.active_kid) == 16


def test_checkpoint_parsing():
    head = {"segment": 1, "seq": 4, "tag": "a" * 64, "kid": "b" * 16}
    cp = audit.parse_checkpoint(json.dumps(audit.make_checkpoint(head, "host-a")).encode())
    assert cp["seq"] == 4 and cp["host"] == "host-a"
    with pytest.raises(Exception, match="not a ClearShield checkpoint"):
        audit.parse_checkpoint(b'{"seq": 1}')
    with pytest.raises(Exception, match="tag is malformed"):
        audit.parse_checkpoint(json.dumps({**cp, "tag": "zz"}).encode())
