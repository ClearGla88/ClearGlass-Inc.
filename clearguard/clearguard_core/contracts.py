"""Hazard-specific detector contracts (spec section 7).

A detector may be called validated only when every contract field is filled in
by review: acceptance criteria, controlled-exercise evidence, an owner, and an
approving reviewer. This module never supplies default reliability or timing
targets; a missing value is a gap, not a default.
"""

from __future__ import annotations

import json
import os

from .alerts import TEMPLATES
from .events import CATEGORIES

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
CONTRACTS_PATH = os.path.join(DATA_DIR, "detector_contracts.json")

FIELDS = (
    "detector_id", "hazard", "implementation", "intended_use", "required_inputs", "quality_limits",
    "operating_envelope", "failure_modes", "trigger_rule", "clearing_rule", "max_event_age_s",
    "timing_budget_ms", "alert_template", "acceptance_criteria", "degraded_behavior", "test_evidence",
    "owner", "review", "calibrated_confidence",
)
IMPLEMENTATIONS = {"app_state", "host_platform", "not_implemented"}
EVIDENCE_KINDS = {"controlled_exercise", "integration_test"}


def _empty(value: object) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _placeholder(value: object) -> bool:
    return isinstance(value, str) and value.strip().startswith("[")


def structure_problems(contract: dict) -> list[str]:
    """Problems that make the contract file itself unusable."""
    cid = contract.get("detector_id", "?")
    problems = [f"{cid}: missing field {f}" for f in FIELDS if f not in contract]
    problems += [f"{cid}: unknown field {f}" for f in sorted(set(contract) - set(FIELDS) - {"_comment"})]
    if problems:
        return problems
    if contract["hazard"] not in CATEGORIES:
        problems.append(f"{cid}: hazard '{contract['hazard']}' is not a supported category")
    if contract["alert_template"] not in TEMPLATES:
        problems.append(f"{cid}: alert_template '{contract['alert_template']}' is not a pre-approved template")
    if contract["implementation"] not in IMPLEMENTATIONS:
        problems.append(f"{cid}: implementation must be one of {sorted(IMPLEMENTATIONS)}")
    if not isinstance(contract["calibrated_confidence"], bool):
        problems.append(f"{cid}: calibrated_confidence must be true or false")
    return problems


def validation_gaps(contract: dict) -> list[str]:
    """Everything that stops this contract from supporting a 'validated' claim."""
    gaps: list[str] = []
    for name in FIELDS:
        value = contract.get(name)
        if name == "calibrated_confidence":
            continue
        if _empty(value) or _placeholder(value):
            gaps.append(f"{name} not set by review")
    if contract.get("implementation") == "not_implemented":
        gaps.append("no implementation in this build")
    criteria = contract.get("acceptance_criteria") or {}
    if isinstance(criteria, dict):
        for key in ("missed_event_rate_max", "false_alerts_per_hour_max", "basis"):
            if _empty(criteria.get(key)) or _placeholder(criteria.get(key)):
                gaps.append(f"acceptance_criteria.{key} not set by review")
    evidence = contract.get("test_evidence") or []
    if isinstance(evidence, list):
        good = [
            e for e in evidence
            if isinstance(e, dict) and e.get("kind") in EVIDENCE_KINDS and e.get("reference")
            and isinstance(e.get("sample_size"), int) and e["sample_size"] > 0 and e.get("date")
        ]
        if not any(e["kind"] == "controlled_exercise" for e in good):
            gaps.append("no controlled-exercise evidence with a sample size")
    review = contract.get("review") or {}
    if not (isinstance(review, dict) and review.get("decision") == "approved"
            and review.get("reviewer") and not _placeholder(review.get("reviewer")) and review.get("date")):
        gaps.append("no approving review by an accountable reviewer")
    # De-duplicate while keeping order.
    return list(dict.fromkeys(gaps))


def is_validated(contract: dict) -> bool:
    return not structure_problems(contract) and not validation_gaps(contract)


def load_contracts(path: str = CONTRACTS_PATH) -> dict[str, dict]:
    with open(path, encoding="utf-8") as handle:
        raw = json.load(handle)
    if raw.get("schema") != "clearguard.contracts/1":
        raise ValueError("detector contracts: unknown schema")
    out: dict[str, dict] = {}
    problems: list[str] = []
    for contract in raw["contracts"]:
        problems += structure_problems(contract)
        if contract.get("detector_id") in out:
            problems.append(f"{contract['detector_id']}: duplicate detector_id")
        out[contract.get("detector_id", "?")] = contract
    if problems:
        raise ValueError("; ".join(problems))
    return out
