"""End-to-end command behaviour against temporary state directories (integration).

Commands run in-process through cli.main so monkeypatching can simulate
permission failures and a microphone; test_entrypoint.py runs the real script."""

from __future__ import annotations

import json
import os
import shutil
import socket

import pytest

from clearshield_core import audit, cli, integrity
from clearshield_core.state import load_state
from cs_testlib import set_config, tone


def kinds(out):
    return [f["kind"] for f in json.loads(out)["findings"]]


def tree(root):
    out = {}
    for base, _, files in os.walk(root):
        for name in files:
            p = os.path.join(base, name)
            out[p] = os.path.getsize(p)
    return out


# ------------------------------------------------------------------ baseline / scan

def test_unchanged_scan_exits_zero(initialized, run):
    code, out, _ = run("scan")
    assert code == 0 and "Detection only" in out


def test_changed_missing_and_metadata_findings(initialized, run):
    with open(initialized.watched, "a") as fh:
        fh.write("tampered\n")
    code, out, _ = run("scan", "--json")
    assert code == 1 and kinds(out) == ["content_changed"]
    os.unlink(initialized.watched)
    code, out, _ = run("scan", "--json")
    assert code == 1 and kinds(out) == ["missing"]


def test_unreadable_is_reported_as_collection_problem(initialized, run, monkeypatch):
    real_open = os.open

    def deny_watched(path, flags, *rest):
        if os.fspath(path) == initialized.watched:
            raise PermissionError(13, "Permission denied")
        return real_open(path, flags, *rest)

    monkeypatch.setattr(integrity.os, "open", deny_watched)  # integrity.os is the global os module
    code, out, _ = run("scan", "--json")
    assert code == 1 and kinds(out) == ["unreadable"]


def test_scan_requires_baseline(state_dir, run, tmp_path):
    run("init", "--watch", str(tmp_path))
    code, _, err = run("scan")
    assert code == 2 and "no approved baseline" in err


def test_baseline_replacement_controls(initialized, run):
    first = load_state(initialized.state_dir, audit.load_keyring(initialized.state_dir))["baseline"]["id"]
    code, _, err = run("baseline")
    assert code == 2 and "baseline --replace" in err
    with open(initialized.watched, "a") as fh:
        fh.write("changed\n")
    code, out, err = run("baseline", "--replace")  # stdin is not a TTY under pytest
    assert code == 2 and "re-run with --yes" in err and "content_changed" in out
    st = load_state(initialized.state_dir, audit.load_keyring(initialized.state_dir))
    assert st["baseline"]["id"] == first
    code, out, _ = run("baseline", "--replace", "--yes", "--json")
    assert code == 0 and json.loads(out)["replaced"] == first
    st = load_state(initialized.state_dir, audit.load_keyring(initialized.state_dir))
    assert st["previous_baseline"]["id"] == first and st["baseline"]["id"] != first
    assert run("scan")[0] == 0


def test_watch_add_remove_flow(initialized, run, tmp_path):
    extra = tmp_path / "extra.conf"
    extra.write_text("x")
    run("watch", "--add", str(extra))
    code, out, _ = run("scan", "--json")
    assert "not_in_baseline" in kinds(out) and code == 0  # info only
    run("watch", "--remove", initialized.watched)
    code, out, _ = run("scan", "--json")
    assert "removed_from_watch" in kinds(out) and code == 1


def test_config_change_after_baseline_is_reported(initialized, run):
    set_config(initialized.state_dir, auth={"failure_threshold": 99})
    code, out, _ = run("scan", "--json")
    assert "config_changed_since_baseline" in kinds(out)


def test_init_twice_refused(initialized, run):
    code, _, err = run("init", "--watch", "/etc/hosts")
    assert code == 2 and "already initialized" in err


def test_state_dir_option_after_subcommand(tmp_path, run, monkeypatch):
    monkeypatch.delenv("CLEARSHIELD_STATE_DIR", raising=False)
    sd = tmp_path / "other"
    assert run("init", "--state-dir", str(sd))[0] == 0
    assert (sd / "state.json").exists()


# ------------------------------------------------------------------ audit integrity

