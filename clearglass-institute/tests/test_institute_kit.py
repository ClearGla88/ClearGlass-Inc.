"""Tests for clearglass-institute/tools/institute_kit.py.

The first group runs the checker against the real package, so a change that
makes it claim more than its record supports fails the build. The rest mutate a
temporary copy to prove each rule fires.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
TODAY = dt.date(2026, 11, 12)

CHARITY_WORDING = (
    "ClearGlass Institute is not currently a registered charity with the Canada Revenue Agency. "
    "Donations are not eligible for official charitable tax receipts."
)
SEPARATION_WORDING = (
    "ClearGlass Institute is a separate not-for-profit initiative from ClearGlass Inc. "
    "ClearGlass Inc. is a separate commercial entity."
)
PACKAGE_DOCS = (
    "01_EXECUTIVE_BRIEF.md",
    "03_BYLAWS.md",
    "04_CONFLICT_AND_RELATED_PARTY_POLICY.md",
    "05_FOUNDING_BOARD_PACKAGE.md",
    "06_BANKING_AND_FINANCIAL_CONTROLS.md",
    "07_PUBLIC_LAUNCH_PAGE_COPY.md",
    "08_FIRST_PUBLIC_BRIEF_OUTLINE.md",
    "09_14_DAY_EXECUTION_PLAN.md",
    "10_90_DAY_OPERATING_PLAN.md",
    "11_RISK_AND_COMPLIANCE_REGISTER.md",
    "12_VALIDATION_CHECKLIST.md",
    "13_OPEN_QUESTIONS.md",
)


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
    """A throwaway copy of the package whose data files a test can change."""

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
        status["gates"]["articles_filed"] = _done("2026-11-04", "registry receipt, tab 1")
        status["gates"]["certificate_of_incorporation"] = _done("2026-11-10", "minute book, tab 1")
        status["entity"]["corporation_number"] = "1000123456"
        status["entity"]["incorporation_date"] = "2026-11-10"
        self.write_status(status)
        return status

    def complete(self) -> dict:
        """Record all ten go/no-go conditions."""
        status = self.incorporate()
        for key in (
            "bylaws_adopted",
            "organizational_minutes_signed",
            "cra_business_number",
            "institute_bank_account",
            "conflict_policy_adopted",
            "annual_return_calendar",
            "public_charity_disclaimer",
        ):
            status["gates"][key] = _done("2026-11-11", "minute book")
        status["public_site"] = {"live": True, "url": "https://institute.example.org/"}
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


class RealPackageTests(unittest.TestCase):
    def test_real_package_passes(self):
        findings, _ = kit.check(KIT, TODAY)
        self.assertEqual(findings, [])

    def test_real_record_claims_nothing_without_evidence(self):
        status = kit.load_status(KIT)
        for key, _ in kit.CORE_GATES + kit.MILESTONES:
            record = kit._records(status)[key]
            if record["met"]:
                self.assertTrue(record["date"] and record["evidence"], key)
        if not status["gates"]["certificate_of_incorporation"]["met"]:
            self.assertIn("It has not been incorporated.", kit.entity_statement(status))
            self.assertIsNone(status["entity"]["corporation_number"])

    def test_package_is_complete_and_in_order(self):
        present = sorted(path.name for path in (KIT / "package").glob("*.md"))
        self.assertEqual(present, sorted(PACKAGE_DOCS))
        readme = (KIT / "README.md").read_text(encoding="utf-8")
        table = readme.split("## The package, in order", 1)[1].split("\n## ", 1)[0]
        positions = [table.index(name) for name in PACKAGE_DOCS]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("articles/ARTICLES_DRAFT.md", readme)

    def test_go_no_go_conditions_match_the_validation_checklist(self):
        self.assertEqual(len(kit.CORE_GATES), 10)
        text = (KIT / "package" / "12_VALIDATION_CHECKLIST.md").read_text(encoding="utf-8")
        for number, (key, label) in enumerate(kit.CORE_GATES, start=1):
            self.assertIn(f"| {number} | {label} |", text)
            self.assertIn(f"`gates.{key}`", text)

    def test_every_step_is_in_the_plan_order(self):
        steps = {key for key, _ in kit.CORE_GATES + kit.MILESTONES}
        self.assertEqual(set(kit.RUNBOOK_ORDER), steps)
        self.assertEqual(len(kit.RUNBOOK_ORDER), len(steps))
        for step, needs in kit.REQUIRES.items():
            for need in needs:
                self.assertLess(kit.RUNBOOK_ORDER.index(need), kit.RUNBOOK_ORDER.index(step))
        plan = (KIT / "package" / "09_14_DAY_EXECUTION_PLAN.md").read_text(encoding="utf-8")
        for key, _ in kit.CORE_GATES:
            self.assertIn(f"`gates.{key}`", plan)
        for key, _ in kit.MILESTONES:
            self.assertIn(f"`milestones.{key}`", plan)

    def test_required_wording_is_exact(self):
        status = kit.load_status(KIT)
        self.assertEqual(kit.charity_disclaimer(status), CHARITY_WORDING)
        self.assertEqual(kit.separation_disclaimer(status), SEPARATION_WORDING)
        copy_doc = (KIT / "package" / "07_PUBLIC_LAUNCH_PAGE_COPY.md").read_text(encoding="utf-8")
        visible = " ".join(
            kit.visible_sentences((KIT / "site" / "index.html").read_text(encoding="utf-8"))
        )
        for wording in (CHARITY_WORDING, SEPARATION_WORDING):
            self.assertIn(wording, copy_doc)
            self.assertIn(wording, visible)

    def test_public_page_is_kept_out_of_search_and_off_the_company_site(self):
        page = (KIT / "site" / "index.html").read_text(encoding="utf-8")
        status = kit.load_status(KIT)
        if not status["public_site"]["live"]:
            self.assertIn('<meta name="robots" content="noindex">', page)
        self.assertNotIn("clearglassinc.com", page)
        self.assertIn("<title>ClearGlass Institute — Clarity in the Public Interest</title>", page)

    def test_no_personal_details_in_the_package(self):
        contact = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+|\b\d{3}[-. ]\d{3}[-. ]\d{4}\b")
        for path in sorted(KIT.rglob("*.md")) + sorted(KIT.rglob("*.html")):
            self.assertIsNone(contact.search(path.read_text(encoding="utf-8")), path.name)

    def test_unverified_rules_carry_an_action(self):
        register = kit.load_claims(KIT)
        for claim in register["claims"]:
            if claim["status"] == "UNVERIFIED":
                self.assertTrue(claim.get("action"), claim["id"])

    def test_open_items_are_counted(self):
        rows = dict(kit.marker_counts(KIT))
        questions = rows["package/13_OPEN_QUESTIONS.md"]
        self.assertTrue(all(count > 0 for count in questions))
        status_md = (KIT / "STATUS.md").read_text(encoding="utf-8")
        self.assertIn("| Document | CONFIRM | LEGAL REVIEW | DECISION REQUIRED |", status_md)


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
        findings = made.findings()
        self.assertFinding(
            findings,
            "institute_bank_account is recorded as done but certificate_of_incorporation is not",
        )
        self.assertFinding(
            findings,
            "institute_bank_account is recorded as done but organizational_minutes_signed is not",
        )

    def test_articles_need_consents_and_a_name_search(self):
        made = self.copy()
        status = made.status
        status["gates"]["articles_filed"] = _done()
        made.write_status(status)
        findings = made.findings()
        self.assertFinding(
            findings, "articles_filed is recorded as done but three_director_consents"
        )
        self.assertFinding(findings, "articles_filed is recorded as done but name_search_report")

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
        fake_email = "jane" + "@" + "example.org"
        fake_phone = "-".join(("905", "555", "0100"))
        for evidence in (f"ask {fake_email}", f"call {fake_phone}", "kept at L7R 1A1"):
            made = self.copy()
            status = made.status
            status["gates"]["three_director_consents"] = _done(evidence=evidence)
            made.write_status(status)
            self.assertFinding(made.findings(), "looks like it holds contact details")

    def test_charity_registration_needs_corporation_and_business_number(self):
        made = self.copy()
        status = made.status
        status["charity"] = {"registered": True, "date": "2026-11-10", "evidence": "CRA letter"}
        made.write_status(status)
        findings = made.findings()
        self.assertFinding(findings, "charity is recorded as registered but certificate_of_incorp")
        self.assertFinding(findings, "charity is recorded as registered but cra_business_number")

    def test_public_site_cannot_be_on_the_company_domain(self):
        for url in ("https://www.clearglassinc.com/institute/", "https://clearglassinc.com/"):
            made = self.copy()
            status = made.status
            status["public_site"] = {"live": True, "url": url}
            made.write_status(status)
            self.assertFinding(made.findings(), "must be on its own domain")

    def test_disclaimer_condition_needs_a_live_site(self):
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


class StatusStateTests(KitCase):
    def test_three_states_of_the_notice(self):
        made = self.copy()
        proposed = kit.entity_statement(made.status)
        self.assertIn("is a proposed organization. It has not been incorporated.", proposed)
        self.assertIn(CHARITY_WORDING, proposed)

        organizing = kit.entity_statement(made.incorporate())
        self.assertIn("was incorporated under the laws of Ontario on 2026-11-10", organizing)
        self.assertIn("Ontario Corporation Number 1000123456", organizing)
        self.assertIn("It is still being organized and is not yet operating.", organizing)
        self.assertNotIn("is an operating", organizing)
        self.assertIn(CHARITY_WORDING, organizing)

        operating = kit.entity_statement(made.complete())
        self.assertIn("is an operating Ontario not-for-profit corporation", operating)
        self.assertIn(CHARITY_WORDING, operating)

    def test_operating_needs_all_ten_conditions(self):
        made = self.copy()
        status = made.complete()
        self.assertTrue(kit.all_gates_met(status))
        for key, _ in kit.CORE_GATES:
            partial = json.loads(json.dumps(status))
            partial["gates"][key] = _blank_record()
            self.assertFalse(kit.all_gates_met(partial), key)
            self.assertNotIn("is an operating", kit.entity_statement(partial))

    def test_complete_record_passes_and_reports_go(self):
        made = self.copy()
        made.complete()
        kit.render(made.root)
        self.assertEqual(made.findings(), [])
        status_md = (made.root / "STATUS.md").read_text(encoding="utf-8")
        self.assertIn("**Result: GO. All ten conditions are recorded.**", status_md)
        self.assertIn("is an operating Ontario not-for-profit corporation", status_md)

    def test_charity_wording_goes_only_when_registration_is_recorded(self):
        made = self.copy()
        status = made.complete()
        status["charity"] = {"registered": True, "date": "2026-11-11", "evidence": "CRA letter"}
        made.write_status(status)
        statement = kit.entity_statement(status)
        self.assertNotIn("not currently a registered charity", statement)
        self.assertIn("ClearGlass Institute is a registered charity.", statement)


class GeneratedFileTests(KitCase):
    def test_stale_generated_file_fails(self):
        made = self.copy()
        path = made.root / "STATUS.md"
        path.write_text(path.read_text(encoding="utf-8") + "\nGO.\n", encoding="utf-8")
        self.assertFinding(made.findings(), "STATUS.md: out of date")

    def test_document_without_notice_fails(self):
        made = self.copy()
        path = made.root / "package" / "03_BYLAWS.md"
        lines = [
            line
            for line in path.read_text(encoding="utf-8").split("\n")
            if not line.startswith(kit.NOTICE_PREFIX)
        ]
        path.write_text("\n".join(lines), encoding="utf-8")
        self.assertFinding(
            made.findings(), "package/03_BYLAWS.md: needs exactly one line starting with"
        )

    def test_hand_edited_notice_fails(self):
        made = self.copy()
        path = made.root / "package" / "01_EXECUTIVE_BRIEF.md"
        text = path.read_text(encoding="utf-8").replace(
            "It has not been incorporated.", "It is an operating corporation.", 1
        )
        path.write_text(text, encoding="utf-8")
        self.assertFinding(made.findings(), "package/01_EXECUTIVE_BRIEF.md: out of date")

    def test_new_document_must_carry_the_notice(self):
        made = self.copy()
        (made.root / "package" / "14_NEW.md").write_text("# New\n\nText.\n", encoding="utf-8")
        self.assertFinding(
            made.findings(), "package/14_NEW.md: needs exactly one line starting with"
        )

    def test_adding_an_open_item_makes_the_status_report_stale(self):
        made = self.copy()
        path = made.root / "package" / "10_90_DAY_OPERATING_PLAN.md"
        path.write_text(
            path.read_text(encoding="utf-8") + "\n[CONFIRM] one more thing.\n", encoding="utf-8"
        )
        self.assertFinding(made.findings(), "STATUS.md: out of date")
        kit.render(made.root)
        self.assertEqual(made.findings(), [])

    def test_render_rewrites_every_notice_when_the_record_changes(self):
        made = self.copy()
        made.incorporate()
        self.assertFinding(made.findings(), "out of date")
        changed = kit.render(made.root)
        self.assertIn("package/03_BYLAWS.md", changed)
        self.assertIn("site/index.html", changed)
        self.assertEqual(made.findings(), [])
        for path in sorted(made.root.rglob("*.md")):
            notice = [
                line
                for line in path.read_text(encoding="utf-8").split("\n")
                if line.startswith(kit.NOTICE_PREFIX)
            ]
            self.assertEqual(len(notice), 1, path.name)
            self.assertNotIn("has not been incorporated", notice[0])
            self.assertIn("Ontario Corporation Number 1000123456", notice[0])
        status_md = (made.root / "STATUS.md").read_text(encoding="utf-8")
        self.assertIn("| 2027-01-09 | File the initial return", status_md)
        self.assertIn("NO-GO. 3 of 10 conditions recorded.", status_md)

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
            "The Institute is an operating corporation.": "operating-claim",
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
            "The Institute has not been incorporated.",
            "A host is named only after it has agreed in writing to be a partner.",
            "The first-year target is 12 briefs.",
        ):
            made.add_to_page(sentence)
        self.assertEqual(made.findings(), [])

    def test_missing_or_altered_required_wording_fails(self):
        made = self.copy()
        text = made.page().read_text(encoding="utf-8")
        made.page().write_text(
            text.replace("ClearGlass Inc. is a separate commercial entity.", "They are related."),
            encoding="utf-8",
        )
        self.assertFinding(made.findings(), "must carry this wording exactly")

    def test_claim_in_meta_description_is_scanned(self):
        made = self.copy()
        text = (
            made.page()
            .read_text(encoding="utf-8")
            .replace(
                "</head>",
                '<meta property="og:description" content="A registered charity for AI literacy.">\n'
                "</head>",
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
        made.add_to_page("The Institute is an operating corporation.")
        self.assertFinding(made.findings(), "[operating-claim]")

    def test_charity_claim_still_fails_after_incorporation(self):
        made = self.copy()
        made.complete()
        kit.render(made.root)
        made.add_to_page("We are a registered charity.")
        self.assertFinding(made.findings(), "[charity-claim]")

    def test_partner_claim_passes_only_with_an_agreement_on_record(self):
        made = self.copy()
        status = made.status
        status["named_partners"] = [
            {"name": "Some Library", "agreement_date": "2026-11-05", "evidence": "tab 14"}
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
        path = made.root / "package" / "09_14_DAY_EXECUTION_PLAN.md"
        path.write_text(path.read_text(encoding="utf-8") + "\nSee [L-99].\n", encoding="utf-8")
        self.assertFinding(made.findings(), "package/09_14_DAY_EXECUTION_PLAN.md: cites [L-99]")

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
        self.assertEqual(by_text["First financial year ends"]["rule"], "none")

    def test_no_year_end_means_no_year_end_dates(self):
        items = kit.compliance_dates(dt.date(2027, 1, 15), None, kit.load_claims(KIT))
        self.assertEqual(len(items), 3)

    def test_bad_year_end_is_refused(self):
        self.assertIsNone(kit._parse_year_end("02-30"))
        self.assertIsNone(kit._parse_year_end("13-01"))
        self.assertEqual(kit._parse_year_end("03-31"), (3, 31))


if __name__ == "__main__":
    unittest.main()
