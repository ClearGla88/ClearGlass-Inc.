"""Tests for clearglass-institute/tools/institute_kit.py.

The first group runs the checker against the real kit, so a change that makes
the kit claim more than its record supports fails the build. The rest mutate a
temporary copy to prove each rule fires.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
TODAY = dt.date(2026, 11, 11)


def _load_tool():
    name = "institute_kit_under_test"
    spec = importlib.util.spec_from_file_location(name, KIT / "tools" / "institute_kit.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


kit = _load_tool()


def _done(date: str = "2026-11-10", evidence: str = "minute book, tab 1") -> dict:
    return {"met": True, "date": date, "evidence": evidence}


def _blank_record() -> dict:
    return {"met": False, "date": None, "evidence": None}


def _baseline_status() -> dict:
    """The record before anything has happened.

    Mutation tests start here, so they keep working after the real record moves on.
    """
    return {
        "schema_version": 1,
        "as_of": TODAY.isoformat(),
        "entity": {
            "proposed_name": "ClearGlass Institute",
            "statute": "Not-for-Profit Corporations Act, 2010 (Ontario)",
            "registered_office_municipality": "Burlington, Ontario",
            "corporation_number": None,
            "incorporation_date": None,
            "financial_year_end": None,
        },
        "gates": {key: _blank_record() for key, _ in kit.CORE_GATES},
        "milestones": {key: _blank_record() for key, _ in kit.MILESTONES},
        "charity": {"registered": False, "date": None, "evidence": None},
        "public_site": {"live": False, "url": None},
        "named_partners": [],
    }


class _Copy:
    """A throwaway copy of the kit whose data files a test can change."""

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "kit"
        shutil.copytree(
            KIT, self.root, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache")
        )
        self.write_status(_baseline_status())
        kit.render(self.root)

    def close(self) -> None:
        self._tmp.cleanup()

    @property
    def status(self) -> dict:
        return json.loads((self.root / "data" / "status.json").read_text(encoding="utf-8"))

    def write_status(self, status: dict) -> None:
        (self.root / "data" / "status.json").write_text(
            json.dumps(status, indent=2), encoding="utf-8"
        )

    @property
    def claims(self) -> dict:
        return json.loads((self.root / "data" / "legal_claims.json").read_text(encoding="utf-8"))

    def write_claims(self, claims: dict) -> None:
        (self.root / "data" / "legal_claims.json").write_text(
            json.dumps(claims, indent=2), encoding="utf-8"
        )

    def page(self) -> Path:
        return self.root / "site" / "index.html"

    def add_to_page(self, sentence: str) -> None:
        text = self.page().read_text(encoding="utf-8")
        self.page().write_text(
            text.replace("</main>", f"  <p>{sentence}</p>\n</main>"), encoding="utf-8"
        )

    def findings(self) -> list[str]:
        return kit.check(self.root, TODAY)[0]

    def incorporate(self) -> dict:
        """Record everything up to and including the certificate."""
        status = self.status
        status["milestones"]["name_search_report"] = _done("2026-11-02", "minute book, tab 13")
        status["gates"]["three_director_consents"] = _done("2026-11-03", "minute book, tab 3")
        status["milestones"]["articles_filed"] = _done("2026-11-04", "registry confirmation, tab 9")
        status["gates"]["certificate_of_incorporation"] = _done("2026-11-10", "minute book, tab 1")
        status["entity"]["corporation_number"] = "1000123456"
        status["entity"]["incorporation_date"] = "2026-11-10"
        self.write_status(status)
        return status


class KitCase(unittest.TestCase):
    def copy(self) -> _Copy:
        made = _Copy()
        self.addCleanup(made.close)
        return made

    def assertFinding(self, findings: list[str], fragment: str) -> None:
        self.assertTrue(
            any(fragment in finding for finding in findings),
            f"expected a finding containing {fragment!r}, got {findings}",
        )


class RealKitTests(unittest.TestCase):
    def test_real_kit_passes(self):
        findings, _ = kit.check(KIT, TODAY)
        self.assertEqual(findings, [])

    def test_real_kit_makes_no_formation_claim(self):
        """Until a person records a step with evidence, nothing is marked done."""
        status = kit.load_status(KIT)
        for key, _ in kit.CORE_GATES + kit.MILESTONES:
            record = kit._records(status)[key]
            if record["met"]:
                self.assertTrue(record["date"] and record["evidence"], key)
        if not status["gates"]["certificate_of_incorporation"]["met"]:
            self.assertIn("not yet incorporated", kit.entity_statement(status))
            self.assertIsNone(status["entity"]["corporation_number"])

    def test_six_tests_match_the_founding_kit(self):
        self.assertEqual(len(kit.CORE_GATES), 6)
        text = (KIT / "FOUNDING_KIT.md").read_text(encoding="utf-8")
        section = text.split("## Validation criteria", 1)[1].split("---", 1)[0]
        numbered = [
            line for line in section.splitlines() if line[:2] in {f"{n}." for n in range(1, 10)}
        ]
        self.assertEqual(len(numbered), 6)

    def test_every_step_is_in_the_runbook_order(self):
        steps = {key for key, _ in kit.CORE_GATES + kit.MILESTONES}
        self.assertEqual(set(kit.RUNBOOK_ORDER), steps)
        self.assertEqual(len(kit.RUNBOOK_ORDER), len(steps))
        for step, needs in kit.REQUIRES.items():
            for need in needs:
                self.assertLess(kit.RUNBOOK_ORDER.index(need), kit.RUNBOOK_ORDER.index(step))

    def test_public_page_is_kept_out_of_search_and_off_the_company_site(self):
        page = (KIT / "site" / "index.html").read_text(encoding="utf-8")
        status = kit.load_status(KIT)
        if not status["public_site"]["live"]:
            self.assertIn('<meta name="robots" content="noindex">', page)
        self.assertNotIn("clearglassinc.com", page)
        self.assertIn("Not a registered charity. Donations are not tax-receiptable.", page)

    def test_unverified_rules_carry_an_action(self):
        register = kit.load_claims(KIT)
        for claim in register["claims"]:
            if claim["status"] == "UNVERIFIED":
                self.assertTrue(claim.get("action"), claim["id"])


class StatusRuleTests(KitCase):
    def test_step_marked_done_needs_date_and_evidence(self):
        made = self.copy()
        status = made.status
        status["gates"]["three_director_consents"] = {"met": True, "date": None, "evidence": None}
        made.write_status(status)
        findings = made.findings()
        self.assertFinding(findings, "three_director_consents is met and needs a date")
        self.assertFinding(findings, "three_director_consents is met and needs evidence")

    def test_step_cannot_come_before_the_step_it_depends_on(self):
        made = self.copy()
        status = made.status
        status["gates"]["institute_bank_account"] = _done()
        made.write_status(status)
        self.assertFinding(
            made.findings(),
            "institute_bank_account is recorded as done but certificate_of_incorporation is not",
        )

    def test_certificate_needs_filed_articles(self):
        made = self.copy()
        status = made.status
        status["gates"]["certificate_of_incorporation"] = _done()
        status["entity"]["corporation_number"] = "1000123456"
        status["entity"]["incorporation_date"] = "2026-11-10"
        made.write_status(status)
        self.assertFinding(
            made.findings(), "certificate_of_incorporation is recorded as done but articles_filed"
        )

    def test_corporation_number_without_certificate_fails(self):
        made = self.copy()
        status = made.status
        status["entity"]["corporation_number"] = "1000123456"
        made.write_status(status)
        self.assertFinding(made.findings(), "must be null until the certificate is recorded")

    def test_unknown_key_fails_closed(self):
        made = self.copy()
        status = made.status
        status["gates"]["registered_charity"] = _done()
        made.write_status(status)
        self.assertFinding(made.findings(), "gates must have exactly the keys")

    def test_date_after_as_of_fails(self):
        made = self.copy()
        status = made.status
        status["gates"]["three_director_consents"] = _done("2027-01-01")
        made.write_status(status)
        self.assertFinding(made.findings(), "is dated after as_of")

    def test_evidence_must_not_hold_contact_details(self):
        for evidence in ("ask jane@example.org", "call 905-555-0100", "kept at L7R 1A1"):
            made = self.copy()
            status = made.status
            status["gates"]["three_director_consents"] = _done(evidence=evidence)
            made.write_status(status)
            self.assertFinding(made.findings(), "looks like it holds contact details")

    def test_charity_registration_needs_corporation_and_business_number(self):
        made = self.copy()
        status = made.status
        status["charity"] = {
            "registered": True,
            "date": "2026-11-10",
            "evidence": "CRA letter, tab 10",
        }
        made.write_status(status)
        findings = made.findings()
        self.assertFinding(
            findings, "charity is recorded as registered but certificate_of_incorporation"
        )
        self.assertFinding(findings, "charity is recorded as registered but cra_business_number")

    def test_public_site_cannot_be_on_the_company_domain(self):
        for url in ("https://www.clearglassinc.com/institute/", "https://clearglassinc.com/"):
            made = self.copy()
            status = made.status
            status["public_site"] = {"live": True, "url": url}
            made.write_status(status)
            self.assertFinding(made.findings(), "must be on its own domain")

    def test_disclaimer_gate_needs_a_live_site(self):
        made = self.copy()
        status = made.status
        status["gates"]["public_charity_disclaimer"] = _done()
        made.write_status(status)
        self.assertFinding(
            made.findings(), "public_charity_disclaimer is recorded as done but public_site"
        )

    def test_partner_needs_agreement_date_and_evidence(self):
        made = self.copy()
        status = made.status
        status["named_partners"] = [
            {"name": "Some Library", "agreement_date": None, "evidence": None}
        ]
        made.write_status(status)
        self.assertFinding(made.findings(), "named_partners[0] is met and needs a date")


class GeneratedFileTests(KitCase):
    def test_stale_generated_file_fails(self):
        made = self.copy()
        path = made.root / "STATUS.md"
        path.write_text(
            path.read_text(encoding="utf-8") + "\nAll six tests are met.\n", encoding="utf-8"
        )
        self.assertFinding(made.findings(), "STATUS.md: out of date")

    def test_document_without_notice_fails(self):
        made = self.copy()
        path = made.root / "programs" / "PROGRAM_PLAN.md"
        lines = [
            l
            for l in path.read_text(encoding="utf-8").split("\n")
            if not l.startswith(kit.NOTICE_PREFIX)
        ]
        path.write_text("\n".join(lines), encoding="utf-8")
        self.assertFinding(
            made.findings(), "programs/PROGRAM_PLAN.md: needs exactly one line starting with"
        )

    def test_hand_edited_notice_fails(self):
        made = self.copy()
        path = made.root / "FOUNDING_KIT.md"
        text = path.read_text(encoding="utf-8").replace(
            "It is not yet incorporated and is not a registered charity.",
            "It is a registered charity.",
        )
        path.write_text(text, encoding="utf-8")
        self.assertFinding(made.findings(), "FOUNDING_KIT.md: out of date")

    def test_new_document_must_carry_the_notice(self):
        made = self.copy()
        (made.root / "programs" / "NEW_BRIEF.md").write_text(
            "# A brief\n\nText.\n", encoding="utf-8"
        )
        self.assertFinding(
            made.findings(), "programs/NEW_BRIEF.md: needs exactly one line starting with"
        )

    def test_render_rewrites_every_notice_when_the_record_changes(self):
        made = self.copy()
        made.incorporate()
        self.assertFinding(made.findings(), "out of date")
        changed = kit.render(made.root)
        self.assertIn("FOUNDING_KIT.md", changed)
        self.assertIn("site/index.html", changed)
        self.assertEqual(made.findings(), [])
        for path in sorted(made.root.rglob("*.md")):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn(
                "not yet incorporated", text.split(kit.NOTICE_PREFIX, 1)[1].split("\n", 1)[0]
            )
        page = made.page().read_text(encoding="utf-8")
        self.assertIn("Ontario Corporation Number 1000123456", page)
        self.assertIn(
            "It is not a registered charity and cannot issue official donation receipts.", page
        )
        status_md = (made.root / "STATUS.md").read_text(encoding="utf-8")
        self.assertIn("| 2027-01-09 | File the initial return", status_md)

    def test_render_refuses_bad_data(self):
        made = self.copy()
        status = made.status
        status["gates"]["institute_bank_account"] = _done()
        made.write_status(status)
        with self.assertRaises(kit.KitError):
            kit.render(made.root)

    def test_page_missing_a_generated_block_fails(self):
        made = self.copy()
        text = made.page().read_text(encoding="utf-8").replace("<!-- cgi:notice:start -->", "")
        made.page().write_text(text, encoding="utf-8")
        self.assertFinding(
            made.findings(), "site/index.html: needs one '<!-- cgi:notice:start -->'"
        )


class PublicClaimTests(KitCase):
    def test_unsupported_claims_on_the_page_fail(self):
        cases = {
            "We are a registered charity.": "charity-claim",
            "Your gift is tax-deductible.": "charity-claim",
            "The Institute was incorporated in Ontario.": "incorporation-claim",
            "The Institute is an Ontario not-for-profit corporation.": "incorporation-claim",
            "Our partners include three public libraries.": "authority-claim",
            "Trusted by schools across Halton.": "authority-claim",
            "We have trained 500 students.": "reach-claim",
        }
        for sentence, rule in cases.items():
            made = self.copy()
            made.add_to_page(sentence)
            self.assertFinding(made.findings(), f"[{rule}]")

    def test_hedged_statements_pass(self):
        made = self.copy()
        for sentence in (
            "The Institute is not a registered charity.",
            "It may apply for charitable registration later.",
            "The Institute is not yet incorporated.",
            "A host is named only after it has agreed in writing to be a partner.",
            "The first-year target is 12 briefs.",
        ):
            made.add_to_page(sentence)
        self.assertEqual(made.findings(), [])

    def test_claim_in_meta_description_is_scanned(self):
        made = self.copy()
        text = (
            made.page()
            .read_text(encoding="utf-8")
            .replace(
                "</head>",
                '<meta property="og:description" content="A registered charity for AI literacy.">\n</head>',
            )
        )
        made.page().write_text(text, encoding="utf-8")
        self.assertFinding(made.findings(), "[charity-claim]")

    def test_incorporation_claim_passes_once_the_certificate_is_recorded(self):
        made = self.copy()
        made.incorporate()
        kit.render(made.root)
        made.add_to_page("The Institute was incorporated in Ontario.")
        self.assertEqual(made.findings(), [])
        made.add_to_page("We are a registered charity.")
        self.assertFinding(made.findings(), "[charity-claim]")

    def test_partner_claim_passes_only_with_an_agreement_on_record(self):
        made = self.copy()
        status = made.status
        status["named_partners"] = [
            {
                "name": "Some Library",
                "agreement_date": "2026-11-05",
                "evidence": "minute book, tab 14",
            }
        ]
        made.write_status(status)
        kit.render(made.root)
        made.add_to_page("Our workshop partner hosts the sessions.")
        self.assertEqual(made.findings(), [])
        self.assertIn("Some Library", made.page().read_text(encoding="utf-8"))


class LegalRegisterTests(KitCase):
    def test_confirmed_rule_needs_a_source(self):
        made = self.copy()
        claims = made.claims
        claims["claims"][0]["status"] = "SECONDARY"
        claims["claims"][0]["sources"] = []
        made.write_claims(claims)
        self.assertFinding(made.findings(), "L-01 is SECONDARY and needs at least one source")

    def test_unverified_rule_needs_an_action(self):
        made = self.copy()
        claims = made.claims
        claims["claims"][0]["status"] = "UNVERIFIED"
        claims["claims"][0].pop("action", None)
        made.write_claims(claims)
        self.assertFinding(made.findings(), "L-01 is UNVERIFIED and needs an action")

    def test_unknown_level_and_duplicate_id_fail(self):
        made = self.copy()
        claims = made.claims
        claims["claims"][1]["status"] = "CONFIRMED"
        claims["claims"][2]["id"] = "L-01"
        made.write_claims(claims)
        findings = made.findings()
        self.assertFinding(findings, "L-02 status must be one of")
        self.assertFinding(findings, "L-01 appears more than once")

    def test_document_citing_a_missing_rule_fails(self):
        made = self.copy()
        path = made.root / "operations" / "RUNBOOK.md"
        path.write_text(path.read_text(encoding="utf-8") + "\nSee [L-99].\n", encoding="utf-8")
        self.assertFinding(made.findings(), "operations/RUNBOOK.md: cites [L-99]")

    def test_old_checks_warn_and_fail_only_in_strict_mode(self):
        made = self.copy()
        newest = max(dt.date.fromisoformat(claim["checked"]) for claim in made.claims["claims"])
        later = newest + dt.timedelta(days=kit.STALE_AFTER_DAYS + 1)
        findings, warnings = kit.check(made.root, later)
        self.assertEqual(findings, [])
        self.assertEqual(len(warnings), len(made.claims["claims"]))
        args = ["--root", str(made.root), "check", "--today", later.isoformat()]
        self.assertEqual(kit.main(args), 0)
        self.assertEqual(kit.main([*args, "--strict"]), 1)
        self.assertEqual(kit.check(made.root, newest)[1], [])


class CalendarTests(unittest.TestCase):
    def test_add_months_clamps_to_month_end(self):
        self.assertEqual(kit.add_months(dt.date(2026, 8, 31), 6), dt.date(2027, 2, 28))
        self.assertEqual(kit.add_months(dt.date(2027, 8, 31), 6), dt.date(2028, 2, 29))
        self.assertEqual(kit.add_months(dt.date(2026, 12, 1), 18), dt.date(2028, 6, 1))

    def test_first_year_end_is_strictly_after_incorporation(self):
        self.assertEqual(kit.first_year_end(dt.date(2027, 1, 15), (12, 31)), dt.date(2027, 12, 31))
        self.assertEqual(kit.first_year_end(dt.date(2027, 12, 31), (12, 31)), dt.date(2028, 12, 31))
        self.assertEqual(kit.first_year_end(dt.date(2027, 5, 1), (3, 31)), dt.date(2028, 3, 31))

    def test_dates_and_rule_levels(self):
        register = kit.load_claims(KIT)
        items = kit.compliance_dates(dt.date(2027, 1, 15), (12, 31), register)
        by_text = {item["obligation"]: item for item in items}
        initial = by_text["File the initial return with the Ontario Business Registry"]
        self.assertEqual(initial["date"], "2027-03-16")
        self.assertEqual(initial["rule"], "[L-12]")
        self.assertEqual(by_text["File the Ontario annual return"]["date"], "2028-06-30")
        self.assertEqual(
            by_text["Latest date for the first annual meeting of members"]["date"], "2028-07-15"
        )
        levels = {claim["id"]: claim["status"] for claim in register["claims"]}
        self.assertEqual(initial["verification"], levels["L-12"])
        self.assertEqual([item["date"] for item in items], sorted(item["date"] for item in items))

    def test_no_year_end_means_no_year_end_dates(self):
        items = kit.compliance_dates(dt.date(2027, 1, 15), None, kit.load_claims(KIT))
        self.assertEqual(len(items), 3)

    def test_bad_year_end_is_refused(self):
        self.assertIsNone(kit._parse_year_end("02-30"))
        self.assertIsNone(kit._parse_year_end("13-01"))
        self.assertEqual(kit._parse_year_end("03-31"), (3, 31))


if __name__ == "__main__":
    unittest.main()