def test_verify_passes_then_detects_modified_record(initialized, run):
    assert run("verify")[0] == 0
    rows = open(initialized.log, "rb").read().splitlines(keepends=True)
    rec = json.loads(rows[1])
    rec["data"]["watch"] = []
    rows[1] = audit.canonical(rec) + b"\n"
    open(initialized.log, "wb").writelines(rows)
    code, out, _ = run("verify")
    assert code == 3 and "tag mismatch" in out


def test_modified_last_record_blocks_further_commands(initialized, run):
    rows = open(initialized.log, "rb").read().splitlines(keepends=True)
    rec = json.loads(rows[-1])
    rec["ts"] = "1999-01-01T00:00:00+00:00"
    rows[-1] = audit.canonical(rec) + b"\n"
    open(initialized.log, "wb").writelines(rows)
    code, _, err = run("scan")
    assert code == 3 and "failed verification" in err


def test_truncated_log_detected_against_state(initialized, run):
    run("scan")
    run("scan")
    rows = open(initialized.log, "rb").read().splitlines(keepends=True)
    open(initialized.log, "wb").writelines(rows[:-2])
    assert run("scan")[0] == 3
    code, out, _ = run("verify")
    assert code == 3 and "truncation, rollback, or tampering" in out


def test_full_rollback_passes_locally_but_fails_against_offhost_checkpoint(initialized, run, tmp_path):
    """The central limitation, demonstrated: restoring an older log AND state is
    self-consistent. Only a checkpoint stored elsewhere reveals it."""
    snapshot = tmp_path / "attacker-copy"
    snapshot.mkdir()
    shutil.copy2(initialized.log, snapshot / "audit.jsonl")
    shutil.copy2(initialized.state, snapshot / "state.json")
    with open(initialized.watched, "a") as fh:
        fh.write("malicious change\n")
    assert run("scan")[0] == 1  # detected and recorded...
    offhost = tmp_path / "offhost-checkpoint.json"
    assert run("checkpoint", "--output", str(offhost))[0] == 0
    shutil.copy2(snapshot / "audit.jsonl", initialized.log)  # ...then history is rolled back
    shutil.copy2(snapshot / "state.json", initialized.state)
    code, out, _ = run("verify")
    assert code == 0, "local verification cannot see a consistent rollback (documented limitation)"
    code, out, _ = run("verify", "--checkpoint", str(offhost))
    assert code == 3 and "truncated or rolled back" in out


def test_checkpoint_round_trip(initialized, run, tmp_path):
    cp = tmp_path / "cp.json"
    run("checkpoint", "--output", str(cp))
    run("scan")
    code, out, _ = run("verify", "--checkpoint", str(cp))
    assert code == 0 and "matches" in out


def test_rewritten_history_with_stolen_key_detected_by_checkpoint(initialized, run, tmp_path):
    cp = tmp_path / "cp.json"
    run("checkpoint", "--output", str(cp))
    seq = json.loads(cp.read_text())["seq"]
    ring = audit.load_keyring(initialized.state_dir)
    rows = open(initialized.log, "rb").read().splitlines(keepends=True)
    # attacker with the key re-signs the whole chain with altered content
    prev = audit.GENESIS
    new_rows = []
    for i, raw in enumerate(rows):
        rec = json.loads(raw)
        data = rec["data"]
        if i == 1:
            data = {**data, "watch": []}
        forged = audit.make_record(ring.active, rec["seq"], prev, rec["type"], data, rec["ts"])
        prev = forged["tag"]
        new_rows.append(audit.canonical(forged) + b"\n")
    open(initialized.log, "wb").writelines(new_rows)
    st = load_state(initialized.state_dir, ring)
    st["audit_head"]["tag"] = prev
    from clearshield_core.state import save_state
    save_state(initialized.state_dir, ring, st)
    assert run("verify")[0] == 0  # the key holder can make a consistent forgery
    code, out, _ = run("verify", "--checkpoint", str(cp))
    assert code == 3 and "history was rewritten" in out and seq >= 1


def test_missing_key(initialized, run):
    os.unlink(initialized.key)
    code, _, err = run("verify")
    assert code == 2 and "HMAC key not found" in err


def test_wrong_key(initialized, run):
    with open(initialized.key, "wb") as fh:
        fh.write(os.urandom(32))
    code, out, _ = run("verify")
    assert code == 3 and "key" in out
    assert run("scan")[0] == 3


