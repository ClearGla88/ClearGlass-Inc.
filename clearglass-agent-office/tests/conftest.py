from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_core.approvals import Principal
from agent_core.office import Office
from agent_core.util import SteppingClock, sequential_ids

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "demo" / "missions.json"
START = datetime(2026, 11, 9, 13, 0, tzinfo=UTC)


def make_office(**kw) -> Office:
    clock = kw.pop("clock", None) or SteppingClock(START, timedelta(seconds=1))
    return Office(ROOT, clock=clock, ids=sequential_ids(), **kw)


@pytest.fixture
def office() -> Office:
    return make_office()


@pytest.fixture
def operator() -> Principal:
    return Principal("operator.founder", "human", "operator")


@pytest.fixture
def ran(office: Office) -> tuple[Office, dict]:
    from apps.worker.daily_loop import run_daily_loop

    return office, run_daily_loop(office, DEMO)
