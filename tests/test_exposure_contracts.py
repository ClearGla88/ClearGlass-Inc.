"""Tests for tools/exposure_contracts.py: the Burlington artifacts must not carry unsourced numbers."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from tools import exposure_contracts as ec

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def copy_root(tmp_path: Path) -> Path:
    for name in ec.ARTIFACTS:
        shutil.copy(ROOT / name, tmp_path / name)
    shutil.copytree(ROOT / "burlington-exposure" / "grids", tmp_path / "burlington-exposure" / "grids")
    return tmp_path


def mutate(root: Path, name: str, change: Callable[[dict], None]) -> list[str]:
    path = root / name
    data = json.loads(path.read_text())
    change(data)
    path.write_text(json.dumps(data))
    return ec.check_all(root)[name]


def test_repository_artifacts_pass() -> None:
    results = ec.check_all(ROOT)
    assert results == {name: [] for name in ec.ARTIFACTS}


def test_strict_parsing_rejects_duplicate_keys_and_nan(copy_root: Path) -> None:
    (copy_root / "priority_levers.json").write_text('{"levers": [], "levers": []}')
    (copy_root / "competitor_intel.json").write_text('{"keyword_results": [], "x": NaN}')
    results = ec.check_all(copy_root)
    assert "duplicate JSON key" in results["priority_levers.json"][0]
    assert "non-finite" in results["competitor_intel.json"][0]


def test_stale_score_and_misordered_ranks_are_caught(copy_root: Path) -> None:
    def stale(data: dict) -> None:
        data["levers"][0]["score"] = 99.0

    assert any("should be 100.0" in p for p in mutate(copy_root, "priority_levers.json", stale))

    def swap(data: dict) -> None:
        data["levers"][0]["rank"], data["levers"][-1]["rank"] = data["levers"][-1]["rank"], data["levers"][0]["rank"]

    assert any("follow scores" in p for p in mutate(copy_root, "priority_levers.json", swap))

    def out_of_range(data: dict) -> None:
        data["levers"][0]["risk"] = 0

    assert any("integers from 1 to 5" in p for p in mutate(copy_root, "priority_levers.json", out_of_range))


def test_metric_values_need_a_collected_source(copy_root: Path) -> None:
    def invent(data: dict) -> None:
        data["gbp"]["impressions"] = 1200

    problems = mutate(copy_root, "baseline_metrics.json", invent)
    assert any("gbp.impressions holds data but source 'google_business_profile' is not collected" in p
               for p in problems)


def test_collected_source_needs_evidence_and_quality_must_follow(copy_root: Path) -> None:
    def collect_without_evidence(data: dict) -> None:
        data["sources"]["ga4"]["status"] = "collected"

    problems = mutate(copy_root, "baseline_metrics.json", collect_without_evidence)
    assert any("needs evidence_ref" in p for p in problems)
    assert any("missing_required_sources" in p for p in problems)
    assert any("completeness_ratio should be 0.1429" in p for p in problems)
    assert any("data_state" in p for p in problems)


def test_live_observations_need_dates_and_evidence(copy_root: Path) -> None:
    def undated(data: dict) -> None:
        data["live_site_observations"]["sitemap_health"].pop("observed_at")

    assert any("observed_at" in p for p in mutate(copy_root, "baseline_metrics.json", undated))


def test_targets_stay_targets_and_guardrails_stay(copy_root: Path) -> None:
    def relabel(data: dict) -> None:
        data["status"] = "achieved"
        data["guardrails"]["prohibited"].remove("review gating")

    problems = mutate(copy_root, "MISSION_OBJECTIVES.json", relabel)
    assert any("targets_not_results" in p for p in problems)
    assert any("review gating" in p for p in problems)


def test_grid_summary_must_match_cells(copy_root: Path) -> None:
    def fake_green(data: dict) -> None:
        data["summary"]["green_cells"] = 12

    assert any("summary does not match" in p for p in mutate(copy_root, "geo_grid_baseline.json", fake_green))

    def cells_while_not_collected(data: dict) -> None:
        data["cells"] = [{"keyword": data["keywords"][0], "point_id": "r0c0", "rank": 1, "missing_reason": None}]

    assert any("cells must be empty" in p
               for p in mutate(copy_root, "geo_grid_baseline.json", cells_while_not_collected))


def test_proposed_grid_hash_must_match_its_file(copy_root: Path) -> None:
    def wrong_hash(data: dict) -> None:
        data["proposed_grids"][0]["sha256"] = "0" * 64

    assert any("sha256 does not match" in p for p in mutate(copy_root, "geo_grid_baseline.json", wrong_hash))


def test_competitor_records_need_evidence(copy_root: Path) -> None:
    def add_unsourced(data: dict) -> None:
        data["keyword_results"][0]["status"] = "collected"
        data["keyword_results"][0]["competitors"] = [{"name": "Example Cyber"}]

    assert any("needs name, observed_at and evidence_refs" in p
               for p in mutate(copy_root, "competitor_intel.json", add_unsourced))


def test_opportunity_verification_rules(copy_root: Path) -> None:
    def claim_verified(data: dict) -> None:
        opp = next(o for o in data["opportunities"] if o["id"] == "burlington-365")
        opp["status"] = "verified"

    problems = mutate(copy_root, "local_opportunity_map.json", claim_verified)
    assert any("burlington-365: 'verified' needs an https official_url" in p for p in problems)
    assert any("burlington-365: 'verified' needs first-party evidence" in p for p in problems)

    def store_contact(data: dict) -> None:
        data["opportunities"][0]["notes"] = "Call 905-555-0100 or email someone@example.org"

    assert any("contact details" in p for p in mutate(copy_root, "local_opportunity_map.json", store_contact))


def test_cli_exit_codes(copy_root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert ec.main(["--root", str(copy_root)]) == 0
    (copy_root / "MISSION_OBJECTIVES.json").unlink()
    assert ec.main(["--root", str(copy_root)]) == 1
    assert "FAIL  MISSION_OBJECTIVES.json: file is missing" in capsys.readouterr().out
    assert ec.main(["--root", str(tmp_path / "nope")]) == 2
