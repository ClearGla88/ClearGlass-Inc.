#!/usr/bin/env python3
"""ClearGlass Agent Office command line.

    python office.py daily-loop [--db var/office.db] [--json]
    python office.py serve [--host 127.0.0.1] [--port 8000]
    python office.py verify-audit [--db var/office.db]
    python office.py export-snapshot [--db var/office.db] [--out apps/web/src/data/demo-snapshot.json]
    python office.py emergency-stop --reason "..."
    python office.py release-stop --reason "..."
    python office.py approve <approval_id> --reason "..." [--decision approve|reject]

The CLI acts as the operator named in config/company.json. It runs locally with
whatever access the shell user has; the API is the authenticated surface.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
for sub in ("packages", ""):
    p = str(ROOT / sub) if sub else str(ROOT)
    if p not in sys.path:
        sys.path.insert(0, p)

from agent_core.approvals import Principal  # noqa: E402
from agent_core.office import Office  # noqa: E402
from agent_core.providers import provider_from_env  # noqa: E402
from agent_core.util import SteppingClock, sequential_ids  # noqa: E402

DEFAULT_DB = ROOT / "var" / "office.db"
DEMO_MISSIONS = ROOT / "demo" / "missions.json"


def open_office(db: str, *, deterministic: bool = False) -> Office:
    if deterministic:
        clock = SteppingClock(datetime(2026, 11, 6, 13, 0, tzinfo=UTC), timedelta(seconds=2))
        return Office(ROOT, db_path=db, clock=clock, ids=sequential_ids(), provider=provider_from_env())
    return Office(ROOT, db_path=db, provider=provider_from_env())


def operator(office: Office) -> Principal:
    op = office.company().operator
    return Principal(op["id"], "human", op.get("role", "operator"))


def cmd_daily_loop(args: argparse.Namespace) -> int:
    from apps.worker.daily_loop import run_daily_loop

    office = open_office(args.db, deterministic=args.deterministic)
    result = run_daily_loop(office, DEMO_MISSIONS if not args.no_demo else None)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(
            f"Daily loop {result['period']}: {'SKIPPED - ' + result.get('reason', '') if result['skipped'] else 'done'}"
        )
        for s in result["steps"]:
            detail = {k: v for k, v in s.items() if k not in ("step", "name")}
            print(f"  {s['step']}. {s['name']}: {json.dumps(detail, default=str)}")
        if not result["skipped"]:
            print(f"  agents involved: {len(result['agents_involved'])} across {result['departments_involved']}")
            print(f"  approvals pending: {result['approvals_pending']}")
            print(f"  audit chain: ok={result['audit']['ok']} events={result['audit']['count']}")
    return 0 if result["skipped"] or result["audit"]["ok"] else 1


def cmd_verify(args: argparse.Namespace) -> int:
    office = open_office(args.db)
    result = office.audit.verify()
    print(json.dumps(result.to_dict(), indent=2))
    return 0 if result.ok else 1


def cmd_snapshot(args: argparse.Namespace) -> int:
    from apps.api.snapshot import build_snapshot

    office = open_office(args.db)
    snap = build_snapshot(office)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snap, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size} bytes)")
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    """Rebuild the console's offline snapshot from a fresh, deterministic run."""
    from apps.api.snapshot import build_snapshot
    from apps.worker.daily_loop import run_daily_loop
    from simulation.sandbox import SCENARIOS

    db = Path(args.db_out)
    for suffix in ("", "-wal", "-shm"):
        Path(f"{db}{suffix}").unlink(missing_ok=True)
    office = open_office(str(db), deterministic=True)
    result = run_daily_loop(office, DEMO_MISSIONS)
    example = SCENARIOS["pricing"].example
    office.run_simulation(
        "sim.business-war-gamer",
        {"scenario_type": "pricing", "title": "Advisory retainer price points", **example, "seed": 7, "runs": 2000},
    )
    snap = build_snapshot(office)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snap, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(
        f"demo: {len(result['agents_involved'])} agents, {result['departments_involved']}, "
        f"approvals pending {result['approvals_pending']}, audit ok={result['audit']['ok']}"
    )
    print(f"wrote {out} ({out.stat().st_size} bytes)")
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    office = open_office(args.db)
    print(json.dumps(office.emergency_stop(operator(office), args.reason), indent=2))
    return 0


def cmd_release(args: argparse.Namespace) -> int:
    office = open_office(args.db)
    print(json.dumps(office.release_emergency_stop(operator(office), args.reason), indent=2, default=str))
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    office = open_office(args.db)
    approval = office.decide_approval(args.approval_id, operator(office), args.decision, args.reason)
    print(json.dumps({"id": approval.id, "status": approval.status, "execution": approval.execution}, indent=2))
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import os

    import uvicorn

    os.environ.setdefault("OFFICE_DB", args.db)
    uvicorn.run("apps.api.main:app", host=args.host, port=args.port, reload=False)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ClearGlass Agent Office")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite database path")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("daily-loop", help="run the Daily Operations Loop")
    p.add_argument("--json", action="store_true")
    p.add_argument("--no-demo", action="store_true", help="do not load demo missions")
    p.add_argument("--deterministic", action="store_true", help="fixed clock and sequential ids (for demos and CI)")
    p.set_defaults(func=cmd_daily_loop)

    sub.add_parser("verify-audit", help="replay the audit hash chain").set_defaults(func=cmd_verify)

    p = sub.add_parser("export-snapshot", help="write the console's offline snapshot")
    p.add_argument("--out", default=str(ROOT / "apps" / "web" / "src" / "data" / "demo-snapshot.json"))
    p.set_defaults(func=cmd_snapshot)

    p = sub.add_parser("demo", help="fresh deterministic run, then write the offline snapshot")
    p.add_argument("--db-out", default=str(ROOT / "var" / "demo.db"))
    p.add_argument("--out", default=str(ROOT / "apps" / "web" / "src" / "data" / "demo-snapshot.json"))
    p.set_defaults(func=cmd_demo)

    p = sub.add_parser("emergency-stop", help="pause every agent and cancel open approvals")
    p.add_argument("--reason", required=True)
    p.set_defaults(func=cmd_stop)

    p = sub.add_parser("release-stop", help="release the emergency stop")
    p.add_argument("--reason", required=True)
    p.set_defaults(func=cmd_release)

    p = sub.add_parser("approve", help="decide an approval as the operator")
    p.add_argument("approval_id")
    p.add_argument("--reason", required=True)
    p.add_argument("--decision", default="approve", choices=["approve", "reject"])
    p.set_defaults(func=cmd_approve)

    p = sub.add_parser("serve", help="run the API with uvicorn")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
