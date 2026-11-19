"""Identity resolution and containment policy: what may be proposed, and what never may."""

from __future__ import annotations

from datetime import timedelta

from active_defense.assets import AMBIGUOUS, RESOLVED, SHARED_ADDRESS, STALE, UNKNOWN


def test_single_decoy_interaction_alerts_but_never_proposes(lab):
    out = lab.decoy()
    case_id = out["cases"][0]
    assert out["subject"] == "asset:lab-ws-001"
    assert lab.state(case_id) == "enriched"
    assert lab.sql("SELECT COUNT(*) FROM proposals")[0][0] == 0
    assert "alert.recorded" in lab.audit_actions()


def test_two_decoy_sensors_without_endpoint_evidence_still_never_propose(lab):
    lab.decoy()
    lab.send("sensor-http-01", category="honeypot.http.request", src_ip="10.66.10.21")
    assert lab.sql("SELECT COUNT(*) FROM proposals")[0][0] == 0


def test_corroborated_evidence_produces_exact_single_asset_proposal(lab):
    case_id = lab.corroborate()
    p = lab.proposal(case_id)
    assert lab.state(case_id) == "awaiting_approval"
    assert p["status"] == "awaiting_approval" and p["target_asset_id"] == "lab-ws-001"
    plan = p["plan"]
    assert plan["blast_radius"] == "single asset"
    assert plan["preserved_access_paths"] == ["10.66.0.10/32:22", "10.66.0.11/32:443"]
    assert plan["correlation"]["id"] == "COR-COMPROMISE-001"
    assert len(plan["evidence"]["signal_ids"]) == 2 and len(plan["evidence"]["artifacts"]) == 2
    assert plan["reversal_procedure"] and plan["expected_impact"]
    assert all(c["passed"] for c in p["decision"]["checks"])


def test_observe_mode_records_the_decision_but_proposes_nothing(make_lab):
    lab = make_lab(mode="observe")
    case_id = lab.corroborate()
    assert lab.state(case_id) == "enriched"
    assert lab.sql("SELECT COUNT(*) FROM proposals")[0][0] == 0
    assert "policy.observe_only" in lab.audit_actions()


def test_protected_asset_is_rejected_and_escalated(lab):
    lab.scenario("protected")
    case_id = lab.sql("SELECT case_id FROM cases WHERE subject='asset:lab-dc-001'")[0][0]
    p = lab.proposal(case_id)
    failed = {c["name"] for c in p["decision"]["checks"] if not c["passed"]}
    assert p["status"] == "denied" and lab.state(case_id) == "rejected"
    assert {"not_protected", "asset_authorized_for_containment", "adapter_available"} <= failed
    assert lab.case(case_id)["case"]["escalated"] == 1
    assert lab.sql("SELECT COUNT(*) FROM actions")[0][0] == 0


def test_every_protected_class_is_excluded(lab):
    for asset in ("lab-dc-001", "lab-bkp-001", "lab-fw-001", "lab-soc-001", "lab-plc-001"):
        lab.edr(asset=asset)
    assert lab.sql("SELECT COUNT(*) FROM actions")[0][0] == 0
    assert all(r[0] == "denied" for r in lab.sql("SELECT status FROM proposals"))


def test_identity_resolution(lab):
    reg, at = lab.bundle.registry, lab.clock.now()
    assert reg.resolve_ip("10.66.10.21", at).status == RESOLVED
    assert reg.resolve_ip("10.66.10.99", at).status == AMBIGUOUS
    assert reg.resolve_ip("10.66.200.7", at).status == SHARED_ADDRESS
    assert reg.resolve_ip("10.66.99.99", at).status == UNKNOWN
    assert reg.resolve_ip("10.66.10.40", at).status == RESOLVED
    assert reg.resolve_ip("10.66.10.40", at + timedelta(hours=2)).status == STALE


def test_unknown_ambiguous_shared_and_stale_sources_never_reach_an_asset(lab):
    for ip in ("10.66.10.99", "10.66.200.7", "10.66.99.99", "192.0.2.80"):
        out = lab.decoy(ip)
        assert out["subject"] == f"ip:{ip}"
    lab.clock.advance(7200)
    assert lab.decoy("10.66.10.40")["subject"] == "ip:10.66.10.40"  # stale DHCP lease
    assert lab.sql("SELECT COUNT(*) FROM proposals")[0][0] == 0


