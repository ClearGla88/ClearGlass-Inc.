"""Key rotation, retired keys and evidence-preserving purge (integration).

Threat: the HMAC key leaked, so the operator ran 'rotate --new-key'. Whoever
holds the old (now retired) key must not be able to forge state or records
written after that rotation. These tests were written first against
1.0.0.dev0, where every one of the forgeries below passed 'verify --all' and
a forged baseline hid a changed file from 'scan'."""

from __future__ import annotations

import hashlib
import os

from clearshield_core import audit
from clearshield_core.state import load_state, save_state


def _old_key_rotation(initialized, run) -> bytes:
    old = open(initialized.key, "rb").read()
    assert run("rotate", "--new-key")[0] == 0
    return old


def test_state_forged_with_retired_key_is_rejected(initialized, run):
    old = _old_key_rotation(initialized, run)
    ring = audit.load_keyring(initialized.state_dir)
    st = load_state(initialized.state_dir, ring)
    with open(initialized.watched, "w") as fh:
        fh.write("tampered\n")
    entry = st["baseline"]["files"][initialized.watched]
    entry["sha256"], entry["size"] = hashlib.sha256(b"tampered\n").hexdigest(), 9
    save_state(initialized.state_dir, audit.Keyring(old, {}), st)  # baseline poisoned with the old key
    code, _, err = run("scan")
    assert code == 3 and "retired key" in err
    code, out, _ = run("verify", "--all")
    assert code == 3 and "retired key" in out


def test_record_forged_with_retired_key_in_active_segment_is_rejected(initialized, run):
    old = _old_key_rotation(initialized, run)
    last = audit.read_last_record(initialized.log)
    forged = audit.make_record(old, last["seq"] + 1, last["tag"], "scan", {"forged": True})
    with open(initialized.log, "ab") as fh:
        fh.write(audit.canonical(forged) + b"\n")
    code, out, _ = run("verify")
    assert code == 3 and "key id changes inside the segment" in out
    assert run("scan")[0] == 3


def test_whole_segment_forged_with_retired_key_fails_verify_all(initialized, run):
    old = _old_key_rotation(initialized, run)          # segment 2 uses the new key
    assert run("rotate")[0] == 0                       # segment 3 active, still the new key
    seg1 = audit.verify_file(audit.archive_path(initialized.state_dir, 1),
                             audit.load_keyring(initialized.state_dir))
    real2 = audit.verify_file(audit.archive_path(initialized.state_dir, 2),
                              audit.load_keyring(initialized.state_dir))
    # Rebuild segment 2 with the old key, keeping its seq, prev links and final tag position.
    prev, lines = seg1["last"]["tag"], []
    path2 = audit.archive_path(initialized.state_dir, 2)
    records = [audit.json.loads(raw) for _, raw, _ in audit.iter_lines(path2)]
    for rec in records:
        body = {k: rec[k] for k in ("seq", "type", "data", "ts")}
        new = audit.make_record(old, body["seq"], prev, body["type"], body["data"], body["ts"])
        lines.append(audit.canonical(new) + b"\n")
        prev = new["tag"]
    with open(path2, "wb") as fh:
        fh.write(b"".join(lines))
    assert real2["ok"]
    code, out, _ = run("verify", "--all")
    assert code == 3 and "earlier segment retired" in out


def test_key_swap_interrupted_after_retiring_old_key_is_completed(initialized, run):
    sd = initialized.state_dir
    ring = audit.load_keyring(sd)
    st = load_state(sd, ring)
    log = audit.AuditLog(sd, ring, st["audit_head"])
    log.append("segment_end", {"reason": "crash test", "new_key": True})
    st["audit_head"] = log.head
    save_state(sd, ring, st)
    os.makedirs(audit.archive_dir(sd), mode=0o700)
    os.replace(initialized.log, audit.archive_path(sd, 1))
    audit.rotate_key(sd, ring)  # crash here: state is still signed with the now-retired key
    code, out, _ = run("verify")
    assert code == 3 and "retired key" in out
    code, _, err = run("scan")
    assert code == 0 and "interrupted rotation" in err
    code, out, _ = run("verify", "--all")
    assert code == 0, out


def test_rotation_interrupted_before_key_swap_still_rotates_the_key(initialized, run):
    sd = initialized.state_dir
    ring = audit.load_keyring(sd)
    st = load_state(sd, ring)
    log = audit.AuditLog(sd, ring, st["audit_head"])
    log.append("segment_end", {"reason": "crash test", "new_key": True})
    st["audit_head"] = log.head
    save_state(sd, ring, st)
    os.makedirs(audit.archive_dir(sd), mode=0o700)
    os.replace(initialized.log, audit.archive_path(sd, 1))  # crash before the key was swapped
    code, _, err = run("scan")
    assert code == 0 and "interrupted rotation" in err
    assert audit.load_keyring(sd).active_kid != ring.active_kid
    code, out, _ = run("verify", "--all")
    assert code == 0, out


def test_half_finished_key_file_swap_is_promoted_by_a_writing_command(initialized, run):
    sd = initialized.state_dir
    nxt = audit.next_key_path(sd)
    os.replace(initialized.key, nxt)  # as if the crash came between the two renames
    code, _, err = run("verify")
    assert code == 2 and "interrupted" in err
    assert run("scan")[0] == 0
    assert os.path.isfile(initialized.key) and not os.path.lexists(nxt)


def test_retired_state_with_a_live_log_is_not_treated_as_recovery(initialized, run):
    old = _old_key_rotation(initialized, run)
    ring = audit.load_keyring(initialized.state_dir)
    save_state(initialized.state_dir, audit.Keyring(old, {}), load_state(initialized.state_dir, ring))
    assert run("watch")[0] == 3


def test_purge_refuses_a_segment_that_fails_verification(initialized, run):
    run("rotate")
    path = audit.archive_path(initialized.state_dir, 1)
    lines = open(path, "rb").read().splitlines(True)
    lines[1] = lines[1].replace(b'"initialized"', b'"initializeX"')
    with open(path, "wb") as fh:
        fh.write(b"".join(lines))
    code, _, err = run("purge", "--before-segment", "2", "--yes")
    assert code == 3 and "refusing to purge" in err
    assert os.path.isfile(path)  # the evidence is still there


def test_purge_records_key_succession_for_later_verification(initialized, run):
    run("rotate", "--new-key")
    run("rotate")
    assert run("purge", "--before-segment", "3", "--yes")[0] == 0
    st = load_state(initialized.state_dir, audit.load_keyring(initialized.state_dir))
    first = st["purged_segments"][0]
    assert first["new_key"] is True and len(first["kid"]) == 16
    code, out, _ = run("verify", "--all")
    assert code == 0, out
