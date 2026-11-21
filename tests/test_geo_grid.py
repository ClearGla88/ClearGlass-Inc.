"""Tests for tools/geo_grid.py: grid geometry, provider import, summaries, comparison."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools import geo_grid as gg

CENTRE = (43.3255, -79.799)


def make_grid(size: int = 3, spacing: float = 2.0) -> dict:
    return gg.plan_grid("test-grid", *CENTRE, size=size, spacing_km=spacing, centre_source="test")


def csv_bytes(rows: list[str], header: str = "keyword,point_id,rank") -> bytes:
    return ("\n".join([header, *rows]) + "\n").encode()


def import_rows(grid: dict, rows: list[str], header: str = "keyword,point_id,rank", **kwargs) -> dict:
    options = {"provider": "Tracker", "observed_at": "2026-12-01T10:00:00-05:00", "run_id": "r1",
               "source_name": "export.csv"}
    options.update(kwargs)
    return gg.import_csv(grid, csv_bytes(rows, header), **options)


# --------------------------------------------------------------------------- #
# Geometry
# --------------------------------------------------------------------------- #

def test_plan_places_centre_and_spaces_neighbours_evenly() -> None:
    grid = make_grid(size=7, spacing=2.0)
    points = {p["id"]: p for p in grid["points"]}
    assert len(points) == 49
    assert (points["r3c3"]["lat"], points["r3c3"]["lng"]) == CENTRE
    for a, b in (("r3c3", "r3c4"), ("r3c3", "r2c3"), ("r0c0", "r0c1"), ("r6c6", "r5c6")):
        d = gg.haversine_km(points[a]["lat"], points[a]["lng"], points[b]["lat"], points[b]["lng"])
        assert d == pytest.approx(2.0, abs=0.01)
    assert points["r0c0"]["lat"] > CENTRE[0] > points["r6c0"]["lat"], "row 0 is the north edge"
    assert points["r0c0"]["lng"] < CENTRE[1] < points["r0c6"]["lng"], "column 0 is the west edge"
    assert grid["span_km"] == 12.0


def test_grid_hash_is_stable_and_detects_tampering() -> None:
    first, second = make_grid(), make_grid()
    assert first["sha256"] == second["sha256"]
    gg.validate_grid(first)
    first["points"][0]["lat"] += 0.001
    with pytest.raises(gg.GridError, match="sha256"):
        gg.validate_grid(first)


@pytest.mark.parametrize("size, spacing", [(4, 2.0), (1, 2.0), (27, 2.0), (5, 0.0), (5, 30.0)])
def test_plan_rejects_even_sizes_and_bad_spacing(size: int, spacing: float) -> None:
    with pytest.raises(gg.GridError):
        gg.plan_grid("g", *CENTRE, size=size, spacing_km=spacing)


# --------------------------------------------------------------------------- #
# Import
# --------------------------------------------------------------------------- #

def test_import_matches_nearest_point_and_fills_missing_cells() -> None:
    grid = make_grid()
    p = {pt["id"]: pt for pt in grid["points"]}
    rows = [
        f"cyber Burlington,{p['r1c1']['lat'] + 0.0004},{p['r1c1']['lng']},1",
        f"cyber Burlington,{p['r0c0']['lat']},{p['r0c0']['lng'] - 0.0004},20+",
        f"cyber Burlington,{p['r2c2']['lat']},{p['r2c2']['lng']},error",
    ]
    run = import_rows(grid, rows, header="keyword,lat,lng,rank")
    cells = {c["point_id"]: c for c in run["cells"]}
    assert len(cells) == 9
    assert cells["r1c1"]["rank"] == 1
    assert cells["r0c0"] == {**cells["r0c0"], "rank": None, "missing_reason": "not_found", "max_checked": 20}
    assert cells["r2c2"]["missing_reason"] == "provider_error"
    assert sum(1 for c in cells.values() if c["missing_reason"] == "not_collected") == 6
    summary = run["summary"]
    assert (summary["successful_cells"], summary["failed_cells"], summary["green_cells"]) == (2, 7, 1)
    assert summary["green_cell_rate"] == 0.5
    assert run["grid_definition"]["sha256"] == grid["sha256"]
    assert len(run["source"]["sha256"]) == 64


def test_blank_rank_fails_closed_unless_its_meaning_is_declared() -> None:
    grid = make_grid()
    with pytest.raises(gg.GridError, match="blank rank"):
        import_rows(grid, ["kw,r0c0,"])
    run = import_rows(grid, ["kw,r0c0,"], blank_as="not_found")
    assert run["cells"][0]["missing_reason"] == "not_found"


@pytest.mark.parametrize("value", ["-", "x", "n/a", "0", "-3", "2.5"])
def test_ambiguous_rank_values_are_rejected(value: str) -> None:
    with pytest.raises(gg.GridError, match="unrecognised rank"):
        import_rows(make_grid(), [f"kw,r0c0,{value}"])


def test_import_rejects_off_grid_rows_duplicates_and_unknown_status() -> None:
    grid = make_grid()
    with pytest.raises(gg.GridError, match="from the nearest grid point"):
        import_rows(grid, ["kw,43.9,-79.0,3"], header="keyword,lat,lng,rank")
    with pytest.raises(gg.GridError, match="duplicate row"):
        import_rows(grid, ["kw,r0c0,3", "kw,r0c0,4"])
    with pytest.raises(gg.GridError, match="unrecognised status"):
        import_rows(grid, ["kw,r0c0,3,pending"], header="keyword,point_id,rank,status")
    with pytest.raises(gg.GridError, match="not in the grid"):
        import_rows(grid, ["kw,r9c9,3"])


def test_column_mapping_and_status_column() -> None:
    run = import_rows(make_grid(), ["kw,r0c0,,not found", "kw,r0c1,2,ok"],
                      header="Search Term,Point,Position,Result",
                      column_map={"keyword": "Search Term", "point_id": "Point", "rank": "Position",
                                  "status": "Result"})
    cells = {c["point_id"]: c for c in run["cells"]}
    assert cells["r0c0"]["missing_reason"] == "not_found"
    assert cells["r0c1"]["rank"] == 2


def test_observed_at_needs_an_offset() -> None:
    with pytest.raises(gg.GridError, match="UTC offset"):
        import_rows(make_grid(), ["kw,r0c0,1"], observed_at="2026-12-01T10:00:00")


# --------------------------------------------------------------------------- #
# Summaries and comparison
# --------------------------------------------------------------------------- #

def test_rate_denominator_excludes_failed_cells_and_is_null_without_successes() -> None:
    run = import_rows(make_grid(), ["kw,r0c0,error", "kw,r0c1,provider_error"])
    assert run["summary"]["green_cell_rate"] is None
    assert run["summary"]["successful_cells"] == 0
    assert run["summary"]["rank_buckets"] == dict.fromkeys(gg.BUCKETS, 0)


def test_summarize_rejects_contradictory_cells() -> None:
    run = import_rows(make_grid(), ["kw,r0c0,1"])
    run["cells"][0]["missing_reason"] = "not_found"
    with pytest.raises(gg.GridError, match="exactly one"):
        gg.summarize(run)


def test_compare_uses_matched_cells_and_reports_relative_change() -> None:
    grid = make_grid()
    base = import_rows(grid, ["kw,r0c0,5", "kw,r0c1,2", "kw,r0c2,error", "kw,r1c0,not found"])
    cur = import_rows(grid, ["kw,r0c0,1", "kw,r0c1,2", "kw,r0c2,1", "kw,r1c0,3"], run_id="r2")
    result = gg.compare(base, cur)
    overall = result["overall"]
    assert overall["matched_cells"] == 3  # r0c2 failed in the baseline, so it is excluded
    assert (overall["baseline_green"], overall["current_green"]) == (1, 3)
    assert overall["relative_change_pct"] == pytest.approx(200.0)
    assert (overall["improved_cells"], overall["declined_cells"]) == (2, 0)
    assert "Geo-grid comparison" in gg.compare_markdown(result)


def test_compare_with_zero_baseline_reports_null_relative_change() -> None:
    grid = make_grid()
    base = import_rows(grid, ["kw,r0c0,9"])
    cur = import_rows(grid, ["kw,r0c0,2"], run_id="r2")
    block = gg.compare(base, cur)["overall"]
    assert block["baseline_rate"] == 0.0 and block["relative_change_pct"] is None
    assert block["change_points"] == 100.0


def test_compare_refuses_runs_that_are_not_comparable() -> None:
    base = import_rows(make_grid(), ["kw,r0c0,1"])
    with pytest.raises(gg.GridError, match="grid definitions differ"):
        gg.compare(base, import_rows(make_grid(spacing=3.0), ["kw,r0c0,1"]))
    with pytest.raises(gg.GridError, match="providers differ"):
        gg.compare(base, import_rows(make_grid(), ["kw,r0c0,1"], provider="Other"))
    with pytest.raises(gg.GridError, match="keyword sets differ"):
        gg.compare(base, import_rows(make_grid(), ["other,r0c0,1"]))


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def test_cli_round_trip(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    grid_file, csv_file, run_file = tmp_path / "grid.json", tmp_path / "export.csv", tmp_path / "run.json"
    assert gg.main(["plan", "--name", "t", "--lat", "43.3255", "--lng", "-79.799", "--size", "3",
                    "--spacing-km", "2", "--out", str(grid_file)]) == 0
    csv_file.write_bytes(b"\xef\xbb\xbfkeyword,point_id,rank\nkw,r1c1,2\n")  # UTF-8 BOM, as spreadsheets write
    assert gg.main(["import", "--grid", str(grid_file), "--csv", str(csv_file), "--provider", "T",
                    "--observed-at", "2026-12-01T10:00:00+00:00", "--run-id", "a", "--out", str(run_file)]) == 0
    run = json.loads(run_file.read_text())
    assert run["source"]["sha256"] == gg.sha256_hex(csv_file.read_bytes())
    assert gg.main(["summarize", str(run_file)]) == 0
    assert json.loads(capsys.readouterr().out)["green_cells"] == 1
    assert gg.main(["compare", str(run_file), str(run_file), "--markdown"]) == 0
    csv_file.write_text("keyword,point_id,rank\nkw,r1c1,-\n")
    assert gg.main(["import", "--grid", str(grid_file), "--csv", str(csv_file), "--provider", "T",
                    "--observed-at", "2026-12-01T10:00:00+00:00", "--run-id", "b"]) == 1


def test_load_json_rejects_duplicate_keys_and_nan(tmp_path: Path) -> None:
    dup, nan = tmp_path / "dup.json", tmp_path / "nan.json"
    dup.write_text('{"a": 1, "a": 2}')
    nan.write_text('{"a": NaN}')
    for path in (dup, nan):
        with pytest.raises(gg.GridError):
            gg.load_json(path)


def test_committed_planning_grids_are_valid() -> None:
    root = Path(__file__).resolve().parents[1] / "burlington-exposure" / "grids"
    files = sorted(root.glob("*.json"))
    assert files, "planning grids are missing"
    for file in files:
        gg.validate_grid(gg.load_json(file))
