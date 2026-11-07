"""Command line: ``python -m agent_office <command>``.

daily-ops      run the Daily Operations Loop and print the briefing
approvals      list pending approvals, or decide one as a named human operator
verify-ledger  replay the audit hash chain (exit 1 if broken)
serve          start the API and operator console (needs uvicorn)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

DEFAULT_DB = os.environ.get("AGENT_OFFICE_DB", ".agent-office-data/office.db")


def _office(path: str):
    from .office import Office

    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    return Office(path)


def cmd_daily_ops(args: argparse.Namespace) -> int:
    from .daily_ops import run_daily_ops

    office = _office(args.db)
    result = run_daily_ops(office, triggered_by="cli")
    if args.markdown:
        Path(args.markdown).write_text(result["briefing_markdown"] + "\n" + result["operations_markdown"],
                                       encoding="utf-8")
    if args.json:
        print(json.dumps({k: v for k, v in result.items() if not k.endswith("_markdown")}, indent=2, default=str))
    else:
        print(result["briefing_markdown"])
        print(result["operations_markdown"])
    ok = result["ledger"]["ok"] and result["red_team"]["passed"]
    return 0 if ok else 1


def cmd_approvals(args: argparse.Namespace) -> int:
    office = _office(args.db)
    if args.action == "list":
        rows = office.approvals.list("pending")
        for a in rows:
            print(f"{a['id']}  {a['risk_level']:<8}  {a['mission_code'] or '-':<6}  {a['action_summary']}")
        if not rows:
            print("No pending approvals.")
        return 0
    if not (args.id and args.operator and args.reason):
        print("decide needs --id, --operator and --reason", file=sys.stderr)
        return 2
    from .models import GovernanceError

    try:
        approval = office.approvals.decide(
            args.id, decision=args.decision, decider_id=args.operator, decider_type="human", reason=args.reason,
        )
    except GovernanceError as exc:
        print(f"refused: {exc.code}: {exc.message}", file=sys.stderr)
        return 1
    print(f"{approval['id']} -> {approval['status']} by {approval['decided_by']}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    result = _office(args.db).ledger.verify()
    print(json.dumps(result.to_dict(), indent=2))
    return 0 if result.ok else 1


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from .api import create_app

    uvicorn.run(create_app(db_path=args.db), host=args.host, port=args.port)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent_office", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default=DEFAULT_DB, help=f"SQLite path (default {DEFAULT_DB})")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("daily-ops")
    p.add_argument("--json", action="store_true")
    p.add_argument("--markdown", help="also write the briefing and report to this file")
    p.set_defaults(func=cmd_daily_ops)

    p = sub.add_parser("approvals")
    p.add_argument("action", choices=["list", "decide"])
    p.add_argument("--id")
    p.add_argument("--decision", choices=["approve", "reject"], default="approve")
    p.add_argument("--operator", help="the human operator deciding")
    p.add_argument("--reason")
    p.set_defaults(func=cmd_approvals)

    p = sub.add_parser("verify-ledger")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("serve")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8080)
    p.set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