def test_insecure_state_directory(initialized, run):
    os.chmod(initialized.state_dir, 0o755)
    code, _, err = run("scan")
    assert code == 2 and "chmod 700" in err


def test_malformed_state(initialized, run):
    with open(initialized.state, "w") as fh:
        fh.write("{garbage")
    assert run("scan")[0] == 3
    code, out, _ = run("verify")
    assert code == 3 and "not valid JSON" in out


def test_interrupted_append_line(initialized, run):
    with open(initialized.log, "ab") as fh:
        fh.write(b'{"v":1,"seq":')
    code, _, err = run("scan")
    assert code == 3 and "incomplete line" in err
    code, out, _ = run("verify")
    assert code == 3 and "incomplete final line" in out


def test_record_written_but_state_not_saved_is_recovered(initialized, run):
    ring = audit.load_keyring(initialized.state_dir)
    st = load_state(initialized.state_dir, ring)
    audit.AuditLog(initialized.state_dir, ring, st["audit_head"]).append("scan", {"simulated": "crash"})
    code, _, err = run("scan")
    assert code == 0 and "interrupted command" in err
    assert run("verify")[0] == 0


def test_rotation_new_key_purge_and_verify_all(initialized, run):
    run("scan")
    assert run("rotate")[0] == 0
    run("scan")
    assert run("rotate", "--new-key")[0] == 0
    run("scan")
    code, out, _ = run("verify", "--all")
    assert code == 0 and "archived segment 1" in out and "archived segment 2" in out
    assert len(os.listdir(os.path.join(initialized.state_dir, "keys", "retired"))) == 1
    code, out, _ = run("purge", "--before-segment", "2", "--yes")
    assert code == 0
    code, out, _ = run("verify", "--all")
    assert code == 0 and "purged by operator" in out


def test_deleted_archive_segment_detected(initialized, run):
    run("rotate")
    os.unlink(audit.archive_path(initialized.state_dir, 1))
    code, out, _ = run("verify", "--all")
    assert code == 3 and "missing and not recorded as purged" in out


def test_interrupted_rotation_is_completed(initialized, run):
    ring = audit.load_keyring(initialized.state_dir)
    st = load_state(initialized.state_dir, ring)
    log = audit.AuditLog(initialized.state_dir, ring, st["audit_head"])
    log.append("segment_end", {"reason": "crash test", "new_key": False})
    st["audit_head"] = log.head
    from clearshield_core.state import save_state
    save_state(initialized.state_dir, ring, st)
    os.makedirs(audit.archive_dir(initialized.state_dir), mode=0o700)
    os.replace(initialized.log, audit.archive_path(initialized.state_dir, 1))
    code, _, err = run("scan")  # crash happened before the new segment was started
    assert code == 0 and "interrupted rotation" in err
    assert run("verify", "--all")[0] == 0


def test_no_secret_material_in_outputs(initialized, run):
    key = open(initialized.key, "rb").read()
    outputs = [run("scan", "--json")[1], run("verify", "--json")[1], run("checkpoint")[1]]
    stored = open(initialized.log, "rb").read() + open(initialized.state, "rb").read()
    for blob in outputs:
        assert key.hex() not in blob
    assert key not in stored and key.hex().encode() not in stored


# ------------------------------------------------------------------ listeners and auth

@pytest.mark.skipif(not os.path.exists("/proc/net/tcp"), reason="needs Linux /proc")
def test_new_loopback_listener_detected(state_dir, run, tmp_path):
    run("init", "--watch", str(tmp_path))
    set_config(state_dir, auth={"enabled": False})
    run("baseline")
    sock = socket.socket()
    try:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        port = sock.getsockname()[1]
        code, out, _ = run("scan", "--json")
    finally:
        sock.close()
    new = [f for f in json.loads(out)["findings"] if f["kind"] == "new_listener"]
    mine = [f for f in new if f["listener"] == f"tcp4/127.0.0.1:{port}"]
    assert code == 1 and mine and mine[0]["severity"] == "low"


