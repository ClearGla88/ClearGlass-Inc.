"""Shared fixtures. Every test runs in its own temporary directory; nothing
touches the real state directory, the real auth logs, or a microphone."""

from __future__ import annotations

import os
import sys
from typing import Callable

import pytest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
PKG_ROOT = os.path.dirname(TESTS_DIR)
for _path in (PKG_ROOT, TESTS_DIR):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from clearshield_core import cli  # noqa: E402
from cs_testlib import build_wav, set_config  # noqa: E402

@pytest.fixture
def wav(tmp_path) -> Callable[..., str]:
    counter = {"n": 0}

    def make(samples: list[float] | None = None, name: str | None = None, **kw) -> str:
        counter["n"] += 1
        path = tmp_path / (name or f"fixture{counter['n']}.wav")
        path.write_bytes(build_wav(samples, **kw))
        return str(path)

    return make


@pytest.fixture
def run(capsys) -> Callable[..., tuple[int, str, str]]:
    def _run(*argv: str) -> tuple[int, str, str]:
        code = cli.main(list(argv))
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    return _run


@pytest.fixture
def state_dir(tmp_path, monkeypatch) -> str:
    sd = tmp_path / "state"
    monkeypatch.setenv("CLEARSHIELD_STATE_DIR", str(sd))
    return str(sd)


@pytest.fixture
def initialized(state_dir, tmp_path, run):
    """Initialized, baselined state watching one file; listeners and auth disabled for determinism."""
    watched = tmp_path / "watched.conf"
    watched.write_text("setting = 1\n")
    code, _, err = run("init", "--watch", str(watched))
    assert code == 0, err
    set_config(state_dir, listeners={"enabled": False}, auth={"enabled": False})
    code, _, err = run("baseline")
    assert code == 0, err

    class Ctx:
        pass

    ctx = Ctx()
    ctx.state_dir = state_dir
    ctx.watched = str(watched)
    ctx.log = os.path.join(state_dir, "audit.jsonl")
    ctx.state = os.path.join(state_dir, "state.json")
    ctx.key = os.path.join(state_dir, "keys", "hmac.key")
    return ctx
