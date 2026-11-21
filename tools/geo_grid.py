#!/usr/bin/env python3
"""Plan, import, summarize, and compare local-pack geo-grid rank runs.

This tool never queries Google. Rank data comes from a rank-tracking provider's
export, which a person downloads and passes in. Scraping Google Maps results is
excluded on purpose: the Google Maps Platform policies forbid exporting or
scraping Maps content outside the Services.

Subcommands:
  plan       write a grid definition (odd N x N points around a centre)
  import     turn a provider CSV export into a run file bound to one grid
  summarize  recompute green-cell counts and rank buckets for a run file
  compare    compare two runs on matched cells only; refuses to compare runs
             taken on different grids, keyword sets, thresholds, or providers

Semantics, shared with tools/exposure_contracts.py:
  - A cell is one (keyword, grid point) pair.
  - "Successful" cells are ranked cells plus not_found cells (the provider
    looked and the business was not in the results it checked).
  - provider_error and not_collected cells are failures. They are reported
    but never counted in a rate's denominator, and never as red cells.
  - green_cell_rate = green_cells / successful_cells, or null when there are
    no successful cells. Null is never written as zero.

Exit status: 0 on success, 1 when inputs fail validation, 2 on a usage error.
Standard library only.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import statistics
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.1.0"
EARTH_RADIUS_KM = 6371.0088  # IUGG mean Earth radius
DEFAULT_THRESHOLD = 3
MISSING_REASONS = ("not_found", "provider_error", "not_collected")
SUCCESS_REASONS = frozenset({"not_found"})
# Only unambiguous spellings are accepted. Anything else ("-", "x", "n/a") fails
# closed, because providers use those marks for different things.
NOT_FOUND_TOKENS = frozenset({"not found", "not_found", "notfound", "nf"})
ERROR_TOKENS = frozenset({"error", "failed", "fail", "blocked", "provider_error"})
OK_STATUS_TOKENS = frozenset({"", "ok", "ranked", "found"})
BUCKETS = ("top_3", "rank_4_10", "rank_11_20", "over_20_or_not_found")


class GridError(ValueError):
    """Input that fails validation. The message says what to fix."""


# --------------------------------------------------------------------------- #
# Geometry
# --------------------------------------------------------------------------- #

def destination(lat: float, lng: float, bearing_deg: float, distance_km: float) -> tuple[float, float]:
    """Great-circle destination point from a start, bearing, and distance."""
    phi1 = math.radians(lat)
    lam1 = math.radians(lng)
    theta = math.radians(bearing_deg)
    delta = distance_km / EARTH_RADIUS_KM
    phi2 = math.asin(math.sin(phi1) * math.cos(delta) + math.cos(phi1) * math.sin(delta) * math.cos(theta))
    lam2 = lam1 + math.atan2(
        math.sin(theta) * math.sin(delta) * math.cos(phi1),
        math.cos(delta) - math.sin(phi1) * math.sin(phi2),
    )
    lng2 = (math.degrees(lam2) + 540.0) % 360.0 - 180.0
    return math.degrees(phi2), lng2


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _check_coordinate(lat: float, lng: float) -> None:
    if not (math.isfinite(lat) and math.isfinite(lng)) or not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise GridError(f"invalid coordinate ({lat}, {lng})")


def plan_grid(name: str, lat: float, lng: float, size: int, spacing_km: float,
              centre_source: str | None = None) -> dict[str, Any]:
    """Return a grid definition: size x size points, row 0 is the north edge."""
    _check_coordinate(lat, lng)
    if not name or not name.replace("-", "").replace("_", "").isalnum():
        raise GridError("grid name must be letters, digits, '-' or '_'")
    if size < 3 or size > 25 or size % 2 == 0:
        raise GridError("size must be an odd number from 3 to 25, so the centre is a grid point")
    if not (math.isfinite(spacing_km) and 0.1 <= spacing_km <= 25.0):
        raise GridError("spacing_km must be between 0.1 and 25")
    half = size // 2
    points = []
    for row in range(size):
        north_km = (half - row) * spacing_km
        bearing_ns = 0.0 if north_km >= 0 else 180.0
        row_lat, row_lng = destination(lat, lng, bearing_ns, abs(north_km))
        for col in range(size):
            east_km = (col - half) * spacing_km
            bearing_ew = 90.0 if east_km >= 0 else 270.0
            p_lat, p_lng = destination(row_lat, row_lng, bearing_ew, abs(east_km))
            points.append({
                "id": f"r{row}c{col}",
                "row": row,
                "col": col,
                "lat": round(p_lat, 6),
                "lng": round(p_lng, 6),
            })
    body = {
        "name": name,
        "centre": {"lat": round(lat, 6), "lng": round(lng, 6), "source": centre_source},
        "size": size,
        "spacing_km": spacing_km,
        "span_km": round(spacing_km * (size - 1), 3),
        "points": points,
    }
    return {"schema_version": SCHEMA_VERSION, **body, "sha256": grid_sha256(body)}


def grid_sha256(grid: dict[str, Any]) -> str:
    """Hash of the fields that make two runs comparable (not the name or source)."""
    centre = grid["centre"]
    return sha256_hex(canonical_json({
        "centre": [centre["lat"], centre["lng"]],
        "size": grid["size"],
        "spacing_km": grid["spacing_km"],
        "points": [[p["id"], p["lat"], p["lng"]] for p in grid["points"]],
    }))


def validate_grid(grid: dict[str, Any]) -> None:
    for key in ("name", "centre", "size", "spacing_km", "points", "sha256"):
        if key not in grid:
            raise GridError(f"grid definition is missing '{key}'")
    if grid["sha256"] != grid_sha256(grid):
        raise GridError("grid sha256 does not match its points; regenerate it with 'plan'")
    if len(grid["points"]) != grid["size"] ** 2:
        raise GridError("grid point count does not equal size squared")


# --------------------------------------------------------------------------- #
# Import
# --------------------------------------------------------------------------- #

def parse_rank(raw: str, blank_as: str | None) -> tuple[int | None, str | None, int | None]:
    """Return (rank, missing_reason, max_checked) for one provider rank value."""
    value = (raw or "").strip().lower()
    if value == "":
        if blank_as is None:
            raise GridError("blank rank value: pass --blank-as not_found or --blank-as provider_error "
                            "after checking what the provider's blank means")
        return None, blank_as, None
    if value in ERROR_TOKENS:
        return None, "provider_error", None
    if value in NOT_FOUND_TOKENS:
        return None, "not_found", None
    for prefix, suffix in ((">", ""), ("", "+")):
        if value.startswith(prefix) and value.endswith(suffix) and (prefix or suffix):
            core = value[len(prefix):len(value) - len(suffix)] if suffix else value[len(prefix):]
            if core.isdigit() and int(core) >= 1:
                return None, "not_found", int(core)
    if value.isdigit() and int(value) >= 1:
        return int(value), None, None
    raise GridError(f"unrecognised rank value {raw!r}")


def _parse_timestamp(text: str) -> str:
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise GridError(f"observed_at must be an ISO 8601 timestamp: {exc}") from None
    if parsed.tzinfo is None:
        raise GridError("observed_at must include a UTC offset, e.g. 2026-12-01T14:00:00-05:00")
    return parsed.isoformat()


def nearest_point(grid: dict[str, Any], lat: float, lng: float) -> dict[str, Any]:
    best = min(grid["points"], key=lambda p: haversine_km(lat, lng, p["lat"], p["lng"]))
    distance = haversine_km(lat, lng, best["lat"], best["lng"])
    tolerance = grid["spacing_km"] * 0.25
    if distance > tolerance:
        raise GridError(f"row at ({lat}, {lng}) is {distance:.3f} km from the nearest grid point; "
                        f"tolerance is {tolerance:.3f} km. Was the export taken on this grid?")
    return best


def import_csv(grid: dict[str, Any], csv_bytes: bytes, *, provider: str, observed_at: str,
               run_id: str, source_name: str, column_map: dict[str, str] | None = None,
               blank_as: str | None = None, threshold: int = DEFAULT_THRESHOLD,
               brand: str | None = None) -> dict[str, Any]:
    """Build a run file from a provider export. Fails closed on anything ambiguous."""
    validate_grid(grid)
    try:
        csv_text = csv_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise GridError("CSV is not UTF-8; re-export it as UTF-8") from None
    if not provider.strip():
        raise GridError("provider is required")
    if blank_as is not None and blank_as not in ("not_found", "provider_error"):
        raise GridError("--blank-as must be not_found or provider_error")
    if threshold < 1:
        raise GridError("threshold must be at least 1")
    columns = {"keyword": "keyword", "rank": "rank", "point_id": "point_id",
               "lat": "lat", "lng": "lng", "status": "status"}
    columns.update(column_map or {})
    reader = csv.DictReader(io.StringIO(csv_text, newline=""))
    headers = set(reader.fieldnames or ())
    for required in ("keyword", "rank"):
        if columns[required] not in headers:
            raise GridError(f"CSV has no '{columns[required]}' column for {required}")
    by_id = {p["id"]: p for p in grid["points"]}
    use_ids = columns["point_id"] in headers
    if not use_ids and not {columns["lat"], columns["lng"]} <= headers:
        raise GridError("CSV needs a point_id column, or lat and lng columns")

    observed: dict[tuple[str, str], dict[str, Any]] = {}
    keywords: list[str] = []
    rows = 0
    for line_no, row in enumerate(reader, start=2):
        rows += 1
        keyword = " ".join((row.get(columns["keyword"]) or "").split())
        if not keyword:
            raise GridError(f"line {line_no}: empty keyword")
        if use_ids:
            point = by_id.get((row.get(columns["point_id"]) or "").strip())
            if point is None:
                raise GridError(f"line {line_no}: point_id is not in the grid")
        else:
            try:
                lat = float(row[columns["lat"]])
                lng = float(row[columns["lng"]])
            except (TypeError, ValueError):
                raise GridError(f"line {line_no}: lat/lng are not numbers") from None
            _check_coordinate(lat, lng)
            point = nearest_point(grid, lat, lng)
        status = (row.get(columns["status"]) or "").strip().lower()
        if status in ERROR_TOKENS:
            rank, reason, max_checked = None, "provider_error", None
        elif status in NOT_FOUND_TOKENS:
            rank, reason, max_checked = None, "not_found", None
        elif status in OK_STATUS_TOKENS:
            try:
                rank, reason, max_checked = parse_rank(row.get(columns["rank"]) or "", blank_as)
            except GridError as exc:
                raise GridError(f"line {line_no}: {exc}") from None
        else:
            raise GridError(f"line {line_no}: unrecognised status {status!r}")
        key = (keyword, point["id"])
        if key in observed:
            raise GridError(f"line {line_no}: duplicate row for keyword {keyword!r} at {point['id']}")
        if keyword not in keywords:
            keywords.append(keyword)
        observed[key] = {"keyword": keyword, "point_id": point["id"], "lat": point["lat"],
                         "lng": point["lng"], "rank": rank, "missing_reason": reason,
                         "max_checked": max_checked}
    if not observed:
        raise GridError("CSV has no data rows")

    cells = []
    for keyword in keywords:
        for point in grid["points"]:
            cells.append(observed.get((keyword, point["id"])) or {
                "keyword": keyword, "point_id": point["id"], "lat": point["lat"], "lng": point["lng"],
                "rank": None, "missing_reason": "not_collected", "max_checked": None,
            })
    run = {
        "schema_version": SCHEMA_VERSION,
        "brand": brand,
        "status": "collected",
        "provider": provider.strip(),
        "run_id": run_id,
        "observed_at": _parse_timestamp(observed_at),
        "grid_definition": {k: grid[k] for k in ("name", "centre", "size", "spacing_km", "span_km", "sha256")
                            if k in grid},
        "keywords": keywords,
        "green_rank_threshold": threshold,
        "rank_semantics": {"green_max_position": threshold, "not_found_value": None,
                           "missing_reasons": list(MISSING_REASONS)},
        "source": {"file_name": source_name, "sha256": sha256_hex(csv_bytes), "rows": rows},
        "cells": cells,
    }
    run["summary"] = summarize(run)
    return run


# --------------------------------------------------------------------------- #
# Summaries and comparison
# --------------------------------------------------------------------------- #

def validate_cell(cell: dict[str, Any], keywords: list[str]) -> None:
    rank = cell.get("rank")
    reason = cell.get("missing_reason")
    where = f"cell {cell.get('keyword')!r}@{cell.get('point_id')}"
    if cell.get("keyword") not in keywords:
        raise GridError(f"{where}: keyword is not in the run's keyword list")
    if (rank is None) == (reason is None):
        raise GridError(f"{where}: needs exactly one of rank or missing_reason")
    if rank is not None and (isinstance(rank, bool) or not isinstance(rank, int) or rank < 1):
        raise GridError(f"{where}: rank must be an integer >= 1")
    if reason is not None and reason not in MISSING_REASONS:
        raise GridError(f"{where}: missing_reason must be one of {', '.join(MISSING_REASONS)}")


def _bucket(cell: dict[str, Any]) -> str | None:
    rank = cell.get("rank")
    if rank is None:
        return "over_20_or_not_found" if cell.get("missing_reason") == "not_found" else None
    if rank <= 3:
        return "top_3"
    if rank <= 10:
        return "rank_4_10"
    if rank <= 20:
        return "rank_11_20"
    return "over_20_or_not_found"


def _counts(cells: list[dict[str, Any]], threshold: int) -> dict[str, Any]:
    ranked = [c for c in cells if c.get("rank") is not None]
    not_found = [c for c in cells if c.get("missing_reason") in SUCCESS_REASONS]
    successful = len(ranked) + len(not_found)
    green = sum(1 for c in ranked if c["rank"] <= threshold)
    buckets = dict.fromkeys(BUCKETS, 0)
    for cell in cells:
        name = _bucket(cell)
        if name:
            buckets[name] += 1
    return {
        "total_cells": len(cells),
        "successful_cells": successful,
        "failed_cells": len(cells) - successful,
        "ranked_cells": len(ranked),
        "not_found_cells": len(not_found),
        "green_cells": green,
        "green_cell_rate": round(green / successful, 6) if successful else None,
        "rank_buckets": buckets,
        "median_rank": statistics.median([c["rank"] for c in ranked]) if ranked else None,
    }


def summarize(run: dict[str, Any]) -> dict[str, Any]:
    keywords = list(run.get("keywords") or [])
    threshold = run.get("green_rank_threshold", DEFAULT_THRESHOLD)
    if isinstance(threshold, bool) or not isinstance(threshold, int) or threshold < 1:
        raise GridError("green_rank_threshold must be an integer >= 1")
    cells = list(run.get("cells") or [])
    seen = set()
    for cell in cells:
        validate_cell(cell, keywords)
        key = (cell["keyword"], cell.get("point_id"))
        if key in seen:
            raise GridError(f"duplicate cell {key}")
        seen.add(key)
    summary = _counts(cells, threshold)
    summary["per_keyword"] = {
        kw: _counts([c for c in cells if c["keyword"] == kw], threshold) for kw in keywords
    }
    return summary


def _comparable(baseline: dict[str, Any], current: dict[str, Any]) -> None:
    problems = []
    b_grid = (baseline.get("grid_definition") or {}).get("sha256")
    c_grid = (current.get("grid_definition") or {}).get("sha256")
    if not b_grid or b_grid != c_grid:
        problems.append("grid definitions differ (or one is missing)")
    if sorted(baseline.get("keywords") or []) != sorted(current.get("keywords") or []):
        problems.append("keyword sets differ")
    if baseline.get("green_rank_threshold") != current.get("green_rank_threshold"):
        problems.append("green_rank_threshold differs")
    if (baseline.get("provider") or "") != (current.get("provider") or ""):
        problems.append("providers differ")
    if baseline.get("status") != "collected" or current.get("status") != "collected":
        problems.append("both runs must have status 'collected'")
    if problems:
        raise GridError("runs are not comparable: " + "; ".join(problems))


def _effective_rank(cell: dict[str, Any]) -> float:
    return float(cell["rank"]) if cell.get("rank") is not None else math.inf


def compare(baseline: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    """Compare two runs on cells that succeeded in both. Correlation, not causation."""
    _comparable(baseline, current)
    summarize(baseline)
    summarize(current)
    threshold = baseline["green_rank_threshold"]

    def successful(run: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
        return {(c["keyword"], c["point_id"]): c for c in run["cells"]
                if c.get("rank") is not None or c.get("missing_reason") in SUCCESS_REASONS}

    b_cells, c_cells = successful(baseline), successful(current)
    matched = sorted(set(b_cells) & set(c_cells))

    def block(keys: list[tuple[str, str]]) -> dict[str, Any]:
        b_green = sum(1 for k in keys if (b_cells[k].get("rank") or math.inf) <= threshold)
        c_green = sum(1 for k in keys if (c_cells[k].get("rank") or math.inf) <= threshold)
        n = len(keys)
        b_rate = b_green / n if n else None
        c_rate = c_green / n if n else None
        improved = sum(1 for k in keys if _effective_rank(c_cells[k]) < _effective_rank(b_cells[k]))
        declined = sum(1 for k in keys if _effective_rank(c_cells[k]) > _effective_rank(b_cells[k]))
        return {
            "matched_cells": n,
            "baseline_green": b_green,
            "current_green": c_green,
            "baseline_rate": round(b_rate, 6) if b_rate is not None else None,
            "current_rate": round(c_rate, 6) if c_rate is not None else None,
            "change_points": round((c_rate - b_rate) * 100, 3) if n else None,
            "relative_change_pct": (round((c_rate - b_rate) / b_rate * 100, 3)
                                    if n and b_rate else None),
            "improved_cells": improved,
            "declined_cells": declined,
            "unchanged_cells": n - improved - declined,
        }

    keywords = list(baseline["keywords"])
    return {
        "schema_version": SCHEMA_VERSION,
        "baseline_run": baseline.get("run_id"),
        "current_run": current.get("run_id"),
        "provider": baseline.get("provider"),
        "grid_sha256": baseline["grid_definition"]["sha256"],
        "green_rank_threshold": threshold,
        "excluded_cells": {
            "baseline_failed": len(baseline["cells"]) - len(b_cells),
            "current_failed": len(current["cells"]) - len(c_cells),
            "unmatched_successful": len(set(b_cells) ^ set(c_cells)),
        },
        "overall": block(matched),
        "per_keyword": {kw: block([k for k in matched if k[0] == kw]) for kw in keywords},
        "note": ("Matched successful cells only. relative_change_pct is null when the baseline rate is 0. "
                 "Rank movement is an observation; do not attribute causation without a controlled test."),
    }


def compare_markdown(result: dict[str, Any]) -> str:
    def fmt(value: Any, suffix: str = "") -> str:
        return "N/A" if value is None else f"{value}{suffix}"

    lines = [
        f"Geo-grid comparison: {result['baseline_run']} -> {result['current_run']}",
        "",
        f"Provider: {result['provider']}. Grid: {result['grid_sha256'][:12]}. "
        f"Green = rank 1-{result['green_rank_threshold']}.",
        "",
        "| Keyword | Matched cells | Baseline green | Current green | Change (pts) | Relative change | Improved | Declined |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    rows = list(result["per_keyword"].items()) + [("All keywords", result["overall"])]
    for name, b in rows:
        lines.append(
            f"| {name} | {b['matched_cells']} | {b['baseline_green']} | {b['current_green']} | "
            f"{fmt(b['change_points'])} | {fmt(b['relative_change_pct'], '%')} | "
            f"{b['improved_cells']} | {b['declined_cells']} |"
        )
    lines += ["", result["note"], ""]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def load_json(path: Path) -> dict[str, Any]:
    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in pairs:
            if key in out:
                raise GridError(f"{path}: duplicate JSON key {key!r}")
            out[key] = value
        return out

    def no_constants(token: str) -> Any:
        raise GridError(f"{path}: non-finite number {token} is not valid JSON")

    data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=no_duplicates,
                      parse_constant=no_constants)
    if not isinstance(data, dict):
        raise GridError(f"{path}: expected a JSON object")
    return data


def write_json(path: Path | None, data: dict[str, Any]) -> None:
    text = json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    if path is None:
        sys.stdout.write(text)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _column_map(pairs: list[str]) -> dict[str, str]:
    mapping = {}
    for pair in pairs:
        field, sep, header = pair.partition("=")
        if not sep or field not in {"keyword", "rank", "point_id", "lat", "lng", "status"} or not header:
            raise GridError(f"--map expects field=Header with field in keyword, rank, point_id, lat, lng, "
                            f"status; got {pair!r}")
        mapping[field] = header
    return mapping


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p_plan = sub.add_parser("plan", help="write a grid definition")
    p_plan.add_argument("--name", required=True)
    p_plan.add_argument("--lat", type=float, required=True)
    p_plan.add_argument("--lng", type=float, required=True)
    p_plan.add_argument("--size", type=int, required=True, help="odd, 3-25")
    p_plan.add_argument("--spacing-km", type=float, required=True)
    p_plan.add_argument("--centre-source", help="where the centre came from (evidence reference)")
    p_plan.add_argument("--out", type=Path)

    p_imp = sub.add_parser("import", help="convert a provider CSV export into a run file")
    p_imp.add_argument("--grid", type=Path, required=True)
    p_imp.add_argument("--csv", type=Path, required=True)
    p_imp.add_argument("--provider", required=True)
    p_imp.add_argument("--observed-at", required=True, help="ISO 8601 with UTC offset")
    p_imp.add_argument("--run-id", required=True)
    p_imp.add_argument("--brand")
    p_imp.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD)
    p_imp.add_argument("--blank-as", choices=("not_found", "provider_error"))
    p_imp.add_argument("--map", action="append", default=[], metavar="FIELD=HEADER")
    p_imp.add_argument("--out", type=Path)

    p_sum = sub.add_parser("summarize", help="recompute a run's summary")
    p_sum.add_argument("run", type=Path)

    p_cmp = sub.add_parser("compare", help="compare two runs on matched cells")
    p_cmp.add_argument("baseline", type=Path)
    p_cmp.add_argument("current", type=Path)
    p_cmp.add_argument("--markdown", action="store_true")

    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            write_json(args.out, plan_grid(args.name, args.lat, args.lng, args.size, args.spacing_km,
                                           args.centre_source))
        elif args.command == "import":
            run = import_csv(load_json(args.grid), args.csv.read_bytes(),
                             provider=args.provider, observed_at=args.observed_at, run_id=args.run_id,
                             source_name=args.csv.name, column_map=_column_map(args.map),
                             blank_as=args.blank_as, threshold=args.threshold, brand=args.brand)
            write_json(args.out, run)
        elif args.command == "summarize":
            write_json(None, summarize(load_json(args.run)))
        else:
            result = compare(load_json(args.baseline), load_json(args.current))
            if args.markdown:
                sys.stdout.write(compare_markdown(result))
            else:
                write_json(None, result)
    except (GridError, json.JSONDecodeError) as exc:
        print(f"geo-grid: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"geo-grid: cannot read or write: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