def test_auth_failures_from_file_source(state_dir, run, tmp_path):
    from datetime import datetime, timezone
    auth = tmp_path / "auth.log"
    auth.write_text("")
    run("init", "--watch", str(tmp_path))
    set_config(state_dir, listeners={"enabled": False},
               auth={"sources": [f"file:{auth}"], "failure_threshold": 3})
    run("baseline")
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with open(auth, "a") as fh:
        for i in range(4):
            fh.write(f"{stamp} host sshd[1]: Failed password for invalid user u{i} "
                     f"from 203.0.113.50 port {4000 + i} ssh2\n")
    code, out, _ = run("scan", "--json")
    assert code == 1 and kinds(out) == ["repeated_auth_failures"]
    assert "u1" not in out  # attempted names of non-existent users are not kept
    code, out, _ = run("scan", "--json")
    assert code == 0 and kinds(out) == []  # cursor: nothing re-read, no duplicate alert
    os.unlink(auth)
    code, out, _ = run("scan", "--json")
    assert code == 1 and kinds(out) == ["auth_source_unavailable"]


# ------------------------------------------------------------------ audio

def test_audio_wav_without_init_uses_defaults_and_records_nothing(run, wav, tmp_path, monkeypatch):
    monkeypatch.setenv("CLEARSHIELD_STATE_DIR", str(tmp_path / "never-created"))
    code, out, _ = run("audio-wav", "--wav", wav([0.0] * 800))
    assert code == 0 and "Not recorded" in out and "silent: yes" in out
    assert not (tmp_path / "never-created").exists()


def test_audio_wav_records_summary_only_and_creates_no_files(initialized, run, wav, tmp_path):
    path = wav(tone(440, 0.5, 12.0, 8000))
    before = tree(str(tmp_path))
    code, out, _ = run("audio-wav", "--wav", path, "--json")
    after = tree(str(tmp_path))
    assert code == 1 and "sustained_high_level" in kinds(out)
    assert set(after) == set(before)  # nothing new anywhere: no recordings, no temp files left
    changed = {p for p in after if after[p] != before[p]}
    assert changed <= {initialized.log, initialized.state}
    last = json.loads(open(initialized.log).read().splitlines()[-1])
    assert last["type"] == "audio_wav_analyzed" and len(json.dumps(last)) < 4096
    assert last["data"]["sha256"] == json.loads(out)["summary"]["sha256"]


def test_audio_wav_rejected_input_is_audited(initialized, run, tmp_path):
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"this is definitely not audio")
    code, _, err = run("audio-wav", "--wav", str(bad))
    assert code == 2 and "not a RIFF/WAVE" in err
    last = json.loads(open(initialized.log).read().splitlines()[-1])
    assert last["type"] == "audio_wav_rejected"


def test_audio_wav_threshold_overrides_validated(initialized, run, wav):
    code, _, err = run("audio-wav", "--wav", wav([0.0] * 80), "--sustained-dbfs", "5")
    assert code == 2 and "outside" in err


class _Stream:
    def __init__(self):
        self.n = 0

    def read(self, frames):
        import math
        import struct
        vals = [0.5 * math.sin(2 * math.pi * 440 * (self.n * frames + i) / 8000) for i in range(frames)]
        self.n += 1
        return struct.pack(f"<{frames}f", *vals), False

    def stop(self):
        pass

    def close(self):
        pass


def test_audio_live_requires_two_step_opt_in(initialized, run, monkeypatch):
    opened = []
    monkeypatch.setattr(cli, "STREAM_FACTORY", lambda *a: opened.append(a) or _Stream())
    code, _, err = run("audio-live", "--seconds", "1", "--allow-microphone")
    assert code == 2 and "disabled" in err
    set_config(initialized.state_dir, audio={"live": {"enabled": True, "sample_rate": 8000}})
    code, _, err = run("audio-live", "--seconds", "1")
    assert code == 2 and "--allow-microphone" in err
    assert opened == []  # the microphone was never opened


def test_audio_live_session_is_audited_and_writes_no_audio(initialized, run, monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "STREAM_FACTORY", lambda *a: _Stream())
    set_config(initialized.state_dir, audio={"live": {"enabled": True, "sample_rate": 8000}})
    before = tree(str(tmp_path))
    code, out, _ = run("audio-live", "--seconds", "12", "--allow-microphone", "--json")
    assert code == 1 and "sustained_high_level" in kinds(out)
    assert set(tree(str(tmp_path))) == set(before)
    types = [json.loads(r)["type"] for r in open(initialized.log).read().splitlines()[-2:]]
    assert types == ["microphone_session_started", "microphone_session_ended"]
