#!/usr/bin/env python3
"""Build the ClearGlass Inc. homepage (``index.html``) from the site config.

    python3 website/build.py            # write index.html (idempotent)
    python3 website/build.py --check    # exit 1 if index.html is stale

The site is served by GitHub Pages straight from the repository root, so the
generated ``index.html`` is committed. ``--check`` reuses the copyright year
already in the file, so the check tests content, not the calendar; the page's
script keeps the visible year current.

stdlib only.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUTPUT = ROOT / "index.html"

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from components import page  # noqa: E402
from site_config import SITE, SiteConfig  # noqa: E402

# Block-level tags that start on a new line, so diffs of the generated file
# stay readable. Whitespace between these tags is not rendered.
_BREAK_BEFORE = re.compile(
    r"(?=<(?:meta|link|script|title|section|/section|header|/header|footer|/footer|"
    r"main|/main|nav|article|details|form|fieldset|/fieldset|div class=\"(?:container|field|"
    r"hero__|section-head|notice|empty-state|footer__|utility)|li|/ul|/ol|ul|ol|h1|h2|h3|p|body|/body|"
    r"head|/head|aside|/aside|picture|a class=\"skip-link))"
)
_YEAR = re.compile(r"<span data-year>(\d{4})</span>")


def render(site: SiteConfig = SITE, year: int | None = None) -> str:
    html = page(site, year or date.today().year)
    head, sep, rest = html.partition("<html")
    body = _BREAK_BEFORE.sub("\n", sep + rest)
    return head + body.replace("\n\n", "\n")


def check_config(site: SiteConfig) -> list[str]:
    """Structural problems that would make the page wrong or dishonest."""
    problems: list[str] = []
    cname = ROOT / "CNAME"
    if cname.exists():
        host = cname.read_text(encoding="utf-8").strip()
        if site.url.rstrip("/") != f"https://{host}":
            problems.append(f"site.url {site.url!r} does not match CNAME {host!r}")
    ids = {"top", "main", "capabilities", "approach", "insights", "about", "contact"}
    for link in (*site.nav, site.primary_cta, site.secondary_cta, site.header_cta):
        if link.href.startswith("#") and link.href[1:] not in ids:
            problems.append(f"link {link.label!r} points at missing section {link.href}")
    for path in (site.monogram, site.hero_image.fallback, *(p for p, _ in site.hero_image.webp_sources)):
        if not (ROOT / path).is_file():
            problems.append(f"asset missing: {path}")
    for article in site.articles:
        if not article.href.startswith(("http://", "https://")) and not (ROOT / article.href).exists():
            problems.append(f"article {article.title!r} links to a page that does not exist")
    sitemap = (ROOT / "sitemap.xml").read_text(encoding="utf-8") if (ROOT / "sitemap.xml").exists() else ""
    for link in site.explore:
        if not (ROOT / link.href).is_file():
            problems.append(f"explore link {link.label!r} points at a missing page: {link.href}")
        elif f"<loc>{site.url.rstrip('/')}/{link.href}</loc>" not in sitemap:
            problems.append(f"explore link {link.label!r} is not a canonical sitemap URL: {link.href}")
    if site.contact.form_endpoint and not site.contact.form_endpoint.startswith("https://"):
        problems.append("contact.form_endpoint must be an https:// URL")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if index.html is stale")
    args = parser.parse_args(argv)

    problems = check_config(SITE)
    if problems:
        for problem in problems:
            print(f"config: {problem}", file=sys.stderr)
        return 1

    if args.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        found = _YEAR.search(current)
        expected = render(SITE, int(found.group(1)) if found else None)
        if current != expected:
            print("index.html is stale: run python3 website/build.py", file=sys.stderr)
            return 1
        print("index.html is up to date")
        return 0

    html = render(SITE)
    if OUTPUT.exists() and OUTPUT.read_text(encoding="utf-8") == html:
        print("index.html unchanged")
    else:
        OUTPUT.write_text(html, encoding="utf-8")
        print(f"wrote {OUTPUT.relative_to(ROOT)} ({len(html.encode('utf-8')):,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
