"""Command line: startup report, key and configuration handling, template lint.

Exit codes: 0 success, 1 check failed, 2 usage or input error.
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from . import __version__
from .alerts import TEMPLATES, lint_message
from .config import generate_key, load_config, read_key, sign, write_key
from .errors import GuardianError
from .guardian import Guardian


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="guardian-sentinel", description="Guardian Sentinel core (design mode).")
    parser.add_argument("--version", action="version", version=f"guardian-sentinel {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("startup", help="print the startup report")
    p.add_argument("--config")
    p.add_argument("--key")
    p = sub.add_parser("keygen", help="create a new enrollment key file (mode 600)")
    p.add_argument("path")
    p = sub.add_parser("sign-config", help="validate a plain configuration and write the authenticated file")
    p.add_argument("plain")
    p.add_argument("out")
    p.add_argument("--key", required=True)
    p = sub.add_parser("check-config", help="authenticate and validate a configuration file")
    p.add_argument("path")
    p.add_argument("--key", required=True)
    sub.add_parser("lint-templates", help="check every approved alert template")
    args = parser.parse_args(argv)

    try:
        if args.cmd == "startup":
            config = None
            if args.config or args.key:
                if not (args.config and args.key):
                    print("startup needs both --config and --key", file=sys.stderr)
                    return 2
                config = load_config(args.config, read_key(args.key))
            print(Guardian(config=config).startup_report(time.time()))
            return 0
        if args.cmd == "keygen":
            write_key(args.path, generate_key())
            print(f"wrote {args.path}")
            return 0
        if args.cmd == "sign-config":
            with open(args.plain, "r", encoding="utf-8") as fh:
                plain = json.load(fh)
            envelope = sign(plain, read_key(args.key))
            with open(args.out, "x", encoding="utf-8") as fh:
                json.dump(envelope, fh, indent=2, sort_keys=True)
                fh.write("\n")
            print(f"wrote {args.out}")
            return 0
        if args.cmd == "check-config":
            cfg = load_config(args.path, read_key(args.key))
            consent = "valid" if cfg.consent_valid(time.time()) else "EXPIRED"
            print(f"ok: policy {cfg.policy_version}, {len(cfg.actions)} action(s), consent {consent}")
            return 0 if consent == "valid" else 1
        if args.cmd == "lint-templates":
            bad = {tid: lint_message(t.text, t.priority) for tid, t in TEMPLATES.items()}
            bad = {k: v for k, v in bad.items() if v}
            for tid, problems in bad.items():
                print(f"{tid}: {'; '.join(problems)}")
            print(f"{len(TEMPLATES)} template(s), {len(bad)} with problems")
            return 1 if bad else 0
    except (GuardianError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 2  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
