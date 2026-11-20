"""Load and validate config/revenue.json.

The office refuses to start on a malformed revenue configuration, the same way it
refuses a malformed policy: an unknown qualification check, a consent table
without a "none" basis, or an offer missing a published fact is an error at
startup, never a permissive default at send time.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from revenue_ops.rules import CHECKS, PUBLISHED_OFFER_KEYS

SKU = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")
CONNECTOR_STATUSES = ("connected", "not_connected", "needs_reconnect", "unavailable")


class RevenueConfigError(ValueError):
    pass


@dataclass(frozen=True)
class RevenueConfig:
    version: str
    currency: str
    offers: dict[str, dict[str, Any]]
    lead_sources: dict[str, dict[str, Any]]
    consent_bases: dict[str, dict[str, Any]]
    consent_note: str
    contact_rules: dict[str, int]
    prohibited_phrases: tuple[str, ...]
    content_note: str
    threshold: int
    criteria: list[dict[str, Any]]
    max_per_cycle: int
    reconcile_after_hours: int
    connector_inventory: dict[str, Any]
    raw: dict[str, Any] = field(repr=False, default_factory=dict)


def _int(value: Any, lo: int, hi: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and lo <= value <= hi


def parse_revenue_config(raw: dict[str, Any]) -> RevenueConfig:
    problems: list[str] = []
    version = raw.get("version")
    if not isinstance(version, str) or not version:
        problems.append("version must be a non-empty string")
    currency = raw.get("currency")
    if currency != "CAD":
        problems.append("currency must be CAD (the only currency the offers are priced in)")

    offers: dict[str, dict[str, Any]] = {}
    for i, offer in enumerate(raw.get("offers") or []):
        where = f"offers[{i}]"
        missing = [k for k in (*PUBLISHED_OFFER_KEYS, "published_checked") if k not in offer]
        if missing:
            problems.append(f"{where}: missing {missing}")
            continue
        extra = set(offer) - {*PUBLISHED_OFFER_KEYS, "published_checked"}
        if extra:
            problems.append(f"{where}: unknown keys {sorted(extra)}")
        sku = offer["sku"]
        if not isinstance(sku, str) or not SKU.match(sku):
            problems.append(f"{where}: sku must be a lowercase slug")
        elif sku in offers:
            problems.append(f"{where}: duplicate sku {sku}")
        if not _int(offer["price_cents"], 1, 100_000_000):
            problems.append(f"{where}: price_cents must be a positive whole number")
        if offer["currency"] != currency:
            problems.append(f"{where}: currency must be {currency}")
        if offer["price_type"] != "one_time":
            problems.append(f"{where}: only one_time prices are supported in the first sales path")
        for key in ("scope", "published_at", "fulfillment_requirements"):
            value = offer[key]
            if not isinstance(value, list) or not value or not all(isinstance(v, str) and v for v in value):
                problems.append(f"{where}: {key} must be a non-empty list of text")
        for key in ("name", "summary"):
            if not isinstance(offer[key], str) or not offer[key].strip():
                problems.append(f"{where}: {key} must be text")
        if not isinstance(offer["assessment"], bool):
            problems.append(f"{where}: assessment must be true or false")
        try:
            date.fromisoformat(str(offer["published_checked"]))
        except ValueError:
            problems.append(f"{where}: published_checked must be a date")
        offers[str(sku)] = dict(offer)
    if not offers:
        problems.append("offers must list at least one offer")

    sources = raw.get("lead_sources") or {}
    if not isinstance(sources, dict) or not sources:
        problems.append("lead_sources must not be empty")
    for sid, spec in sources.items():
        if not isinstance(spec, dict) or not spec.get("label") or not spec.get("ref_hint"):
            problems.append(f"lead_sources.{sid}: needs label and ref_hint")

    bases = raw.get("consent_bases") or {}
    if "none" not in bases or bases["none"].get("allows_first_contact") is not False:
        problems.append("consent_bases must define 'none' with allows_first_contact false")
    for bid, spec in bases.items():
        if not isinstance(spec, dict) or not spec.get("label") or not spec.get("law"):
            problems.append(f"consent_bases.{bid}: needs label and law")
            continue
        if not isinstance(spec.get("allows_first_contact"), bool):
            problems.append(f"consent_bases.{bid}: allows_first_contact must be true or false")
        age = spec.get("max_age_days")
        if age is not None and not _int(age, 1, 3650):
            problems.append(f"consent_bases.{bid}: max_age_days must be null or 1-3650")

    rules = raw.get("contact_rules") or {}
    contact_rules: dict[str, int] = {}
    for key, lo, hi in (("max_messages_per_contact_per_30_days", 1, 20), ("min_hours_between_messages", 0, 720)):
        if not _int(rules.get(key), lo, hi):
            problems.append(f"contact_rules.{key} must be {lo}-{hi}")
        else:
            contact_rules[key] = rules[key]

    content = raw.get("content_policy") or {}
    phrases = content.get("prohibited_phrases")
    if not isinstance(phrases, list) or not phrases or not all(isinstance(p, str) and p.strip() for p in phrases):
        problems.append("content_policy.prohibited_phrases must be a non-empty list of text")
        phrases = []

    qual = raw.get("qualification") or {}
    threshold = qual.get("threshold")
    if not _int(threshold, 0, 100):
        problems.append("qualification.threshold must be 0-100")
    criteria = qual.get("criteria") or []
    seen: set[str] = set()
    for i, c in enumerate(criteria):
        where = f"qualification.criteria[{i}]"
        if c.get("check") not in CHECKS:
            problems.append(f"{where}: unknown check {c.get('check')!r}")
        if not c.get("id") or c["id"] in seen:
            problems.append(f"{where}: id missing or duplicated")
        seen.add(str(c.get("id")))
        if not _int(c.get("points"), 0, 100) or not isinstance(c.get("required"), bool) or not c.get("label"):
            problems.append(f"{where}: needs points 0-100, required true/false, and a label")
    if not criteria:
        problems.append("qualification.criteria must not be empty")

    max_per_cycle = (raw.get("cycle") or {}).get("max_opportunities_per_cycle")
    if not _int(max_per_cycle, 1, 100):
        problems.append("cycle.max_opportunities_per_cycle must be 1-100")
    reconcile = raw.get("release_reconcile_after_hours")
    if not _int(reconcile, 1, 720):
        problems.append("release_reconcile_after_hours must be 1-720")

    inventory = raw.get("connector_inventory") or {}
    try:
        date.fromisoformat(str(inventory.get("checked_at")))
    except ValueError:
        problems.append("connector_inventory.checked_at must be a date")
    for i, c in enumerate(inventory.get("connectors") or []):
        if not c.get("id") or not c.get("name") or c.get("status") not in CONNECTOR_STATUSES:
            problems.append(f"connector_inventory.connectors[{i}]: needs id, name and a status in {CONNECTOR_STATUSES}")

    if problems:
        raise RevenueConfigError("config/revenue.json: " + "; ".join(problems))
    return RevenueConfig(
        version=str(version),
        currency=str(currency),
        offers=offers,
        lead_sources=dict(sources),
        consent_bases=dict(bases),
        consent_note=str(raw.get("consent_note", "")),
        contact_rules=contact_rules,
        prohibited_phrases=tuple(phrases),
        content_note=str(content.get("note", "")),
        threshold=int(threshold),
        criteria=list(criteria),
        max_per_cycle=int(max_per_cycle),
        reconcile_after_hours=int(reconcile),
        connector_inventory=dict(inventory),
        raw=raw,
    )


def load_revenue_config(path: str | Path) -> RevenueConfig:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RevenueConfigError(f"missing {path}") from exc
    except json.JSONDecodeError as exc:
        raise RevenueConfigError(f"{path}: invalid JSON ({exc})") from exc
    return parse_revenue_config(raw)
