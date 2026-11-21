#!/usr/bin/env python3
"""Check that the Burlington exposure artifacts stay honest: no number without a source.

Validates the JSON files at the repository root that the Burlington local-visibility
program is planned and measured with:

  MISSION_OBJECTIVES.json     targets stay labelled as targets; guardrails stay in place
  priority_levers.json        every score equals impact*confidence*urgency/(effort*risk)
                              and ranks follow the scores
  baseline_metrics.json       a metric can be non-null only when its source is
                              collected, with an evidence reference and a timestamp;
                              quality figures match the source states
  competitor_intel.json       a competitor record needs an observation time and evidence
  geo_grid_baseline.json      the summary equals what tools/geo_grid.py computes from
                              the cells; proposed grids match their files
  local_opportunity_map.json  "verified" needs a first-party URL; no contact details

JSON is parsed strictly: duplicate keys and NaN/Infinity are errors.
Exit status: 0 when every file passes, 1 when any check fails, 2 on a usage error.
Standard library only.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

try:
    from tools import geo_grid
except ImportError:  # run as a script: tools/ itself is sys.path[0]
    import geo_grid  # type: ignore[no-redef]

FACTORS = ("expected_impact", "confidence", "urgency", "effort", "risk")
SOURCE_STATES = frozenset({"not_collected", "collected", "partial", "failed"})
HAS_DATA = frozenset({"collected", "partial"})
OPPORTUNITY_STATES = frozenset({"verified", "partially_verified", "unverified", "candidate",
                                "not_collected", "rejected"})
FIT_LEVELS = frozenset({"high", "medium", "low"})
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE = re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?!\d)")

# Which source must be collected before a baseline metric may hold a value.
METRIC_SOURCES: dict[str, dict[str, str]] = {
    "gbp": {"*": "google_business_profile"},
    "web": {
        "organic_sessions": "ga4", "local_organic_sessions": "ga4", "sessions_by_city": "ga4",
        "top_landing_pages": "ga4", "conversion_events": "ga4",
        "local_intent_queries": "search_console", "qualified_local_leads": "crm",
    },
    "social.instagram": {"*": "instagram"},
    "social.tiktok": {"*": "tiktok"},
    "social.linkedin": {"*": "linkedin"},
}
CONFIG_KEYS = frozenset({"local_scope"})


class ContractError(ValueError):
    pass


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def load_strict(path: Path) -> Any:
    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in pairs:
            if key in out:
                raise ContractError(f"duplicate JSON key {key!r}")
            out[key] = value
        return out

    def no_constants(token: str) -> Any:
        raise ContractError(f"non-finite number {token}")

    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=no_duplicates,
                          parse_constant=no_constants)
    except json.JSONDecodeError as exc:
        raise ContractError(f"invalid JSON: {exc}") from None


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def is_https(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("https://") and len(value) > len("https://")


def valid_date(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = date.fromisoformat(value[:10])
    except ValueError:
        return False
    return parsed <= datetime.now(timezone.utc).date() + timedelta(days=1)


def valid_timestamp(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    return parsed.tzinfo is not None


def present(value: Any) -> bool:
    """True when a metric slot holds data: a number, a non-empty string, or a non-empty collection."""
    if value is None:
        return False
    if isinstance(value, (list, dict, str)):
        return len(value) > 0
    return True


# --------------------------------------------------------------------------- #
# Checks: each returns a list of problems
# --------------------------------------------------------------------------- #

def check_mission(data: dict[str, Any], root: Path) -> list[str]:
    problems = []
    if data.get("status") != "targets_not_results":
        problems.append("status must stay 'targets_not_results': targets are not results")
    objectives = data.get("objectives")
    if not isinstance(objectives, list) or not objectives:
        return problems + ["objectives must be a non-empty list"]
    seen = set()
    for obj in objectives:
        oid = obj.get("id")
        if not oid or oid in seen:
            problems.append(f"objective id {oid!r} is missing or duplicated")
        seen.add(oid)
        for key in ("metric", "definition", "target", "owner", "minimum_evidence"):
            if not present(obj.get(key)):
                problems.append(f"objective {oid}: '{key}' is required")
        for key, value in (obj.get("target") or {}).items():
            if isinstance(value, bool) or (isinstance(value, (int, float)) and (not is_number(value) or value < 0)):
                problems.append(f"objective {oid}: target.{key} must be a non-negative finite number")
    prohibited = {str(p).lower() for p in (data.get("guardrails") or {}).get("prohibited", [])}
    for required in ("review gating", "fabricated reviews or locations"):
        if required not in prohibited:
            problems.append(f"guardrails.prohibited must keep {required!r}")
    for note in data.get("feasibility_notes", []):
        if not present(note.get("note")) or not is_https(note.get("source")):
            problems.append("each feasibility note needs 'note' text and an https 'source'")
    return problems


def check_levers(data: dict[str, Any], root: Path) -> list[str]:
    problems = []
    levers = data.get("levers")
    if not isinstance(levers, list) or not levers:
        return ["levers must be a non-empty list"]
    ids = set()
    for lever in levers:
        lid = lever.get("id")
        if not lid or lid in ids:
            problems.append(f"lever id {lid!r} is missing or duplicated")
        ids.add(lid)
        values = [lever.get(f) for f in FACTORS]
        if any(isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= 5 for v in values):
            problems.append(f"lever {lid}: {', '.join(FACTORS)} must be integers from 1 to 5")
            continue
        impact, confidence, urgency, effort, risk = values
        expected = round(impact * confidence * urgency / (effort * risk), 4)
        if not is_number(lever.get("score")) or abs(lever["score"] - expected) > 1e-4:
            problems.append(f"lever {lid}: score {lever.get('score')} should be {expected}")
        for key in ("action", "gate", "acceptance", "rationale"):
            if not present(lever.get(key)):
                problems.append(f"lever {lid}: '{key}' is required")
    ranked = sorted(levers, key=lambda lv: lv.get("rank") if isinstance(lv.get("rank"), int) else 10**9)
    if [lv.get("rank") for lv in ranked] != list(range(1, len(levers) + 1)):
        problems.append("ranks must run 1..n without gaps or repeats")
    scores = [lv.get("score") for lv in ranked]
    if all(is_number(s) for s in scores) and any(a < b - 1e-9 for a, b in zip(scores, scores[1:])):
        problems.append("ranks must follow scores from highest to lowest")
    return problems


def _group(data: dict[str, Any], dotted: str) -> dict[str, Any]:
    node: Any = data
    for part in dotted.split("."):
        node = node.get(part, {}) if isinstance(node, dict) else {}
    return node if isinstance(node, dict) else {}


def _negative(value: Any) -> bool:
    if is_number(value):
        return value < 0
    if isinstance(value, dict):
        return any(_negative(v) for v in value.values())
    if isinstance(value, list):
        return any(_negative(v) for v in value)
    return False


def check_baseline(data: dict[str, Any], root: Path) -> list[str]:
    problems = []
    sources = data.get("sources")
    if not isinstance(sources, dict) or not sources:
        return ["sources must be a non-empty object"]
    for name, src in sources.items():
        status = (src or {}).get("status")
        if status not in SOURCE_STATES:
            problems.append(f"source {name}: status must be one of {sorted(SOURCE_STATES)}")
        if status in HAS_DATA and not (present(src.get("evidence_ref")) and valid_timestamp(src.get("last_success_at"))):
            problems.append(f"source {name}: '{status}' needs evidence_ref and a last_success_at timestamp")
    for group, mapping in METRIC_SOURCES.items():
        for key, value in _group(data, group).items():
            if key in CONFIG_KEYS or not present(value):
                continue
            source = mapping.get(key) or mapping.get("*")
            if source is None:
                problems.append(f"{group}.{key} holds data but has no source mapping in the contract")
            elif (sources.get(source) or {}).get("status") not in HAS_DATA:
                problems.append(f"{group}.{key} holds data but source '{source}' is not collected")
            if _negative(value):
                problems.append(f"{group}.{key} contains a negative number")
    with_data = sorted(n for n, s in sources.items() if (s or {}).get("status") in HAS_DATA)
    missing = sorted(n for n, s in sources.items() if (s or {}).get("status") != "collected")
    quality = data.get("quality") or {}
    if sorted(quality.get("missing_required_sources") or []) != missing:
        problems.append(f"quality.missing_required_sources should be {missing}")
    ratio = round((len(sources) - len(missing)) / len(sources), 4)
    if quality.get("completeness_ratio") != ratio:
        problems.append(f"quality.completeness_ratio should be {ratio}")
    if quality.get("complete") is not (not missing):
        problems.append(f"quality.complete should be {not missing}")
    state = data.get("data_state")
    if (state == "not_collected") != (not with_data):
        problems.append("data_state must be 'not_collected' exactly when no external source has data")
    for section in ("repository_observations", "live_site_observations"):
        for key, obs in (data.get(section) or {}).items():
            if not isinstance(obs, dict) or "value" not in obs or not present(obs.get("evidence_ref")):
                problems.append(f"{section}.{key} needs 'value' and 'evidence_ref'")
            elif section == "live_site_observations" and not valid_date(obs.get("observed_at")):
                problems.append(f"{section}.{key} needs an observed_at date")
    return problems


def check_competitors(data: dict[str, Any], root: Path) -> list[str]:
    problems = []
    for result in data.get("keyword_results") or []:
        kw, status, competitors = result.get("keyword"), result.get("status"), result.get("competitors") or []
        if status not in ("not_collected", "collected"):
            problems.append(f"{kw}: status must be 'not_collected' or 'collected'")
        if status == "not_collected" and competitors:
            problems.append(f"{kw}: competitors listed but status is 'not_collected'")
        for comp in competitors:
            if not (present(comp.get("name")) and valid_timestamp(comp.get("observed_at"))
                    and isinstance(comp.get("evidence_refs"), list) and comp["evidence_refs"]):
                problems.append(f"{kw}: competitor {comp.get('name')!r} needs name, observed_at and evidence_refs")
    return problems


def check_grid(data: dict[str, Any], root: Path) -> list[str]:
    problems = []
    status = data.get("status")
    if status not in ("not_collected", "collected"):
        return ["status must be 'not_collected' or 'collected'"]
    if status == "not_collected":
        if data.get("cells"):
            problems.append("cells must be empty while status is 'not_collected'")
        for key in ("provider", "run_id", "observed_at"):
            if data.get(key) is not None:
                problems.append(f"{key} must be null while status is 'not_collected'")
    else:
        for key in ("provider", "run_id", "observed_at"):
            if not present(data.get(key)):
                problems.append(f"{key} is required for a collected run")
        if not present((data.get("grid_definition") or {}).get("sha256")):
            problems.append("a collected run needs grid_definition.sha256")
    try:
        expected = geo_grid.summarize(data)
    except geo_grid.GridError as exc:
        return problems + [f"cells: {exc}"]
    if data.get("summary") != expected:
        problems.append("summary does not match the cells; regenerate it with tools/geo_grid.py summarize")
    for proposal in data.get("proposed_grids") or []:
        file = root / str(proposal.get("file", ""))
        if proposal.get("status") != "proposed_not_approved" and not present(proposal.get("approved_by")):
            problems.append(f"proposed grid {proposal.get('file')}: an approved grid needs 'approved_by'")
        try:
            grid = geo_grid.load_json(file)
            geo_grid.validate_grid(grid)
        except (OSError, geo_grid.GridError, json.JSONDecodeError) as exc:
            problems.append(f"proposed grid {proposal.get('file')}: {exc}")
            continue
        if grid["sha256"] != proposal.get("sha256"):
            problems.append(f"proposed grid {proposal.get('file')}: sha256 does not match the file")
    return problems


def check_opportunities(data: dict[str, Any], root: Path) -> list[str]:
    problems = []
    text = json.dumps(data, ensure_ascii=False)
    if EMAIL.search(text) or PHONE.search(text):
        problems.append("contact details (emails or phone numbers) must not be stored in the opportunity map")
    seen = set()
    for opp in data.get("opportunities") or []:
        oid, status = opp.get("id"), opp.get("status")
        if not oid or oid in seen:
            problems.append(f"opportunity id {oid!r} is missing or duplicated")
        seen.add(oid)
        if status not in OPPORTUNITY_STATES:
            problems.append(f"{oid}: status must be one of {sorted(OPPORTUNITY_STATES)}")
        if "fit" in opp and opp["fit"] not in FIT_LEVELS:
            problems.append(f"{oid}: fit must be high, medium or low")
        evidence = opp.get("evidence") or []
        for item in evidence:
            if not (is_https(item.get("url")) and item.get("publisher") in ("first_party", "secondary")
                    and valid_date(item.get("retrieved")) and present(item.get("method"))):
                problems.append(f"{oid}: evidence needs an https url, publisher, retrieved date and method")
        if status == "verified":
            if not is_https(opp.get("official_url")):
                problems.append(f"{oid}: 'verified' needs an https official_url")
            if not any(item.get("publisher") == "first_party" for item in evidence):
                problems.append(f"{oid}: 'verified' needs first-party evidence")
        if status == "partially_verified" and not evidence:
            problems.append(f"{oid}: 'partially_verified' needs at least one evidence item")
    return problems


ARTIFACTS: dict[str, Callable[[dict[str, Any], Path], list[str]]] = {
    "MISSION_OBJECTIVES.json": check_mission,
    "priority_levers.json": check_levers,
    "baseline_metrics.json": check_baseline,
    "competitor_intel.json": check_competitors,
    "geo_grid_baseline.json": check_grid,
    "local_opportunity_map.json": check_opportunities,
}


def check_all(root: Path) -> dict[str, list[str]]:
    results: dict[str, list[str]] = {}
    for name, check in ARTIFACTS.items():
        path = root / name
        try:
            data = load_strict(path)
        except FileNotFoundError:
            results[name] = ["file is missing"]
            continue
        except ContractError as exc:
            results[name] = [str(exc)]
            continue
        if not isinstance(data, dict):
            results[name] = ["expected a JSON object"]
            continue
        try:
            results[name] = check(data, root)
        except (ContractError, AttributeError, TypeError) as exc:
            results[name] = [f"malformed structure: {exc}"]
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    if not args.root.is_dir():
        print(f"exposure-contracts: {args.root} is not a directory", file=sys.stderr)
        return 2
    results = check_all(args.root)
    failed = 0
    for name, problems in results.items():
        if problems:
            failed += 1
            for problem in problems:
                print(f"FAIL  {name}: {problem}")
        else:
            print(f"PASS  {name}")
    print(f"exposure-contracts: {len(results) - failed} of {len(results)} artifacts pass")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
