"""The real script, run as a subprocess: interface compatibility and exit codes."""

from __future__ import annotations

import os
import subprocess
import sys

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                      "clearshield.py")


def cs(*args, env_dir=None):
    env = {"PATH": "/usr/bin:/bin", "HOME": str(env_dir or "/nonexistent")}
    if env_dir:
        env["CLEARSHIELD_STATE_DIR"] = os.path.join(str(env_dir), "state")
    return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True, env=env,
                          timeout=60)


def test_original_v1_commands_and_flags_exist():
    top = cs("--help").stdout
    for command in ("init", "baseline", "scan", "verify", "audio-wav"):
        assert command in top
    assert "--watch" in cs("init", "--help").stdout
    assert "--wav" in cs("audio-wav", "--help").stdout


def test_documented_v1_workflow_and_exit_codes(tmp_path):
    hosts = tmp_path / "hosts"
    hosts.write_text("127.0.0.1 localhost\n")
    config_override = '{"auth": {"enabled": false}, "listeners": {"enabled": false}}'
    assert cs("init", "--watch", str(hosts), env_dir=tmp_path).returncode == 0
    (tmp_path / "state" / "config.json").write_text(config_override)
    assert cs("baseline", env_dir=tmp_path).returncode == 0
    assert cs("scan", env_dir=tmp_path).returncode == 0
    hosts.write_text("127.0.0.1 localhost\n203.0.113.1 bank.example\n")
    result = cs("scan", env_dir=tmp_path)
    assert result.returncode == 1 and "content_changed" in result.stdout
    assert cs("verify", env_dir=tmp_path).returncode == 0
    with open(tmp_path / "state" / "audit.jsonl", "ab") as fh:
        fh.write(b"{}\n")
    assert cs("verify", env_dir=tmp_path).returncode == 3


def test_usage_error_exit_code():
    assert cs("no-such-command").returncode == 2


def test_no_traceback_on_operational_error(tmp_path):
    result = cs("scan", env_dir=tmp_path)
    assert result.returncode == 2 and "Traceback" not in result.stderr
    assert "Run 'clearshield.py init' first" in result.stderr
