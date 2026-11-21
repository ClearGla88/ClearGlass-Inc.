"""Tests for tools/local_seo_audit.py on a synthetic site, offline and with a fake fetcher."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools import local_seo_audit as audit_mod

SITE = "https://www.example.test"


def org_jsonld(name: str = "ClearGlass Test Inc.", phone: str = "+1-289-555-0000",
               email: str = "hello@example.test", locality: str = "Burlington", **extra) -> str:
    node = {"@context": "https://schema.org", "@type": "Organization", "@id": f"{SITE}/#org", "name": name,
            "telephone": phone, "email": email,
            "address": {"@type": "PostalAddress", "addressLocality": locality, "addressRegion": "ON"}}
    node.update(extra)
    return f'<script type="application/ld+json">{json.dumps(node)}</script>'


def page(title: str | None, body: str = "", head: str = "") -> str:
    title_tag = f"<title>{title}</title>" if title is not None else ""
    return (f"<!doctype html><html><head>{title_tag}<meta name=\"description\" content=\"d\">{head}</head>"
            f"<body>{body}</body></html>")


def build_site(root: Path, *, local_page: bool = True) -> None:
    urls = ["/", "/a.html", "/b.html", "/missing.html"] + (["/burlington-services.html"] if local_page else [])
    root.joinpath("robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {SITE}/sitemap.xml\n")
    root.joinpath("sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + "".join(f"<url><loc>{SITE}{u}</loc></url>" for u in urls) + "</urlset>")
    root.joinpath("index.html").write_text(page(
        "Home", '<h1>Welcome</h1><a href="/a.html">A</a> <a href="gone.html">Gone</a> '
        '<a href="mailto:x@example.test">mail</a> <a href="https://other.test/x">ext</a>',
        org_jsonld(areaServed=[{"@type": "AdministrativeArea", "name": "Burlington, Ontario"}])))
    root.joinpath("a.html").write_text(page(
        "A", "<p>Burlington and more Burlington</p>",
        org_jsonld(name="ClearGlass Test Inc", phone="(289) 555-9999") + '<meta name="robots" content="noindex">'))
    root.joinpath("b.html").write_text(page(
        None, "", '<script type="application/ld+json">{"@type": "Organization",</script>'
        '<link rel="canonical" href="https://www.example.test/a.html">'))
    if local_page:
        root.joinpath("burlington-services.html").write_text(page(
            "Cybersecurity in Burlington, Ontario", "<h1>Cybersecurity for <em>Burlington</em> firms</h1>"))
    root.joinpath("c.html").write_text(page("C", "<script>var sig = 'Call (905) 555-0142';</script>"))


def run(root: Path, **kwargs) -> dict:
    return audit_mod.audit(audit_mod.RepoSite(root, SITE), **kwargs)


def rules(report: dict) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for item in report["findings"]:
        grouped.setdefault(item["rule"], []).append(item)
    return grouped


def test_checkout_audit_finds_each_problem(tmp_path: Path) -> None:
    build_site(tmp_path)
    report = run(tmp_path)
    found = rules(report)
    assert [f["path"] for f in found["sitemap-url-unavailable"]] == ["/missing.html"]
    assert found["sitemap-url-unavailable"][0]["severity"] == "warning", "a checkout may not be the deployed site"
    assert [f["path"] for f in found["sitemap-page-noindex"]] == ["a.html"]
    assert [f["path"] for f in found["nap-phone-conflict"]] == ["a.html"]
    assert [f["path"] for f in found["nap-name-variant"]] == ["a.html"]
    assert [f["path"] for f in found["jsonld-invalid"]] == ["b.html"]
    assert [f["path"] for f in found["missing-title"]] == ["b.html"]
    assert found["canonical-mismatch"][0]["path"] == "b.html"
    placeholder = found["placeholder-phone"][0]
    assert placeholder["path"] == "c.html" and "555-0142" in placeholder["detail"]
    links = found["internal-link-unavailable"]
    assert [f["path"] for f in links] == ["/gone.html"] and "index.html" in links[0]["detail"]
    assert "no-local-landing-page" not in found
    assert "nap-email-conflict" not in found and "nap-locality-conflict" not in found
    nap = report["canonical_nap"]
    assert (nap["name"], nap["telephone"], nap["locality"]) == ("ClearGlass Test Inc.", "+1-289-555-0000", "Burlington")
    signals = report["local_signals"]
    assert signals["pages_with_locality_in_title"] == ["burlington-services.html"]
    assert signals["pages_with_locality_in_h1"] == ["burlington-services.html"]
    assert signals["pages_with_locality_in_area_served"] == ["index.html"]
    assert report["counts"]["sitemap_urls"] == 5 and report["counts"]["sitemap_urls_available"] == 4


def test_missing_local_landing_page_is_reported(tmp_path: Path) -> None:
    build_site(tmp_path, local_page=False)
    assert "no-local-landing-page" in rules(run(tmp_path))


def test_nap_override_file_is_the_reference(tmp_path: Path) -> None:
    build_site(tmp_path)
    nap = {"name": "ClearGlass Test Inc.", "telephone": "289 555 9999", "email": "hello@example.test",
           "locality": "Burlington", "source": "nap.json"}
    found = rules(run(tmp_path, nap=nap))
    assert [f["path"] for f in found["nap-phone-conflict"]] == ["index.html"]


@pytest.mark.parametrize("text, hit", [
    ("555-0100", True), ("(905) 555-0199", True), ("+1 905.555.0150", True),
    ("555-0200", False), ("15550123", False), ("id-555-0123", False), ("5550123", False),
])
def test_fictional_phone_pattern(text: str, hit: bool) -> None:
    assert bool(audit_mod.FICTIONAL_PHONE.search(text)) is hit


def test_phone_and_email_normalisation() -> None:
    assert audit_mod.norm_phone("+1 (289) 707-0269") == audit_mod.norm_phone("289.707.0269") == "2897070269"
    assert audit_mod.norm_email("mailto:Hello@Example.test ") == "hello@example.test"


def test_live_mode_treats_unavailable_sitemap_urls_as_errors(tmp_path: Path) -> None:
    build_site(tmp_path)
    checkout = audit_mod.RepoSite(tmp_path, SITE)
    calls: list[str] = []

    def fake_fetch(url: str) -> tuple[int, str | None]:
        calls.append(url)
        if url.endswith("/missing.html"):
            return 503, None
        return checkout.get(url)

    report = audit_mod.audit(audit_mod.LiveSite(SITE, fetch=fake_fetch))
    unavailable = rules(report)["sitemap-url-unavailable"]
    assert unavailable[0]["severity"] == "error" and unavailable[0]["detail"] == "HTTP 503"
    assert all(url.startswith(SITE) for url in calls), "live mode only requests the audited host"
    assert report["counts"]["extra_pages_audited"] == 0
    assert len(calls) == len(set(calls)), "each URL is fetched once"


def test_live_site_requires_https() -> None:
    with pytest.raises(ValueError):
        audit_mod.LiveSite("http://www.example.test")


def test_checkout_paths_cannot_escape_the_root(tmp_path: Path) -> None:
    (tmp_path / "site").mkdir()
    (tmp_path / "secret.html").write_text("x")
    checkout = audit_mod.RepoSite(tmp_path / "site", SITE)
    assert checkout.get(f"{SITE}/../secret.html") == (404, None)
    assert checkout.get(f"{SITE}/%2e%2e/secret.html") == (404, None)


def test_cli_check_flag_and_outputs(tmp_path: Path) -> None:
    build_site(tmp_path)
    json_out, md_out = tmp_path / "r.json", tmp_path / "r.md"
    args = ["--root", str(tmp_path), "--site", SITE, "--json", str(json_out), "--markdown", str(md_out)]
    assert audit_mod.main(args) == 0
    assert audit_mod.main(args + ["--check"]) == 1, "noindex, invalid JSON-LD and a phone conflict are errors"
    assert json.loads(json_out.read_text())["mode"] == "checkout"
    assert "## Findings by rule" in md_out.read_text()


def test_cli_unreadable_homepage_is_a_usage_error(tmp_path: Path) -> None:
    assert audit_mod.main(["--root", str(tmp_path), "--site", SITE]) == 2


def test_repository_checkout_audit_runs() -> None:
    root = Path(__file__).resolve().parents[1]
    report = audit_mod.audit(audit_mod.RepoSite(root, "https://www.clearglassinc.com"), check_links=False)
    assert report["counts"]["pages_audited"] > 0
    assert report["canonical_nap"]["locality"] == "Burlington"
