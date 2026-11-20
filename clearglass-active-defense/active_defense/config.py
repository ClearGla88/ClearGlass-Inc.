"""Load and cross-validate a deployment: configuration, inventory, rules, playbooks, secrets.

Loading fails closed. Any invalid file, missing secret, unknown reference or
weak key stops the process before it accepts an event or runs an action.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import ValidationError

from .assets import AssetRegistry
from .models import DefenseConfig, Inventory, Playbook, PrincipalConfig, RuleSet, SensorConfig

REQUIRED_PLAYBOOKS: tuple[str, ...] = (
    "PB-01-decoy-interaction",
    "PB-02-honeytoken-use",
    "PB-03-isolate-corroborated-host",
    "PB-04-lateral-movement-scope",
    "PB-05-ransomware-containment",
    "PB-06-false-positive",
    "PB-07-recovery",
    "PB-08-sensor-distrust",
)
MIN_SECRET_CHARS = 32


class ConfigError(Exception):
    """The deployment is invalid. The message names the file and the problem."""


@dataclass(frozen=True)
class Principal:
    principal: str
    role: str


@dataclass(frozen=True)
class Bundle:
    config: DefenseConfig
    config_path: Path
    base_dir: Path
    registry: AssetRegistry
    ruleset: RuleSet
    playbooks: dict[str, Playbook]
    sensors: dict[str, SensorConfig]
    sensor_keys: dict[str, bytes] = field(repr=False)
    principals_by_token_hash: dict[str, Principal] = field(repr=False)

    def resolve(self, value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else (self.base_dir / path).resolve()

    @property
    def database_path(self) -> Path:
        return self.resolve(self.config.database)

    @property
    def state_dir(self) -> Path:
        return self.resolve(self.config.state_dir)

    @property
    def emergency_stop_file(self) -> Path:
        return self.state_dir / "EMERGENCY_STOP"


def _read_yaml(path: Path) -> object:
    try:
        with path.open("r", encoding="utf-8") as fh:
            return yaml.safe_load(fh)
    except FileNotFoundError as exc:
        raise ConfigError(f"{path}: file not found") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: invalid YAML: {exc}") from exc


def _validate(model: type, data: object, path: Path):
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = ".".join(str(p) for p in first["loc"]) or "(root)"
        raise ConfigError(f"{path}: {loc}: {first['msg']} ({exc.error_count()} error(s))") from exc


def load_secret(*, env: str | None, file: str | None, base_dir: Path, what: str) -> str:
    if env is not None:
        value = os.environ.get(env, "")
        source = f"environment variable {env}"
    else:
        assert file is not None
        path = Path(file) if Path(file).is_absolute() else (base_dir / file)
        try:
            value = path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise ConfigError(f"{what}: secret file {path} not found (create it with 'defense.py init-secrets')") from exc
        source = f"file {path}"
    value = value.strip()
    if len(value) < MIN_SECRET_CHARS:
        raise ConfigError(f"{what}: secret from {source} is missing or shorter than {MIN_SECRET_CHARS} characters")
    return value


def _principal_hash(p: PrincipalConfig, base_dir: Path) -> str:
    if p.token_sha256 is not None:
        return p.token_sha256
    token = load_secret(env=p.token_env, file=p.token_file, base_dir=base_dir, what=f"principal {p.principal}")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def load_playbooks(directory: Path) -> dict[str, Playbook]:
    if not directory.is_dir():
        raise ConfigError(f"{directory}: playbook directory not found")
    books: dict[str, Playbook] = {}
    for path in sorted(directory.glob("*.yaml")):
        pb = _validate(Playbook, _read_yaml(path), path)
        if pb.id in books:
            raise ConfigError(f"{path}: duplicate playbook id {pb.id}")
        books[pb.id] = pb
    missing = [p for p in REQUIRED_PLAYBOOKS if p not in books]
    if missing:
        raise ConfigError(f"{directory}: missing required playbooks {missing}")
    return books


def cross_validate(cfg: DefenseConfig, registry: AssetRegistry, ruleset: RuleSet, books: dict[str, Playbook]) -> None:
    for signal, pb_id in ruleset.signal_playbooks.items():
        pb = books.get(pb_id)
        if pb is None:
            raise ConfigError(f"rules: signal {signal} names unknown playbook {pb_id}")
        if pb.action_types & {"propose_isolation", "propose_release"}:
            raise ConfigError(
                f"rules: signal playbook {pb_id} proposes containment; a single signal never may"
            )
    for cor in ruleset.correlations:
        if cor.playbook not in books:
            raise ConfigError(f"rules: correlation {cor.id} names unknown playbook {cor.playbook}")
        pb = books[cor.playbook]
        if "propose_isolation" in pb.action_types and not cor.requires_verified_asset:
            raise ConfigError(f"rules: correlation {cor.id} proposes isolation without a verified asset")
    for pb_id in cfg.response.enforce_preauthorized_playbooks:
        pb = books.get(pb_id)
        if pb is None or "propose_isolation" not in pb.action_types:
            raise ConfigError(f"response: {pb_id} is not an isolation playbook and cannot be preauthorized")
    for sensor in cfg.sensors:
        if sensor.host_asset_id and registry.get(sensor.host_asset_id) is None:
            raise ConfigError(f"sensor {sensor.id}: host_asset_id {sensor.host_asset_id} is not in the inventory")
    if "PB-07-recovery" in books and not books["PB-07-recovery"].recovery_criteria:
        raise ConfigError("PB-07-recovery must list recovery criteria")


def load_bundle(config_path: str | Path, *, load_sensor_keys: bool = True, load_principals: bool = True) -> Bundle:
    """Load everything. The worker passes load_sensor_keys=False: it never needs them."""
    path = Path(config_path).resolve()
    base = path.parent
    cfg: DefenseConfig = _validate(DefenseConfig, _read_yaml(path), path)

    def res(value: str) -> Path:
        p = Path(value)
        return p if p.is_absolute() else (base / p).resolve()

    inv_path = res(cfg.assets_file)
    inventory: Inventory = _validate(Inventory, _read_yaml(inv_path), inv_path)
    registry = AssetRegistry(inventory)
    rules_path = res(cfg.rules_file)
    ruleset: RuleSet = _validate(RuleSet, _read_yaml(rules_path), rules_path)
    books = load_playbooks(res(cfg.playbooks_dir))
    cross_validate(cfg, registry, ruleset, books)

    keys: dict[str, bytes] = {}
    if load_sensor_keys:
        for s in cfg.sensors:
            keys[s.id] = load_secret(env=s.key_env, file=s.key_file, base_dir=base, what=f"sensor {s.id}").encode()
    principals: dict[str, Principal] = {}
    if load_principals:
        for p in cfg.principals:
            digest = _principal_hash(p, base)
            if digest in principals:
                raise ConfigError(f"principal {p.principal}: token is shared with another principal")
            principals[digest] = Principal(p.principal, p.role)
    return Bundle(
        config=cfg,
        config_path=path,
        base_dir=base,
        registry=registry,
        ruleset=ruleset,
        playbooks=books,
        sensors={s.id: s for s in cfg.sensors},
        sensor_keys=keys,
        principals_by_token_hash=principals,
    )