def test_ambiguous_decoy_source_does_not_corroborate_endpoint_alert(lab):
    lab.decoy("10.66.10.99")  # bound to lab-ws-003 and lab-ws-004
    case_id = lab.edr(asset="lab-ws-003")["cases"][0]
    assert lab.state(case_id) == "enriched"
    assert lab.sql("SELECT COUNT(*) FROM proposals")[0][0] == 0


def test_conflicting_asserted_identity_is_not_trusted(lab):
    out = lab.send("sensor-edr-01", category="endpoint.alert", asset_id="lab-ws-002", src_ip="10.66.10.21",
                   attributes={"verdict": "malicious", "behavior": "suspicious_process"})
    assert out["identity"] == "CONFLICT" and out["subject"] == "claimed:lab-ws-002"


def test_network_lateral_signal_without_endpoint_evidence_is_denied(lab):
    lab.decoy()
    lab.send("sensor-flow-01", category="network.flow", src_ip="10.66.10.21",
             attributes={"pattern": "internal_fanout"})
    case_id = lab.sql("SELECT case_id FROM cases WHERE subject='asset:lab-ws-001'")[0][0]
    p = lab.proposal(case_id)
    failed = {c["name"] for c in p["decision"]["checks"] if not c["passed"]}
    assert p["status"] == "denied" and "evidence_corroborated" in failed


def test_lateral_movement_scopes_related_assets_and_proposes_source_only(lab):
    lab.decoy("10.66.10.40")  # another asset with a recent signal
    lab.scenario("lateral")
    case_id = lab.sql("SELECT case_id FROM cases WHERE subject='asset:lab-ws-001'")[0][0]
    p = lab.proposal(case_id)
    assert p["playbook_id"] == "PB-04-lateral-movement-scope"
    assert p["target_asset_id"] == "lab-ws-001"
    assert p["plan"]["related_assets_for_review"] == ["lab-ws-002"]


def test_ransomware_escalates_with_short_approval_window(lab):
    lab.scenario("ransomware")
    case_id = lab.sql("SELECT case_id FROM cases")[0][0]
    p = lab.proposal(case_id)
    view = lab.case(case_id)
    assert p["playbook_id"] == "PB-05-ransomware-containment" and view["case"]["escalated"] == 1
    assert view["case"]["severity"] == "critical"
    from active_defense.util import parse_iso
    assert (parse_iso(p["expires_at"]) - parse_iso(p["created_at"])).total_seconds() == 900


def test_enforce_mode_preauthorizes_low_criticality_only(make_lab):
    resp = {"enforce_acknowledged": True, "enforce_preauthorized_playbooks": ["PB-03-isolate-corroborated-host"],
            "max_concurrent_isolations": 5, "max_actions_per_hour": 10}
    lab = make_lab(mode="enforce", response=resp)
    case_id = lab.corroborate()
    p = lab.proposal(case_id)
    assert p["status"] == "approved" and p["decided_by"].startswith("policy:")
    assert lab.state(case_id) == "executing"
    assert lab.executor.run_once()[0]["status"] == "verified"
    crit = lab.corroborate(asset="lab-app-001", ip="10.66.20.10")
    assert lab.proposal(crit)["status"] == "awaiting_approval"  # critical asset: a human decides


def test_concurrency_limit_blocks_second_incident(lab):
    first = lab.contain()
    second = lab.corroborate(asset="lab-ws-002", ip="10.66.10.40")
    p = lab.proposal(second)
    failed = {c["name"] for c in p["decision"]["checks"] if not c["passed"]}
    assert lab.state(first) == "verified"
    assert p["status"] == "denied" and failed == {"within_rate_limits"}


def test_hourly_rate_limit(make_lab):
    lab = make_lab(response={"max_concurrent_isolations": 10, "max_actions_per_hour": 1})
    lab.contain()
    p = lab.proposal(lab.corroborate(asset="lab-ws-002", ip="10.66.10.40"))
    assert p["status"] == "denied"
    assert any("last hour" in c["detail"] for c in p["decision"]["checks"] if not c["passed"])
