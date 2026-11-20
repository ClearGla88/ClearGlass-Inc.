#!/usr/bin/env python3
"""ClearGlass Active Defense command line.

Run ``python3 defense.py --help`` for the command list. Every command that
takes CONFIG validates the whole deployment first and exits 2 if it is invalid.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import sys
import time
from pathlib import Path

from active_defense import __version__


def _bundle(path: str, **kw):
    from active_defense.config import ConfigError, load_bundle

    try:
        return load_bundle(path, **kw)
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2) from None


def _store(bundle):
    from active_defense.store import Store

    store = Store(bundle.database_path)
    store.init()
    return store


def _read_key(args) -> bytes:
    from active_defense.config import load_secret

    value = load_secret(env=args.key_env, file=args.key_file, base_dir=Path.cwd(), what=f"sensor {args.sensor_id}")
    return value.encode()


def cmd_check_config(args) -> int:
    b = _bundle(args.config)
    print(json.dumps({
        "config": str(b.config_path), "environment": b.config.environment, "mode": b.config.mode,
        "policy_version": b.config.policy_version, "inventory_version": b.registry.version,
        "ruleset_version": b.ruleset.ruleset_version, "assets": len(b.registry.all()),
        "rules": len(b.ruleset.rules), "correlations": len(b.ruleset.correlations),
        "playbooks": sorted(b.playbooks), "sensors": sorted(b.sensors),
        "principals": len(b.principals_by_token_hash), "adapter": b.config.response.adapter,
    }, indent=2))
    return 0


def cmd_init_secrets(args) -> int:
    from active_defense.lab import init_secrets

    created = init_secrets(args.config)
    for p in created:
        print(f"created {p} (mode 0600)")
    if not created:
        print("all secret files already exist; nothing written")
    return 0


def cmd_init_db(args) -> int:
    b = _bundle(args.config, load_sensor_keys=False, load_principals=False)
    _store(b)
    print(f"database ready: {b.database_path}")
    return 0


def cmd_serve(args) -> int:
    import uvicorn

    from active_defense.api import create_app

    if not ipaddress.ip_address(args.host).is_loopback and not (args.tls_cert and args.tls_key):
        if not args.plaintext_on_isolated_network:
            print("refusing to listen on a non-loopback address without --tls-cert and --tls-key", file=sys.stderr)
            return 2
        print("WARNING: plaintext HTTP on a non-loopback address. Only for an isolated container network whose "
              "published port is bound to 127.0.0.1 (see docker-compose.yml).", file=sys.stderr)
    b = _bundle(args.config)
    store = _store(b)
    uvicorn.run(create_app(b, store), host=args.host, port=args.port, ssl_certfile=args.tls_cert,
                ssl_keyfile=args.tls_key, log_level="info", server_header=False)
    return 0


def cmd_worker(args) -> int:
    from active_defense.adapters import MockNetworkAdapter
    from active_defense.executor import Executor

    b = _bundle(args.config, load_sensor_keys=False, load_principals=False)
    store = _store(b)
    adapter = MockNetworkAdapter(args.adapter_state or (b.state_dir / "mock_network.db"))
    ex = Executor(store, b, adapter, worker_id=args.worker_id)
    while True:
        for r in ex.run_once():
            print(json.dumps(r), flush=True)
        if args.once:
            return 0
        time.sleep(args.interval)


def cmd_demo(args) -> int:
    from active_defense import demo

    if args.json:
        demo.main_json(args.keep)
    else:
        result = demo.run(args.keep)
        print(f"\nlab data written to {result['root']}")
    return 0


def cmd_verify_audit(args) -> int:
    b = _bundle(args.config, load_sensor_keys=False, load_principals=False)
    result = _store(b).verify_audit()
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


def cmd_verify_evidence(args) -> int:
    from active_defense.evidence import verify_case

    b = _bundle(args.config, load_sensor_keys=False, load_principals=False)
    result = verify_case(_store(b).connect(), args.case_id)
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


def cmd_metrics(args) -> int:
    from active_defense.config import Principal
    from active_defense.engine import Engine
    from active_defense.operations import Operations

    b = _bundle(args.config, load_sensor_keys=False, load_principals=False)
    ops = Operations(Engine(_store(b), b))
    print(json.dumps(ops.metrics(Principal("local-cli", "analyst")), indent=2))
    return 0


def cmd_mint_honeytoken(args) -> int:
    from active_defense import honeytokens
    from active_defense.util import Clock

    b = _bundle(args.config, load_sensor_keys=False, load_principals=False)
    store = _store(b)
    token = honeytokens.mint()
    with store.tx() as c:
        token_id = honeytokens.register(c, token, label=args.label, placement=args.placement, at=Clock().now())
    print(json.dumps({"token_id": token_id, "token": token,
                      "note": "shown once; only its fingerprint is stored. It grants no access anywhere."}))
    return 0


def cmd_create_honeyfile(args) -> int:
    from active_defense import honeytokens
    from active_defense.sensors.honeyfile import create_honeyfile
    from active_defense.util import Clock

    b = _bundle(args.config, load_sensor_keys=False, load_principals=False)
    store = _store(b)
    token = create_honeyfile(args.path)
    with store.tx() as c:
        token_id = honeytokens.register(c, token, label=args.label, placement=f"honeyfile {args.path}",
                                        at=Clock().now())
    print(json.dumps({"honeyfile": str(Path(args.path).resolve()), "token_id": token_id}))
    return 0


def cmd_kill_switch(args) -> int:
    b = _bundle(args.config, load_sensor_keys=False, load_principals=False)
    path = b.emergency_stop_file
    if args.state == "on":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"engaged {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n", encoding="utf-8")
        print(f"kill switch ON: {path}. The worker stops claiming actions; existing containment is unchanged.")
    else:
        path.unlink(missing_ok=True)
        print(f"kill switch OFF: {path} removed. The database emergency stop, if engaged, still applies.")
    return 0


def cmd_retention(args) -> int:
    from active_defense.evidence import apply_retention
    from active_defense.util import Clock

    b = _bundle(args.config, load_sensor_keys=False, load_principals=False)
    n = apply_retention(_store(b), retention_days=b.config.evidence.retention_days, at=Clock().now(),
                        actor="cli:retention")
    print(f"purged content of {n} artifact(s); hashes and custody records kept")
    return 0


def cmd_send_synthetic(args) -> int:
    from active_defense.sensors.client import SignedClient
    from active_defense.simulate import scenario_events

    b = _bundle(args.config)
    if b.config.environment != "lab":
        print("send-synthetic is a lab tool; refusing for a non-lab deployment", file=sys.stderr)
        return 2
    for sensor_id, event in scenario_events(args.scenario, environment=b.config.environment,
                                            scope=b.config.authorization_scope):
        status, body = SignedClient(args.api, sensor_id, b.sensor_keys[sensor_id]).send(event)
        print(json.dumps({"sensor": sensor_id, "http": status, "response": body}))
    return 0


def _sink(args):
    from active_defense.sensors.client import AsyncSender, SignedClient

    client = SignedClient(args.api, args.sensor_id, _read_key(args), spool_dir=args.spool_dir)
    client.flush_spool()
    return AsyncSender(client)


def cmd_sensor(args) -> int:
    sender = _sink(args)
    common = {"sink": sender.submit, "sensor_id": args.sensor_id, "environment": args.environment,
              "scope": args.scope}
    if args.kind == "http":
        from active_defense.sensors.http_honeypot import HttpHoneypot
        sensor = HttpHoneypot(args.bind, args.port, **common).start()
        print(f"HTTP decoy on {args.bind}:{sensor.port}")
    elif args.kind == "tcp":
        from active_defense.sensors.tcp_tripwire import TcpTripwire
        sensor = TcpTripwire(args.bind, args.port, **common).start()
        print(f"TCP tripwire on {args.bind}:{sensor.port}")
    else:
        from active_defense.sensors.honeyfile import HoneyfileWatcher
        sensor = HoneyfileWatcher(args.path, **common).start()
        print(f"honeyfile watcher: {json.dumps(sensor.capabilities())}")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        sensor.stop()
        sender.drain()
        sender.stop()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="defense.py", description="ClearGlass Active Defense (lab-first).")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)

    def with_config(name: str, func, help_text: str) -> argparse.ArgumentParser:
        sp = sub.add_parser(name, help=help_text)
        sp.add_argument("config")
        sp.set_defaults(func=func)
        return sp

    with_config("check-config", cmd_check_config, "validate the whole deployment")
    with_config("init-secrets", cmd_init_secrets, "create missing key and token files (0600, never overwrites)")
    with_config("init-db", cmd_init_db, "create the database schema")
    sp = with_config("serve", cmd_serve, "run the control API")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=8088)
    sp.add_argument("--tls-cert")
    sp.add_argument("--tls-key")
    sp.add_argument("--plaintext-on-isolated-network", action="store_true",
                    help="allow plain HTTP on a non-loopback address inside an isolated container network")
    sp = with_config("worker", cmd_worker, "run the response executor")
    sp.add_argument("--once", action="store_true")
    sp.add_argument("--interval", type=float, default=5.0)
    sp.add_argument("--worker-id", default="worker-1")
    sp.add_argument("--adapter-state")
    with_config("verify-audit", cmd_verify_audit, "replay the audit hash chain")
    sp = with_config("verify-evidence", cmd_verify_evidence, "recompute a case's artifact hashes")
    sp.add_argument("case_id")
    with_config("metrics", cmd_metrics, "print measured counts and latencies, with their limits")
    sp = with_config("mint-honeytoken", cmd_mint_honeytoken, "create and register a synthetic honeytoken")
    sp.add_argument("--label", required=True)
    sp.add_argument("--placement", required=True)
    sp = with_config("create-honeyfile", cmd_create_honeyfile, "write a decoy file holding a fresh honeytoken")
    sp.add_argument("path")
    sp.add_argument("--label", required=True)
    sp = with_config("kill-switch", cmd_kill_switch, "out-of-band emergency stop file for the worker")
    sp.add_argument("state", choices=["on", "off"])
    with_config("retention", cmd_retention, "purge evidence content past the retention period")
    sp = with_config("send-synthetic", cmd_send_synthetic, "send a benign synthetic scenario (lab only)")
    sp.add_argument("--api", default="http://127.0.0.1:8088")
    sp.add_argument("--scenario", required=True)

    sp = sub.add_parser("demo", help="run the end-to-end lab demonstration on loopback")
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--keep", help="directory to keep the lab data in (default: a new temporary directory)")
    sp.set_defaults(func=cmd_demo)

    sp = sub.add_parser("sensor", help="run one sensor; it holds only its own key")
    sp.add_argument("kind", choices=["http", "tcp", "honeyfile"])
    sp.add_argument("--sensor-id", required=True)
    key = sp.add_mutually_exclusive_group(required=True)
    key.add_argument("--key-file")
    key.add_argument("--key-env")
    sp.add_argument("--api", default="http://127.0.0.1:8088")
    sp.add_argument("--environment", default="lab", choices=["lab", "staging", "production"])
    sp.add_argument("--scope", required=True)
    sp.add_argument("--bind", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=0)
    sp.add_argument("--path", nargs="*", default=[])
    sp.add_argument("--spool-dir")
    sp.set_defaults(func=cmd_sensor)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
