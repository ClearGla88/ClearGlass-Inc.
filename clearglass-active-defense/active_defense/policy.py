"""Deterministic containment policy.

Every check runs and is recorded, so a decision can be read back and explained.
No model output, free-text field, or captured attacker content is an input to
this module: it takes typed values only.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from .assets import Identity
from .config import Bundle
from .models import CRITICALITY_RANK, DECOY_SIGNALS, Asset, Playbook
from .store import Store
from .util import iso


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class Decision:
    outcome: str  # "deny" | "require_approval" | "preauthorized"
    checks: tuple[Check, ...]

    @property
    def failed(self) -> list[Check]:
        return [c for c in self.checks if not c.passed]

    def to_dict(self) -> dict:
        return {
            "outcome": self.outcome,
            "checks": [{"name": c.name, "passed": c.passed, "detail": c.detail} for c in self.checks],
        }


@dataclass(frozen=True)
class SignalView:
    signal_id: str
    signal: str
    sensor_id: str
    identity_asserting: bool
    trusted: bool


def emergency_stop_engaged(c: sqlite3.Connection, stop_file: Path) -> tuple[bool, str]:
    if stop_file.exists():
        return True, f"kill-switch file {stop_file} is present"
    state = Store.get_control(c, "emergency_stop", {"engaged": False})
    if state.get("engaged"):
        return True, f"engaged by {state.get('by')}: {state.get('reason')}"
    return False, "not engaged"


def circuit_open(c: sqlite3.Connection) -> tuple[bool, str]:
    state = Store.get_control(c, "circuit_breaker", {"open": False})
    if state.get("open"):
        return True, f"open since {state.get('since')}: {state.get('reason')}"
    return False, "closed"


def capacity(
    c: sqlite3.Connection, bundle: Bundle, *, now: datetime, case_id: str, exclude_action: str | None = None
) -> tuple[bool, str]:
    r = bundle.config.response
    active = c.execute("SELECT COUNT(*) FROM containments WHERE state='active'").fetchone()[0]
    inflight = c.execute(
        "SELECT COUNT(*) FROM actions WHERE kind='isolate' AND status IN ('queued','executing') AND action_id != ?",
        (exclude_action or "",),
    ).fetchone()[0]
    if active + inflight >= r.max_concurrent_isolations:
        return False, f"{active} active and {inflight} in-flight isolations; limit {r.max_concurrent_isolations}"
    hour_ago = iso(now - timedelta(hours=1))
    recent = c.execute(
        "SELECT COUNT(*) FROM actions WHERE kind='isolate' AND created_at >= ? "
        "AND status NOT IN ('cancelled','blocked','expired') AND action_id != ?",
        (hour_ago, exclude_action or ""),
    ).fetchone()[0]
    if recent >= r.max_actions_per_hour:
        return False, f"{recent} isolations in the last hour; limit {r.max_actions_per_hour}"
    per_case = c.execute(
        "SELECT COUNT(*) FROM actions WHERE kind='isolate' AND case_id=? "
        "AND status NOT IN ('cancelled','blocked','expired','failed') AND action_id != ?",
        (case_id, exclude_action or ""),
    ).fetchone()[0]
    if per_case >= r.max_isolations_per_case:
        return False, f"case already has {per_case} isolation(s); limit {r.max_isolations_per_case}"
    return True, f"{active} active, {inflight} in flight, {recent} in the last hour"


def evaluate_isolation(
    c: sqlite3.Connection,
    bundle: Bundle,
    *,
    now: datetime,
    case_id: str,
    identity: Identity,
    asset: Asset | None,
    playbook: Playbook,
    signals: list[SignalView],
) -> Decision:
    cfg = bundle.config
    checks: list[Check] = []

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append(Check(name, passed, detail))

    stopped, why = emergency_stop_engaged(c, bundle.emergency_stop_file)
    add("no_emergency_stop", not stopped, why)
    is_open, why = circuit_open(c)
    add("circuit_closed", not is_open, why)
    add("identity_verified", identity.verified, f"{identity.status}: {identity.reason}")
    add("asset_in_inventory", asset is not None, asset.asset_id if asset else "target is not an inventoried asset")
    if asset is None:
        for name in ("environment_in_scope", "not_protected", "asset_authorized_for_containment", "adapter_available"):
            add(name, False, "no inventoried asset")
    else:
        add(
            "environment_in_scope",
            asset.environment == cfg.environment,
            f"asset environment {asset.environment}, deployment environment {cfg.environment}",
        )
        excluded = asset.protected_class is not None and asset.protected_class in playbook.asset_exclusions
        add(
            "not_protected",
            asset.protected_class is None and not excluded,
            "not protected" if asset.protected_class is None else f"protected class {asset.protected_class}",
        )
        add(
            "asset_authorized_for_containment",
            asset.authorized_for_containment,
            "authorized in inventory" if asset.authorized_for_containment else "inventory does not authorize containment",
        )
        add("adapter_available", asset.adapter == cfg.response.adapter, f"asset adapter {asset.adapter}")

    trusted = [s for s in signals if s.trusted]
    present = {s.signal for s in trusted}
    req = playbook.required_evidence
    missing_all = [s for s in req.all_of if s not in present]
    any_ok = (not req.any_of) or bool(present & set(req.any_of))
    sensors = {s.sensor_id for s in trusted}
    endpoint = [s for s in trusted if s.signal not in DECOY_SIGNALS and s.identity_asserting]
    corroborated = not missing_all and any_ok and len(sensors) >= req.min_distinct_sensors and bool(endpoint)
    detail = (
        f"signals {sorted(present)} from {len(sensors)} sensor(s); "
        f"missing {missing_all or 'none'}; any_of {'met' if any_ok else 'unmet'}; "
        f"identity-asserting non-decoy signals {len(endpoint)}"
    )
    if not endpoint:
        detail += "; deception signals alone never authorize containment"
    add("evidence_corroborated", corroborated, detail)
    distrusted = sorted({s.sensor_id for s in signals if not s.trusted})
    add(
        "sensor_trusted",
        bool(trusted) and corroborated,
        "authorizing evidence is from trusted sensors"
        + (f"; ignored evidence from distrusted {distrusted}" if distrusted else ""),
    )
    contained = None
    if asset is not None:
        contained = c.execute(
            "SELECT case_id FROM containments WHERE target_asset_id=? AND state='active'", (asset.asset_id,)
        ).fetchone()
    add(
        "not_already_contained",
        contained is None,
        "no active containment" if contained is None else f"already contained under case {contained['case_id']}",
    )
    ok, why = capacity(c, bundle, now=now, case_id=case_id)
    add("within_rate_limits", ok, why)

    if any(not ch.passed for ch in checks):
        return Decision("deny", tuple(checks))

    assert asset is not None
    dependents = [bundle.registry.get(d) for d in asset.dependents]
    heavy = [d.asset_id for d in dependents if d is not None and CRITICALITY_RANK[d.criticality] >= 2]
    preauth = (
        cfg.mode == "enforce"
        and playbook.id in cfg.response.enforce_preauthorized_playbooks
        and CRITICALITY_RANK[asset.criticality] <= CRITICALITY_RANK[cfg.response.enforce_max_criticality]
        and not heavy
    )
    return Decision("preauthorized" if preauth else "require_approval", tuple(checks))
