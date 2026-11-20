"""Authenticated state, private directories, atomic writes, locking (unit)."""

from __future__ import annotations

import json
import os

import pytest

from clearshield_core import audit, fsutil
from clearshield_core.errors import ClearShieldError, ConfigError, IntegrityFailure, InsecurePermissions
from clearshield_core.state import load_state, new_state_data, save_state, state_path


@pytest.fixture
def ring_dir(tmp_path):
    sd = str(tmp_path / "s")
    fsutil.make_private_dir(sd)
    key = audit.generate_key(sd)
    ring = audit.Keyring(key, {})
    save_state(sd, ring, new_state_data(["/etc/hosts"], {"segment": 1, "seq": 0, "tag": "0" * 64,
                                                           "kid": ring.active_kid}, "t"))
    return sd, ring


def test_state_round_trip(ring_dir):
    sd, ring = ring_dir
    assert load_state(sd, ring)["watch"] == ["/etc/hosts"]


def test_state_edit_without_key_detected(ring_dir):
    sd, ring = ring_dir
    env = json.loads(open(state_path(sd)).read())
    env["data"]["watch"] = []  # attacker removes the watch list but cannot re-tag
    with open(state_path(sd), "w") as fh:
        json.dump(env, fh)
    with pytest.raises(IntegrityFailure, match="failed authentication"):
        load_state(sd, ring)


@pytest.mark.parametrize("content", [b"", b"{not json", b"[1,2]", b'{"format":"other"}'])
def test_malformed_state_is_an_integrity_failure(ring_dir, content):
    sd, ring = ring_dir
    with open(state_path(sd), "wb") as fh:
        fh.write(content)
    with pytest.raises(IntegrityFailure):
        load_state(sd, ring)


def test_missing_state(ring_dir):
    sd, ring = ring_dir
    os.unlink(state_path(sd))
    with pytest.raises(IntegrityFailure, match="missing"):
        load_state(sd, ring)


def test_world_readable_state_dir_rejected(tmp_path):
    d = tmp_path / "open"
    d.mkdir()
    os.chmod(d, 0o755)
    with pytest.raises(InsecurePermissions, match="chmod 700"):
        fsutil.check_private_dir(str(d))


def test_symlinked_state_dir_rejected(tmp_path):
    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    link = tmp_path / "link"
    link.symlink_to(real)
    with pytest.raises(InsecurePermissions, match="symlink"):
        fsutil.check_private_dir(str(link))


def test_missing_state_dir_explains_init(tmp_path):
    with pytest.raises(ConfigError, match="init"):
        fsutil.check_private_dir(str(tmp_path / "nope"))


def test_make_private_dir_ignores_permissive_umask(tmp_path):
    old = os.umask(0o000)
    try:
        fsutil.make_private_dir(str(tmp_path / "p"))
    finally:
        os.umask(old)
    assert (os.stat(tmp_path / "p").st_mode & 0o777) == 0o700


def test_atomic_write_sets_mode_and_replaces(tmp_path):
    target = tmp_path / "f"
    target.write_text("old")
    fsutil.atomic_write(str(target), b"new")
    assert target.read_text() == "new" and (os.stat(target).st_mode & 0o777) == 0o600


def test_interrupted_atomic_write_keeps_old_file_and_cleans_up(tmp_path, monkeypatch):
    target = tmp_path / "f"
    target.write_text("old")

    def boom(*a, **k):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(fsutil.os, "replace", boom)
    with pytest.raises(OSError):
        fsutil.atomic_write(str(target), b"new")
    assert target.read_text() == "old"
    assert [p.name for p in tmp_path.iterdir()] == ["f"]  # no .partial leftovers


def test_interrupted_state_save_keeps_previous_state(ring_dir, monkeypatch):
    sd, ring = ring_dir
    data = load_state(sd, ring)
    data["watch"] = ["/changed"]
    monkeypatch.setattr(fsutil.os, "replace", lambda *a: (_ for _ in ()).throw(OSError(5, "EIO")))
    with pytest.raises(OSError):
        save_state(sd, ring, data)
    monkeypatch.undo()
    assert load_state(sd, ring)["watch"] == ["/etc/hosts"]


def test_create_exclusive_refuses_overwrite(tmp_path):
    p = tmp_path / "k"
    fsutil.create_exclusive(str(p), b"a")
    with pytest.raises(FileExistsError):
        fsutil.create_exclusive(str(p), b"b")


def test_read_private_file_size_cap(tmp_path):
    p = tmp_path / "big"
    p.write_bytes(b"x" * 100)
    os.chmod(p, 0o600)
    with pytest.raises(ClearShieldError, match="exceeds"):
        fsutil.read_private_file(str(p), 10)


def test_lock_is_exclusive(tmp_path):
    d = str(tmp_path)
    with fsutil.StateLock(d):
        with pytest.raises(ClearShieldError, match="another ClearShield command"):
            with fsutil.StateLock(d):
                pass
    with fsutil.StateLock(d):  # released
        pass
