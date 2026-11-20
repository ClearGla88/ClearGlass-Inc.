"""A PLAN-FIRST payload is a plan, not a result. This module keeps it that way.

A go-to-market plan arrives as one JSON document before any research has run. Most
of it is unknown, and the document has to say so. ``check_plan`` refuses a payload
that:

- has a field the contract does not define, or lacks one it does (fail closed);
- claims more confidence than its evidence supports;
- states a market size, a verified claim, or spend without a source or an approval;
- proposes an action without a named approver and a rollback plan;
- carries a credential-shaped string.

``readiness`` then answers one question: may the first cycle start? It may not until
the plan is approved and every decision in the approvals record is made.

Neither function authorizes anything. A status written in a file is not an approval:
the operator authorizes the first cycle by creating the plan-first mission through
the authenticated API or CLI, and the policy gate limits that mission to research,
analysis and drafts (``config/policy.json``, ``mission_modes.plan_first``).

stdlib only, apart from the secret patterns shared with the audit ledger.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from audit_ledger.canonical import find_secrets

CONFIDENCE = ("INSUFFICIENT", "LOW", "MEDIUM", "HIGH")
LEVELS = ("LOW", "MEDIUM", "HIGH")
APPROVAL_STATES = ("PENDING", "APPROVED", "REJECTED", "EXPIRED")
CLASSIFICATIONS = ("VERIFIED", "INFERENCE", "ASSUMPTION")
NOT_ESTABLISHED = "NOT ESTABLISHED"

# Field -> expected type, or an enum tuple, or a nested schema. A list schema is [item].
SCHEMA: dict[str, Any] = {
    "meta": {
        "company": str,
        "product": str,
        "market": str,
        "geography": str,
        "revenue_model": str,
        "analysis_date": "date",
        "next_review_date": "date",
        "overall_confidence": CONFIDENCE,
        "evidence_quality_score": int,
    },
    "decision_frame": {
        "decision_statement": str,
        "decision_owner": str,
        "decision_deadline": "date",
        "success_metric": str,
        "baseline": str,
        "target_threshold": str,
        "reversibility": ("REVERSIBLE", "PARTIALLY_REVERSIBLE", "IRREVERSIBLE"),
        "risk_tolerance": LEVELS,
        "exclusions": [str],
        "kill_criteria": [str],
    },
    "executive_brief": {
        "bottom_line": str,
        "recommended_decision": str,
        "why_now": str,
        "confidence": CONFIDENCE,
        "expected_impact": str,
        "downside_if_wrong": str,
        "what_would_change_this_recommendation": str,
        "next_checkpoint": str,
    },
    "market_state": {
        "market_definition": str,
        "demand_direction": ("UNKNOWN", "GROWING", "STABLE", "DECLINING"),
        "growth_drivers": [str],
        "constraints": [str],
        "regulatory_risks": [str],
        "market_sizing": {
            "estimate": str,
            "method": str,
            "range": str,
            "confidence": CONFIDENCE,
            "limitations": [str],
        },
    },
    "competitive_landscape": [dict],
    "buyer_intelligence": {
        "segments": [{"segment": str, "hypothesis": str, "evidence_quality": CONFIDENCE}],
        "jobs_to_be_done": [str],
        "triggers": [str],
        "decision_criteria": [str],
        "objections": [str],
        "alternatives": [str],
        "buying_committee": [str],
    },
    "strategic_options": [
        {
            "option": str,
            "thesis": str,
            "evidence": [str],
            "expected_impact": str,
            "confidence": CONFIDENCE,
            "effort": LEVELS,
            "time_to_value": str,
            "downside_if_wrong": str,
            "kill_criteria": [str],
            "owner": str,
            "next_action": str,
            "deadline": "date",
        }
    ],
    "red_team": {
        "strongest_counterargument": str,
        "weak_evidence": [str],
        "alternative_explanations": [str],
        "bias_risks": [str],
        "falsification_tests": [str],
        "minimum_evidence_needed": [str],
        "decision_risk_if_wrong": str,
    },
    "evidence_ledger": [
        {
            "claim": str,
            "classification": CLASSIFICATIONS,
            "source_ids": [str],
            "supporting_excerpt": str,
            "conflict_resolution": str,
            "confidence": CONFIDENCE,
        }
    ],
    "source_register": [dict],
    "market_state_updates": [
        {
            "entity": str,
            "field": str,
            "prior_value": str,
            "new_value": str,
            "change_type": ("NEW", "CHANGED", "REMOVED"),
            "materiality": LEVELS,
            "evidence": [str],
        }
    ],
    "proposed_actions": [
        {
            "action": str,
            "channel": str,
            "recipient_or_platform": str,
            "draft_content": str,
            "estimated_cost": str,
            "approval_required": bool,
            "approver": str,
            "rollback_plan": str,
        }
    ],
    "data_gaps": [str],
    "open_questions": [str],
    "audit": {
        "agents_executed": [str],
        "tools_used": [str],
        "spend_to_date": str,
        "human_review_required": bool,
        "reviewer": str,
        "approval_status": APPROVAL_STATES,
    },
}

APPROVALS_SCHEMA: dict[str, Any] = {
    "plan": str,
    "note": str,
    "required_before_first_cycle": [
        {
            "id": str,
            "question": str,
            "status": ("PENDING", "DECIDED"),
            "decision": (str, type(None)),
            "decided_by": (str, type(None)),
            "decided_at": (str, type(None)),
        }
    ],
}

_MONEY = re.compile(r"^\$(\d{1,3}(?:,\d{3})*|\d+)(?:\.\d{2})?$")
_DIGIT = re.compile(r"\d")


class PlanError(ValueError):
    """The file is missing, unreadable, or not a JSON object."""


def load_json(path: str | Path) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PlanError(f"{path}: file is missing") from exc
    except json.JSONDecodeError as exc:
        raise PlanError(f"{path}: not valid JSON ({exc})") from exc
    if not isinstance(data, dict):
        raise PlanError(f"{path}: top level must be an object")
    return data


def _parse_date(value: Any) -> date | None:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _cents(value: Any) -> int | None:
    if not isinstance(value, str):
        return None
    match = _MONEY.match(value.strip())
    if not match:
        return None
    return round(float(value.strip()[1:].replace(",", "")) * 100)


def _rank(level: str) -> int:
    return CONFIDENCE.index(level) if level in CONFIDENCE else -1


def _check_shape(value: Any, schema: Any, where: str, out: list[str]) -> None:
    """Exact-match validation: unknown keys and missing keys are both errors."""
    if isinstance(schema, dict):
        if not isinstance(value, dict):
            out.append(f"{where}: must be an object")
            return
        unknown = sorted(set(value) - set(schema))
        missing = sorted(set(schema) - set(value))
        if unknown:
            out.append(f"{where}: unknown field(s) {unknown}")
        if missing:
            out.append(f"{where}: missing field(s) {missing}")
        for key, sub in schema.items():
            if key in value:
                _check_shape(value[key], sub, f"{where}.{key}" if where else key, out)
    elif isinstance(schema, list):
        if not isinstance(value, list):
            out.append(f"{where}: must be a list")
            return
        for index, item in enumerate(value):
            _check_shape(item, schema[0], f"{where}[{index}]", out)
    elif schema == "date":
        if _parse_date(value) is None:
            out.append(f"{where}: must be a date as YYYY-MM-DD")
    elif isinstance(schema, tuple) and all(isinstance(option, str) for option in schema):
        if value not in schema:
            out.append(f"{where}: must be one of {list(schema)}")
    elif isinstance(schema, tuple):
        if not isinstance(value, schema):
            out.append(f"{where}: wrong type")
    elif schema is int:
        if not isinstance(value, int) or isinstance(value, bool):
            out.append(f"{where}: must be an integer")
    elif schema is bool:
        if not isinstance(value, bool):
            out.append(f"{where}: must be true or false")
    elif schema is str:
        if not isinstance(value, str):
            out.append(f"{where}: must be a string")
    elif schema is dict:
        if not isinstance(value, dict):
            out.append(f"{where}: must be an object")


def check_plan(plan: dict[str, Any]) -> list[str]:
    """Return every reason the plan is not acceptable. An empty list means it is."""
    out: list[str] = []
    _check_shape(plan, SCHEMA, "", out)
    if out:
        return out  # the rules below assume the shape

    hits = find_secrets(json.dumps(plan))
    if hits:
        out.append(f"plan carries credential-shaped text ({', '.join(sorted(set(hits)))}); remove it")

    meta, frame, audit = plan["meta"], plan["decision_frame"], plan["audit"]
    sources = plan["source_register"]
    source_ids = {str(s.get("id")) for s in sources if s.get("id")}

    # Dates
    analysis, review = _parse_date(meta["analysis_date"]), _parse_date(meta["next_review_date"])
    if analysis and review and review < analysis:
        out.append("meta.next_review_date is before meta.analysis_date")
    if not 0 <= meta["evidence_quality_score"] <= 100:
        out.append("meta.evidence_quality_score must be between 0 and 100")

    # Confidence cannot outrun evidence
    if not sources:
        if meta["overall_confidence"] != "INSUFFICIENT":
            out.append("meta.overall_confidence must be INSUFFICIENT while source_register is empty")
        if meta["evidence_quality_score"] != 0:
            out.append("meta.evidence_quality_score must be 0 while source_register is empty")
    if _rank(plan["executive_brief"]["confidence"]) > _rank(meta["overall_confidence"]):
        out.append("executive_brief.confidence is higher than meta.overall_confidence")

    sizing = plan["market_state"]["market_sizing"]
    if sizing["confidence"] == "INSUFFICIENT":
        for key in ("estimate", "range"):
            if _DIGIT.search(sizing[key]):
                out.append(f"market_state.market_sizing.{key} states a figure while its confidence is INSUFFICIENT")
    if plan["market_state"]["demand_direction"] != "UNKNOWN" and not sources:
        out.append("market_state.demand_direction must be UNKNOWN while source_register is empty")
    for index, item in enumerate(plan["competitive_landscape"]):
        if not (item.get("source_ids") or item.get("sources")):
            out.append(f"competitive_landscape[{index}]: a competitor entry needs at least one source")

    for index, claim in enumerate(plan["evidence_ledger"]):
        where = f"evidence_ledger[{index}]"
        missing = [sid for sid in claim["source_ids"] if sid not in source_ids]
        if missing:
            out.append(f"{where}: source id(s) {missing} are not in source_register")
        if claim["classification"] == "VERIFIED" and len(claim["source_ids"]) < 2:
            out.append(f"{where}: a VERIFIED claim needs at least two independent sources")
        if claim["classification"] == "VERIFIED" and not claim["supporting_excerpt"].strip():
            out.append(f"{where}: a VERIFIED claim needs a supporting excerpt")
        if claim["classification"] != "VERIFIED" and _rank(claim["confidence"]) > _rank("LOW"):
            out.append(f"{where}: an unverified claim cannot carry confidence above LOW")

    for index, segment in enumerate(plan["buyer_intelligence"]["segments"]):
        if not sources and segment["evidence_quality"] != "INSUFFICIENT":
            out.append(f"buyer_intelligence.segments[{index}]: evidence_quality must be INSUFFICIENT with no sources")

    for index, option in enumerate(plan["strategic_options"]):
        where = f"strategic_options[{index}]"
        if not option["evidence"] and _rank(option["confidence"]) > _rank("LOW"):
            out.append(f"{where}: confidence above LOW needs evidence")
        if not option["kill_criteria"]:
            out.append(f"{where}: needs at least one kill criterion")
        for key in ("owner", "next_action"):
            if not option[key].strip():
                out.append(f"{where}: {key} is required")

    if not frame["kill_criteria"]:
        out.append("decision_frame.kill_criteria must not be empty")
    if not frame["exclusions"]:
        out.append("decision_frame.exclusions must not be empty")
    if not frame["decision_owner"].strip():
        out.append("decision_frame.decision_owner is required")

    # Every proposed action waits for a named human
    for index, action in enumerate(plan["proposed_actions"]):
        where = f"proposed_actions[{index}]"
        if action["approval_required"] is not True:
            out.append(f"{where}: approval_required must be true")
        for key in ("approver", "rollback_plan"):
            if not action[key].strip():
                out.append(f"{where}: {key} is required")
        cost = _cents(action["estimated_cost"])
        if cost is None:
            out.append(f"{where}: estimated_cost must be a dollar amount such as $0 or $250.00")
        elif cost > 0 and audit["approval_status"] != "APPROVED":
            out.append(f"{where}: a plan that is not approved cannot propose spending")

    if audit["human_review_required"] is not True:
        out.append("audit.human_review_required must be true")
    if not audit["reviewer"].strip():
        out.append("audit.reviewer is required")
    spend = _cents(audit["spend_to_date"])
    if spend is None:
        out.append("audit.spend_to_date must be a dollar amount such as $0")
    if audit["approval_status"] != "APPROVED":
        if spend:
            out.append("audit.spend_to_date must be $0 until the plan is approved")
        if audit["tools_used"]:
            out.append("audit.tools_used must be empty until the plan is approved")
    return out


def check_approvals(record: dict[str, Any], plan_name: str | None = None) -> list[str]:
    out: list[str] = []
    _check_shape(record, APPROVALS_SCHEMA, "", out)
    if out:
        return out
    if plan_name is not None and record["plan"] != plan_name:
        out.append(f"approvals record is for {record['plan']!r}, not {plan_name!r}")
    seen: set[str] = set()
    for index, item in enumerate(record["required_before_first_cycle"]):
        where = f"required_before_first_cycle[{index}]"
        if not item["id"].strip() or item["id"] in seen:
            out.append(f"{where}: id missing or duplicated")
        seen.add(item["id"])
        decided = item["status"] == "DECIDED"
        fields = (item["decision"], item["decided_by"], item["decided_at"])
        if decided and not all(isinstance(f, str) and f.strip() for f in fields):
            out.append(f"{where}: a decided item needs decision, decided_by and decided_at")
        if decided and _parse_date(item["decided_at"]) is None:
            out.append(f"{where}: decided_at must be a date as YYYY-MM-DD")
        if not decided and any(f is not None for f in fields):
            out.append(f"{where}: a pending item must leave decision, decided_by and decided_at null")
    if not record["required_before_first_cycle"]:
        out.append("required_before_first_cycle must list at least one decision")
    return out


def readiness(plan: dict[str, Any], approvals: dict[str, Any] | None) -> list[str]:
    """Return what still blocks the first cycle. An empty list means nothing does.

    Call only on a plan and a record that passed their checks.
    """
    blockers: list[str] = []
    status = plan["audit"]["approval_status"]
    if status != "APPROVED":
        blockers.append(f"plan approval is {status}; the decision owner has not approved it")
    if approvals is None:
        blockers.append("no approvals record: the decisions required before the first cycle are not recorded")
    else:
        for item in approvals["required_before_first_cycle"]:
            if item["status"] != "DECIDED":
                blockers.append(f"decision pending: {item['id']}: {item['question']}")
    return blockers
