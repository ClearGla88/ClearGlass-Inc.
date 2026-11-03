import unittest

from content_agent import ALLOCATION, PILLARS, build_plan, evaluate_paid, validate_seed


SEED = {
    "opacity_issue": "missing public records", "security_consequence": "controls cannot be verified",
    "founder_truth": "I rebuilt the evidence model today.", "product": "Guardian",
    "feature": "evidence mapping", "pain": "unowned risk", "demo": "map evidence to an owner",
    "sources": ["https://example.gov/report"]
}


class ContentAgentTests(unittest.TestCase):
    def test_exact_allocation_and_approval_gate(self):
        drafts = build_plan(SEED)
        self.assertEqual(len(drafts), 10)
        self.assertEqual([sum(d.pillar == p for d in drafts) for p in PILLARS], list(ALLOCATION))
        self.assertTrue(all(d.status == "DRAFT_REQUIRES_HUMAN_APPROVAL" for d in drafts))

    def test_clarity_drafts_retain_sources(self):
        drafts = build_plan(SEED)
        self.assertTrue(all(d.evidence == SEED["sources"] for d in drafts[:5]))

    def test_rejects_missing_or_non_https_sources(self):
        bad = dict(SEED, sources=[])
        with self.assertRaises(ValueError):
            validate_seed(bad)
        bad["sources"] = ["http://example.gov/report"]
        with self.assertRaises(ValueError):
            validate_seed(bad)

    def test_paid_seeding_pause_and_scale_rules(self):
        actions = evaluate_paid([
            {"reel_id": "seed", "hours_since_publish": 6, "completion_rate": .51, "hook_retention": .40, "spend_cad": 0},
            {"reel_id": "pause", "hours_since_publish": 8, "completion_rate": .35, "hook_retention": .29, "spend_cad": 5},
            {"reel_id": "scale", "hours_since_publish": 12, "completion_rate": .42, "hook_retention": .31, "spend_cad": 10},
        ])
        self.assertEqual([(a.decision, a.budget_cad_per_day) for a in actions], [("SEED", 10), ("PAUSE", 0), ("SCALE_CAP", 20)])
        self.assertTrue(all(a.status == "RECOMMENDATION_REQUIRES_HUMAN_APPROVAL" for a in actions))

    def test_paid_metrics_fail_closed(self):
        with self.assertRaises(ValueError):
            evaluate_paid([{"reel_id": "bad", "hours_since_publish": 1, "completion_rate": 1.1, "hook_retention": .5, "spend_cad": 0}])


if __name__ == "__main__":
    unittest.main()
