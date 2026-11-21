#!/usr/bin/env python3
"""Validate the site's crawl and indexing signals against the repository.

Checks, all offline against the files GitHub Pages serves:

* robots.txt: a ``User-agent: *`` group that does not block the whole site,
  and Sitemap directives that are HTTPS, on the canonical host from ``CNAME``,
  and point at sitemap files that exist.
* Every sitemap robots.txt lists: valid XML; every <loc> absolute HTTPS on
  the canonical host; no duplicates; each URL maps to a file in the
  repository; no page is ``noindex``; each page's own canonical (if any)
  is that same URL; <lastmod> values are W3C dates.
* The homepage (index.html): exactly one canonical (the site root), one
  non-empty <title>, one non-empty meta description, one <h1>, no noindex,
  JSON-LD that parses, and WebSite and Organization entities whose url is
  the site root.

Usage::

    python3 tools/validate_seo.py                    # exit 1 on any problem
    python3 tools/validate_seo.py --prune-sitemaps   # drop URLs with no page, or
                                                     # that are not canonical, then validate

Prints file names and URLs only: never environment variables, tokens, or
request data. Standard library only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse

NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
W3C_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2}))?$")
URL_BLOCK = re.compile(r"[ \t]*<url>\s*<loc>\s*([^<]+?)\s*</loc>.*?</url>[ \t]*\r?\n?", re.S)


class _Head(HTMLParser):
    """Collects the tags that carry indexing signals."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.canonicals: list[str] = []
        self.titles: list[str] = []
        self.descriptions: list[str] = []
        self.robots: list[str] = []
        self.h1 = 0
        self.jsonld: list[str] = []
        self._in: str | None = None
        self._buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "link" and "canonical" in a.get("rel", "").lower().split():
            self.canonicals.append(a.get("href", ""))
        elif tag == "meta" and a.get("name", "").lower() == "description":
            self.descriptions.append(a.get("content", "").strip())
        elif tag == "meta" and a.get("name", "").lower() == "robots":
            self.robots.append(a.get("content", "").lower())
        elif tag == "h1":
            self.h1 += 1
        elif tag == "title" or (tag == "script" and a.get("type", "").lower() == "application/ld+json"):
            self._in, self._buf = tag, []

    def handle_data(self, data):
        if self._in:
            self._buf.append(data)

    def handle_endtag(self, tag):
        if self._in and tag == self._in:
            text = "".join(self._buf)
            (self.titles if tag == "title" else self.jsonld).append(text.strip())
            self._in = None


def _head(path: Path) -> _Head:
    parser = _Head()
    parser.feed(path.read_text(encoding="utf-8", errors="replace"))
    return parser


def canonical_origin(root: Path) -> str:
    host = (root / "CNAME").read_text(encoding="utf-8").strip().lower()
    return f"https://{host}"


def url_to_file(root: Path, url: str) -> Path:
    path = unquote(urlparse(url).path).lstrip("/")
    if path == "" or path.endswith("/"):
        return root / path / "index.html"
    candidate = root / path
    if candidate.suffix or candidate.exists():
        return candidate
    html = root / f"{path}.html"
    return html if html.exists() else root / path / "index.html"


