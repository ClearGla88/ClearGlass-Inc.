"""Command-line interface. Run ``python3 clearguard.py --help``.

Everything here runs offline in design mode. ``simulate`` replays a synthetic
scenario through the real gate, policy engine and workflows; it never touches a
sensor, speaker, or contact.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict

from . import DESIGN_MODE_NOTICE, PRODUCT, __version__
from . import audit as audit_mod
from . import config as config_mod
from . import contracts as contracts_mod
from .alerts import TEMPLATES, lint_templates
from .audit import AuditLog
from .capability import load_registry, registry_problems
from .errors import (
    EXIT_ERROR,
    EXIT_INTEGRITY,
    EXIT_NOT_READY,
    EXIT_OK,
    ClearGuardError,
    ConfigError,
    IntegrityError,
)
from .session import Session
from .timeutil import parse_time, utcnow

PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIM_BANNER = "SIMULATION: synthetic inputs only. No sensor was read, no sound was played, no one was contacted."


def _emit(args: argparse.Namespace, payload: dict, lines: list[str]) -> None:
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    else:
        print("\n".join(lines))


def _load_config(args: argparse.Namespace) -> tuple[config_mod.TrustedConfig | None, str]:
    path = getattr(args, "config", None)
    if not path:
        return None, "missing"
    data = config_mod.read_json(path)
    problems = config_mod.validate(data)
    if problems:
        raise ConfigError(problems)
    key = config_mod.read_key(args.key) if getattr(args, "key", None) else None
    status = config_mod.signature_status(data, key)
    if status == "verified":
        return config_mod.TrustedConfig(data), status
    return None, status


def _session(args: argparse.Namespace, *, simulation: bool = False) -> Session:
    config, status = _load_config(args)
    return Session(config=config, config_status=status, simulation=simulation)


def cmd_startup(args: argparse.Namespace) -> int:
    session = _session(args)
    now = utcnow()
    lines = session.startup(now)
    r = session.readiness(now)
    _emit(args, {"lines": lines, "readiness": asdict(r)}, lines)
    return EXIT_OK


def cmd_status(args: argparse.Namespace) -> int:
    session = _session(args)
    response = session.command("Guardian, status.", utcnow())
    _emit(args, asdict(response), [response.text])
    return EXIT_OK


def cmd_activate(args: argparse.Namespace) -> int:
    session = _session(args)
    ok, message = session.try_activate(utcnow())
    _emit(args, {"activated": ok, "message": message}, [message])
    return EXIT_OK if ok else EXIT_NOT_READY


def cmd_say(args: argparse.Namespace) -> int:
    session = _session(args)
    response = session.command(args.text, utcnow())
    _emit(args, asdict(response), [response.text])
    return EXIT_OK if response.command else EXIT_NOT_READY


def cmd_keygen(args: argparse.Namespace) -> int:
    try:
        config_mod.generate_key(args.output)
    except FileExistsError as exc:
        raise ClearGuardError(f"{args.output} already exists; refusing to overwrite a key") from exc
    _emit(args, {"key": args.output}, [
        f"Wrote a new key to {args.output} (mode 0600).",
        "Keep it off shared storage and out of the repository. Anyone holding it can sign a configuration.",
    ])
    return EXIT_OK


def cmd_sign(args: argparse.Namespace) -> int:
    data = config_mod.read_json(args.config_file)
    problems = config_mod.validate(data)
    if problems:
        raise ConfigError(problems)
    signed = config_mod.sign(data, config_mod.read_key(args.key))
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(signed, handle, indent=2, sort_keys=True)
        handle.write("\n")
    unresolved = config_mod.placeholders(signed)
    lines = [f"Signed {args.config_file} -> {args.output} (key {signed['signature']['key_id']})."]
    if unresolved:
        lines.append(f"Warning: {len(unresolved)} placeholder value(s) remain; readiness checks will fail until they are set.")
    _emit(args, {"output": args.output, "key_id": signed["signature"]["key_id"], "placeholders": unresolved}, lines)
    return EXIT_OK


def cmd_check_config(args: argparse.Namespace) -> int:
    data = config_mod.read_json(args.config_file)
    problems = config_mod.validate(data)
    key = config_mod.read_key(args.key) if args.key else None
    status = config_mod.signature_status(data, key) if not problems else "not checked"
    unresolved = config_mod.placeholders(data) if not problems else []
    lines = [f"Schema: {'valid' if not problems else 'INVALID'}"]
    lines += [f"  - {p}" for p in problems]
    lines.append(f"Signature: {status}")
    if unresolved:
        lines.append(f"Unresolved values ({len(unresolved)}): " + ", ".join(unresolved))
    accepted = not problems and status == "verified"
    lines.append("Accepted for operation: " + ("yes" if accepted else "no"))
    _emit(args, {"problems": problems, "signature": status, "placeholders": unresolved, "accepted": accepted}, lines)
    if problems:
        return EXIT_ERROR
    if status == "invalid":
        return EXIT_INTEGRITY
    return EXIT_OK if accepted else EXIT_NOT_READY


def cmd_contracts(args: argparse.Namespace) -> int:
    contracts = contracts_mod.load_contracts()
    rows, lines = [], [f"{'detector':26} {'hazard':28} {'implementation':16} validated"]
    for cid, contract in contracts.items():
        gaps = contracts_mod.validation_gaps(contract)
        rows.append({"detector_id": cid, "hazard": contract["hazard"], "implementation": contract["implementation"],
                     "validated": not gaps, "gaps": gaps})
        lines.append(f"{cid:26} {contract['hazard']:28} {contract['implementation']:16} {'yes' if not gaps else 'no'}")
        lines += [f"    gap: {g}" for g in gaps]
    _emit(args, {"contracts": rows}, lines)
    return EXIT_OK


def cmd_capabilities(args: argparse.Namespace) -> int:
    caps = load_registry()
    problems = registry_problems(caps, PACKAGE_ROOT)
    lines = [f"{c.level.name:12} {c.title}" for c in caps]
    lines += [f"PROBLEM: {p}" for p in problems]
    _emit(args, {"capabilities": [{"id": c.cap_id, "title": c.title, "level": c.level.name, "limits": c.limits}
                                  for c in caps], "problems": problems}, lines)
    return EXIT_ERROR if problems else EXIT_OK


def cmd_lint(args: argparse.Namespace) -> int:
    problems = lint_templates()
    lines = [f"{tid:24} {prio.name:9} {text}" for tid, (prio, text) in TEMPLATES.items()]
    lines += [f"PROBLEM: {p}" for p in problems] or ["All templates pass."]
    _emit(args, {"problems": problems}, lines)
    return EXIT_NOT_READY if problems else EXIT_OK


def run_scenario(session: Session, scenario: dict) -> list[dict]:
    """Replay a scenario. Each step has ``at`` (ISO time) and exactly one of
    ``observation``, ``event``, ``command``, ``tick`` or ``activate``."""
    if scenario.get("schema") != "clearguard.scenario/1":
        raise ClearGuardError("scenario: schema must be 'clearguard.scenario/1'")
    out: list[dict] = []
    for i, step in enumerate(scenario.get("steps", [])):
        try:
            now = parse_time(step["at"])
        except (KeyError, ValueError) as exc:
            raise ClearGuardError(f"scenario step {i}: needs a valid 'at' time") from exc
        kinds = [k for k in ("observation", "event", "command", "tick", "activate") if k in step]
        if len(kinds) != 1:
            raise ClearGuardError(f"scenario step {i}: needs exactly one action")
        kind = kinds[0]
        record: dict = {"step": i, "at": step["at"], "kind": kind}
        if kind == "observation":
            admission = session.observe(step["observation"], now)
            record.update(id=admission.observation_id, result=admission.status, reasons=admission.reasons)
        elif kind == "event":
            decision, deliveries = session.raise_event(step["event"], now)
            record.update(id=decision.event_id, result=decision.outcome, reasons=decision.reasons,
                          alert=decision.alert.spoken() if decision.alert else None,
                          deliveries=[d.describe() for d in deliveries],
                          proposed_actions=decision.proposed_actions)
        elif kind == "command":
            response = session.command(step["command"], now)
            record.update(id=step["command"], result=response.command or "refused", text=response.text,
                          confirmed=response.confirmed)
        elif kind == "tick":
            record.update(result="tick", text=" ".join(session.emergency.tick(now)) or "nothing pending")
        else:
            ok, message = session.try_activate(now)
            record.update(result="activated" if ok else "refused", text=message)
        out.append(record)
    return out


def cmd_simulate(args: argparse.Namespace) -> int:
    with open(args.scenario, encoding="utf-8") as handle:
        scenario = json.load(handle)
    config, status = _load_config(args)
    audit = AuditLog(args.audit_out) if args.audit_out else None
    session = Session(config=config, config_status=status, simulation=True, audit=audit)
    results = run_scenario(session, scenario)
    lines = [SIM_BANNER, f"Scenario: {scenario.get('label', args.scenario)}"]
    for r in results:
        head = f"[{r['at']}] {r['kind']:11} {r.get('id') or '':22} {r['result']}"
        lines.append(head)
        for reason in r.get("reasons") or []:
            lines.append(f"    reason: {reason}")
        if r.get("alert"):
            lines.append(f"    alert: {r['alert']}")
        for d in r.get("deliveries") or []:
            lines.append(f"    delivery: {d}")
        if r.get("proposed_actions"):
            lines.append(f"    proposed actions (not executed): {', '.join(r['proposed_actions'])}")
        if r.get("text"):
            lines.append(f"    {r['text']}")
    chain = audit_mod.verify(session.audit.records)
    lines.append(f"Audit trail: {len(session.audit.records)} record(s), chain {'intact' if not chain else 'BROKEN'}")
    lines.append(DESIGN_MODE_NOTICE)
    _emit(args, {"banner": SIM_BANNER, "results": results, "audit_records": len(session.audit.records),
                 "audit_problems": chain}, lines)
    return EXIT_INTEGRITY if chain else EXIT_OK


def cmd_verify_audit(args: argparse.Namespace) -> int:
    records = AuditLog(args.audit_file).records
    problems = audit_mod.verify(records)
    lines = [f"{len(records)} record(s)."] + [f"  - {p}" for p in problems]
    lines.append("Result: " + ("PASS" if not problems else "FAIL"))
    lines.append("Tamper-evident, not tamper-proof: whoever can rewrite the whole file can rebuild the chain.")
    _emit(args, {"records": len(records), "problems": problems}, lines)
    return EXIT_INTEGRITY if problems else EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="clearguard",
        description=f"{PRODUCT}: Guardian Sentinel personal-safety core. {DESIGN_MODE_NOTICE}",
    )
    parser.add_argument("--version", action="version", version=f"{PRODUCT} {__version__}")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    sub = parser.add_subparsers(dest="command", required=True)

    def with_config(p: argparse.ArgumentParser) -> argparse.ArgumentParser:
        p.add_argument("--config", help="signed configuration file")
        p.add_argument("--key", help="key file used to verify the configuration signature")
        return p

    with_config(sub.add_parser("startup", help="the startup readiness report")).set_defaults(func=cmd_startup)
    with_config(sub.add_parser("status", help="answer 'Guardian, status.'")).set_defaults(func=cmd_status)
    with_config(sub.add_parser("activate", help="try the activation flow (refused in design mode)")).set_defaults(func=cmd_activate)
    p = with_config(sub.add_parser("say", help="run one voice command, e.g. \"Guardian, what is unavailable?\""))
    p.add_argument("text")
    p.set_defaults(func=cmd_say)
    p = sub.add_parser("keygen", help="create a configuration-signing key (mode 0600)")
    p.add_argument("--output", required=True)
    p.set_defaults(func=cmd_keygen)
    p = sub.add_parser("sign-config", help="validate and sign a configuration")
    p.add_argument("config_file")
    p.add_argument("--key", required=True)
    p.add_argument("--output", required=True)
    p.set_defaults(func=cmd_sign)
    p = sub.add_parser("check-config", help="validate a configuration and check its signature")
    p.add_argument("config_file")
    p.add_argument("--key")
    p.set_defaults(func=cmd_check_config)
    sub.add_parser("contracts", help="detector contracts and their validation gaps").set_defaults(func=cmd_contracts)
    sub.add_parser("capabilities", help="capability states and evidence").set_defaults(func=cmd_capabilities)
    sub.add_parser("lint-templates", help="check the pre-approved alert templates").set_defaults(func=cmd_lint)
    p = with_config(sub.add_parser("simulate", help="replay a synthetic scenario"))
    p.add_argument("scenario")
    p.add_argument("--audit-out", help="also write the audit trail to this JSON-lines file")
    p.set_defaults(func=cmd_simulate)
    p = sub.add_parser("verify-audit", help="verify an audit trail written by simulate --audit-out")
    p.add_argument("audit_file")
    p.set_defaults(func=cmd_verify_audit)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ConfigError as exc:
        print("Configuration rejected:", file=sys.stderr)
        for problem in exc.problems:
            print(f"  - {problem}", file=sys.stderr)
        return EXIT_ERROR
    except IntegrityError as exc:
        print(f"Integrity failure: {exc}", file=sys.stderr)
        return EXIT_INTEGRITY
    except (ClearGuardError, OSError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_ERROR
