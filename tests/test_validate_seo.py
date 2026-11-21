"""Tests for tools/validate_seo.py: the repository passes, and each defect it
guards against makes it fail. Runs in Baseline CI's pytest job (stdlib only)."""

from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import validate_seo  # noqa: E402

ORIGIN = "https://www.example.org"
GOOD_HOME = f"""<!DOCTYPE html><html lang="en"><head>
<title>Example Inc. | Secure software</title>
<meta name="description" content="Example Inc. builds secure software.">
<link rel="canonical" href="{ORIGIN}/">
<script type="application/ld+json">{json.dumps({"@context": "https://schema.org", "@graph": [
    {"@type": "WebSite", "@id": ORIGIN + "/#website", "url": ORIGIN + "/", "name": "Example Inc."},
    {"@type": "Organization", "@id": ORIGIN + "/#organization", "url": ORIGIN + "/", "name": "Example Inc."}]})}</script>
</head><body><h1>Example Inc.</h1><a href="about.html">About</a></body></html>"""
GOOD_ABOUT = f'<html><head><link rel="canonical" href="{ORIGIN}/about.html"></head><body><h1>About</h1></body></html>'


def sitemap(*urls: str) -> str:
    body = "".join(f"  <url>\n    <loc>{u}</loc>\n  </url>\n" for u in urls)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{body}</urlset>\n'


@pytest.fixture
def site(tmp_path: Path) -> Path:
    (tmp_path / "CNAME").write_text("www.example.org\n")
    (tmp_path / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {ORIGIN}/sitemap.xml\n")
    (tmp_path / "sitemap.xml").write_text(sitemap(f"{ORIGIN}/", f"{ORIGIN}/about.html"))
    (tmp_path / "index.html").write_text(GOOD_HOME)
    (tmp_path / "about.html").write_text(GOOD_ABOUT)
    return tmp_path


def problems(root: Path) -> list[str]:
    return validate_seo.run(root)


def test_repository_passes() -> None:
    assert validate_seo.main(["--root", str(ROOT)]) == 0


def test_valid_fixture_passes(site: Path) -> None:
    assert problems(site) == []


@pytest.mark.parametrize("old, new, expected", [
    ("<h1>Example Inc.</h1>", "<h1>A</h1><h1>B</h1>", "one <h1>"),
    ('<meta name="description" content="Example Inc. builds secure software.">', "", "meta description"),
    ("<title>Example Inc. | Secure software</title>", "<title></title>", "<title>"),
    (f'<link rel="canonical" href="{ORIGIN}/">', f'<link rel="canonical" href="{ORIGIN}/"><link rel="canonical" href="{ORIGIN}/x">', "canonical"),
    (f'<link rel="canonical" href="{ORIGIN}/">', '<link rel="canonical" href="https://example.org/">', "canonical"),
    ('"@type": "WebSite"', '"@type": "Thing"', "no WebSite"),
    ('"@type": "Organization"', '"@type": "Thing"', "no Organization"),
    ('{"@context"', '{,"@context"', "does not parse"),
    ("</head>", '<meta name="robots" content="noindex"></head>', "noindex"),
])
def test_homepage_defects_fail(site: Path, old: str, new: str, expected: str) -> None:
    page = site / "index.html"
    page.write_text(page.read_text().replace(old, new, 1))
    found = problems(site)
    assert any(expected in p for p in found), found


@pytest.mark.parametrize("urls, expected", [
    ((f"{ORIGIN}/", "http://www.example.org/about.html"), "not HTTPS on the canonical host"),
    ((f"{ORIGIN}/", "https://evil.example.com/about.html"), "not HTTPS on the canonical host"),
    ((f"{ORIGIN}/", f"{ORIGIN}/about.html", f"{ORIGIN}/about.html"), "duplicate URL"),
    ((f"{ORIGIN}/", f"{ORIGIN}/missing.html"), "no such page"),
])
def test_sitemap_defects_fail(site: Path, urls: tuple[str, ...], expected: str) -> None:
    (site / "sitemap.xml").write_text(sitemap(*urls))
    found = problems(site)
    assert any(expected in p for p in found), found


def test_non_canonical_page_in_sitemap_fails(site: Path) -> None:
    (site / "about.html").write_text(GOOD_ABOUT.replace("/about.html", "/index.html"))
    assert any("different canonical" in p for p in problems(site))


def test_invalid_sitemap_xml_fails(site: Path) -> None:
    (site / "sitemap.xml").write_text("<urlset><url>")
    assert any("invalid XML" in p for p in problems(site))


@pytest.mark.parametrize("robots, expected", [
    ("User-agent: *\nAllow: /\n", "no 'Sitemap:"),
    (f"User-agent: *\nDisallow: /\nSitemap: {ORIGIN}/sitemap.xml\n", "disallows the whole site"),
    (f"User-agent: *\nSitemap: {ORIGIN}/sitemap.xml\nSitemap: https://other.example/s.xml\n", "not on the canonical host"),
])
def test_robots_defects_fail(site: Path, robots: str, expected: str) -> None:
    (site / "robots.txt").write_text(robots)
    assert any(expected in p for p in problems(site))


def test_prune_removes_only_bad_urls_and_keeps_valid_xml(site: Path) -> None:
    (site / "sitemap.xml").write_text(sitemap(f"{ORIGIN}/", f"{ORIGIN}/gone.html", f"{ORIGIN}/about.html"))
    assert validate_seo.main(["--root", str(site), "--prune-sitemaps"]) == 0
    text = (site / "sitemap.xml").read_text()
    ET.fromstring(text.encode())
    assert "gone.html" not in text and f"{ORIGIN}/about.html" in text and f"<loc>{ORIGIN}/</loc>" in text