def _page_problem(root: Path, origin: str, url: str) -> str | None:
    """Why this URL should not be in a sitemap, or None."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or f"https://{parsed.netloc.lower()}" != origin:
        return "not HTTPS on the canonical host"
    page = url_to_file(root, url)
    if not page.is_file():
        return "no such page in the repository"
    if page.suffix.lower() in {".html", ".htm"}:
        head = _head(page)
        if any("noindex" in r for r in head.robots):
            return "page is noindex"
        if head.canonicals and head.canonicals[0].rstrip("/") != url.rstrip("/"):
            return f"page declares a different canonical ({head.canonicals[0]})"
    return None


def sitemap_files(root: Path, origin: str) -> tuple[list[Path], list[str]]:
    errors: list[str] = []
    robots = root / "robots.txt"
    if not robots.is_file():
        return [root / "sitemap.xml"], ["robots.txt is missing"]
    lines = [ln.split("#", 1)[0].strip() for ln in robots.read_text(encoding="utf-8").splitlines()]
    agent, star_disallow, sitemaps = None, [], []
    for ln in lines:
        key, _, value = ln.partition(":")
        key, value = key.strip().lower(), value.strip()
        if key == "user-agent":
            agent = value
        elif key == "disallow" and agent == "*":
            star_disallow.append(value)
        elif key == "sitemap":
            sitemaps.append(value)
    if "/" in star_disallow:
        errors.append("robots.txt: 'User-agent: *' disallows the whole site")
    if f"{origin}/sitemap.xml" not in sitemaps:
        errors.append(f"robots.txt: no 'Sitemap: {origin}/sitemap.xml' directive")
    files = []
    for s in sitemaps:
        if not s.startswith(origin + "/"):
            errors.append(f"robots.txt: sitemap not on the canonical host: {s}")
            continue
        f = url_to_file(root, s)
        (files.append(f) if f.is_file() else errors.append(f"robots.txt: sitemap file missing: {s}"))
    return files, errors


def check_sitemap(root: Path, origin: str, path: Path) -> list[str]:
    name = path.relative_to(root).as_posix()
    try:
        tree = ET.parse(path).getroot()
    except ET.ParseError as exc:
        return [f"{name}: invalid XML ({exc})"]
    if tree.tag not in (f"{NS}urlset", f"{NS}sitemapindex"):
        return [f"{name}: root element is not a sitemap urlset or sitemapindex"]
    errors, seen = [], set()
    for entry in tree:
        loc = entry.findtext(f"{NS}loc", "").strip()
        if loc in seen:
            errors.append(f"{name}: duplicate URL {loc}")
        seen.add(loc)
        lastmod = entry.findtext(f"{NS}lastmod")
        if lastmod is not None and not W3C_DATE.match(lastmod.strip()):
            errors.append(f"{name}: invalid lastmod for {loc}")
        if tree.tag == f"{NS}sitemapindex":
            if not url_to_file(root, loc).is_file():
                errors.append(f"{name}: child sitemap missing: {loc}")
            continue
        problem = _page_problem(root, origin, loc)
        if problem:
            errors.append(f"{name}: {loc}: {problem}")
    return errors


def check_homepage(root: Path, origin: str) -> list[str]:
    page = root / "index.html"
    if not page.is_file():
        return ["index.html is missing"]
    head, errors = _head(page), []
    home = origin + "/"
    if head.canonicals != [home]:
        errors.append(f"index.html: expected exactly one canonical {home}, found {head.canonicals}")
    if len(head.titles) != 1 or not head.titles[0]:
        errors.append(f"index.html: expected one non-empty <title>, found {len(head.titles)}")
    if len(head.descriptions) != 1 or not head.descriptions[0]:
        errors.append(f"index.html: expected one non-empty meta description, found {len(head.descriptions)}")
    if head.h1 != 1:
        errors.append(f"index.html: expected one <h1>, found {head.h1}")
    if any("noindex" in r for r in head.robots):
        errors.append("index.html: homepage is noindex")
    entities = []
    for block in head.jsonld:
        try:
            data = json.loads(block)
        except json.JSONDecodeError as exc:
            errors.append(f"index.html: JSON-LD does not parse ({exc.msg})")
            continue
        for item in (data if isinstance(data, list) else [data]):
            entities.extend(item.get("@graph", [item]) if isinstance(item, dict) else [])
    for kind in ("WebSite", "Organization"):
        found = [e for e in entities if e.get("@type") == kind]
        if not found:
            errors.append(f"index.html: JSON-LD has no {kind}")
        elif any(e.get("url") != home for e in found):
            errors.append(f"index.html: JSON-LD {kind} url is not {home}")
    return errors


def prune_sitemaps(root: Path, origin: str, files: list[Path]) -> int:
    removed = 0
    for path in files:
        text = path.read_text(encoding="utf-8")
        if "<urlset" not in text:
            continue

        def keep(match: re.Match) -> str:
            nonlocal removed
            if _page_problem(root, origin, match.group(1)):
                removed += 1
                print(f"pruned {path.name}: {match.group(1)}")
                return ""
            return match.group(0)

        new = URL_BLOCK.sub(keep, text)
        if new != text:
            ET.fromstring(new.encode("utf-8"))  # never write invalid XML
            path.write_text(new, encoding="utf-8")
    return removed


def run(root: Path, prune: bool = False) -> list[str]:
    origin = canonical_origin(root)
    files, errors = sitemap_files(root, origin)
    if prune:
        print(f"removed {prune_sitemaps(root, origin, files)} sitemap URL(s)")
    for f in files:
        errors += check_sitemap(root, origin, f)
    return errors + check_homepage(root, origin)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    ap.add_argument("--prune-sitemaps", action="store_true",
                    help="remove sitemap URLs with no page, or that are not canonical, then validate")
    args = ap.parse_args(argv)
    errors = run(args.root.resolve(), prune=args.prune_sitemaps)
    for error in errors:
        print(f"FAIL {error}")
    print(f"validate_seo: {len(errors)} problem(s)" if errors else "validate_seo: OK")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
