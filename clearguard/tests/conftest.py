"""Shared fixtures. Every input is synthetic; nothing reads a sensor, plays
audio, or contacts anyone."""

from __future__ import annotations

import copy
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
PKG_ROOT = os.path.dirname(TESTS_DIR)
for _path in (PKG_ROOT, TESTS_DIR):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from cg_testlib import NOW, base_config, observation, validated_contract  # noqa: E402
from clearguard_core import cli  # noqa: E402
from clearguard_core.config import TrustedConfig, validate  # noqa: E402


@pytest.fixture
def now() -> datetime:
    return NOW


@pytest.fixture
def config_data() -> dict:
    data = base_config()
    assert validate(data) == []
    return data


@pytest.fixture
def trusted(config_data) -> TrustedConfig:
    return TrustedConfig(copy.deepcopy(config_data))


@pytest.fixture
def obs():
    return observation


@pytest.fixture
def validated():
    return validated_contract


@pytest.fixture
def later():
    def _later(seconds: float) -> datetime:
        return NOW + timedelta(seconds=seconds)
    return _later


@pytest.fixture
def run(capsys):
    def _run(*argv: str) -> tuple[int, str, str]:
        code = cli.main(list(argv))
        captured = capsys.readouterr()
        return code, captured.out, captured.err
    return _run


__all__ = ["NOW", "timezone"]
