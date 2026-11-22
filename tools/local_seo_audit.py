#!/usr/bin/env python3
"""Audit a static site for local-search hygiene: sitemaps, structured data, NAP, local signals.

Two modes, both read-only:
  --root PATH   audit the HTML files in a checkout, offline. A checkout is not
                necessarily what is deployed (on 2026-11-21 this repository was
                not the source of www.clearglassinc.com), so confirm with --live
                before acting on a checkout finding.
  --live URL    audit the deployed site with GET requests: robots.txt, the
                sitemaps it names, every sitemap URL, and the internal links
                found on those pages. Same host only; a redirect to another host
                or to plain http is refused; requests run one at a time.

Checks:
  - sitemaps named in robots.txt are served; every sitemap URL is served (live)
    or has a source file (checkout); sitemap pages are not noindexed and do not
    declare their canonical URL as another page
  - every JSON-LD block parses
  - name, phone, email, and locality in the site's own structured data match the
    canonical record: the homepage's structured data, or --nap FILE
  - fictional 555-0100 to 555-0199 phone numbers in shipped HTML
  - titles and meta descriptions on sitemap pages
  - whether any sitemap page names the target locality in its title or H1

Not checked: rankings, Google Business Profile data, reviews, or anything that
needs an account. Those come from exports; see tools/geo_grid.py.

Exit status: 0 when the report is written; 1 with --check when an error-severity
finding exists; 2 on a usage error or an unreadable homepage. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0.0"
USER_AGENT = "clearglass-local-seo-audit/1.0 (+read-only)"
DEFAULT_LOCALITY = "Burlington"
BRAND_TOKEN = "clearglass"
ORG_TYPES = frozenset({"Organization", "Corporation", "LocalBusiness", "ProfessionalService",
                       "OnlineBusiness", "Store"})
# NANP reserves 555-0100 through 555-0199 for fiction. A separator is required so
# that digit runs inside hashes and IDs do not match.
FICTIONAL_PHONE = re.compile(r"(?<![\d-])555[\s.-]01\d{2}(?!\d)")
SKIP_LINK_PREFIXES = ("#", "mailto:", "tel:", "javascript:", "data:", "sms:")
MAX_BODY_BYTES = 8_000_000
MAX_NESTED_SITEMAPS = 50

RULES: dict[str, tuple[str, str]] = {
    "homepage-unavailable": ("error", "The homepage could not be read."),
    "robots-unavailable": ("warning", "robots.txt could not be read; sitemap discovery fell back to /sitemap.xml."),
    "robots-sitemap-unavailable": ("error", "A sitemap named in robots.txt is not served."),
    "sitemap-unparseable": ("error", "A sitemap is not valid XML."),
    "sitemap-url-off-host": ("error", "A sitemap lists a URL on another host."),
    "sitemap-url-unavailable": ("error", "A sitemap URL is not served (live) or has no source file (checkout)."),
    "sitemap-page-noindex": ("error", "A sitemap page tells search engines not to index it."),
    "canonical-mismatch": ("warning", "A sitemap page declares a different URL as canonical."),
    "jsonld-invalid": ("error", "A JSON-LD block does not parse, so search engines ignore it."),
    "nap-phone-conflict": ("error", "Structured data lists a phone number that differs from the canonical record."),
    "nap-locality-conflict": ("error", "Structured data lists a locality that differs from the canonical record."),
    "nap-email-conflict": ("warning", "Structured data lists an email that differs from the canonical record."),
    "nap-name-variant": ("warning", "Structured data spells the business name differently from the canonical record."),
    "placeholder-phone": ("warning", "A fictional 555-01xx phone number ships in the page source."),
    "missing-title": ("warning", "A sitemap page has no <title>."),
    "missing-meta-description": ("info", "A sitemap page has no meta description."),
    "internal-link-unavailable": ("warning", "An internal link points to a page that is not served or has no source file."),
    "no-local-landing-page": ("warning", "No sitemap page names the target locality in its title or H1."),
}


@dataclass(frozen=True)
class Finding:
    rule: str
    severity: str
    path: str
    line: int | None
    detail: str


def finding(rule: str, path: str, detail: str, line: int | None = None, severity: str | None = None) -> Finding:
    return Finding(rule, severity or RULES[rule][0], path, line, detail)


# --------------------------------------------------------------------------- #
# Page parsing
# --------------------------------------------------------------------------- #

class PageParser(HTMLParser):
    """Collects the head metadata, H1 text, links, JSON-LD blocks, and visible text."""

    _HIDDEN = frozenset({"script", "style", "noscript", "template"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title: str | None = None
        self.meta_description: str | None = None
        self.robots: list[str] = []
        self.canonical: str | None = None
        self.h1: list[str] = []
        self.links: list[tuple[str, int]] = []
        self.jsonld: list[tuple[str, int]] = []
        self.text: list[str] = []
        self._title_buf: list[str] | None = None
        self._h1_depth = 0
        self._h1_buf: list[str] = []
        self._svg_depth = 0
        self._hidden_depth = 0
        self._jsonld_buf: list[str] | None = None
        self._jsonld_line = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): (v or "") for k, v in attrs}
        line = self.getpos()[0]
        if tag == "svg":
            self._svg_depth += 1
        elif tag == "title" and self.title is None and not self._svg_depth:
            self._title_buf = []
        elif tag == "meta":
            name = a.get("name", "").lower()
            if name == "description" and self.meta_description is None:
                self.meta_description = a.get("content", "")
            elif name in ("robots", "googlebot"):
                self.robots.append(a.get("content", "").lower())
        elif tag == "link" and "canonical" in a.get("rel", "").lower().split() and self.canonical is None:
            self.canonical = a.get("href", "")
        elif tag == "h1":
            self._h1_depth += 1
            if self._h1_depth == 1:
                self._h1_buf = []
        elif tag == "a" and a.get("href"):
            self.links.append((a["href"], line))
        elif tag == "script" and a.get("type", "").strip().lower() == "application/ld+json":
            self._jsonld_buf = []
            self._jsonld_line = line
        if tag in self._HIDDEN:
            self._hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "svg" and self._svg_depth:
            self._svg_depth -= 1
        elif tag == "title" and self._title_buf is not None:
            self.title = " ".join("".join(self._title_buf).split())
            self._title_buf = None
        elif tag == "h1" and self._h1_depth:
            self._h1_depth -= 1
            if self._h1_depth == 0:
                self.h1.append(" ".join("".join(self._h1_buf).split()))
        elif tag == "script" and self._jsonld_buf is not None:
            self.jsonld.append(("".join(self._jsonld_buf), self._jsonld_line))
            self._jsonld_buf = None
        if tag in self._HIDDEN and self._hidden_depth:
            self._hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._jsonld_buf is not None:
            self._jsonld_buf.append(data)
            return
        if self._title_buf is not None:
            self._title_buf.append(data)
        if self._h1_depth:
            self._h1_buf.append(data)
        if not self._hidden_depth:
            self.text.append(data)


def parse_page(html: str) -> PageParser:
    parser = PageParser()
    parser.feed(html)
    parser.close()
    return parser


def iter_nodes(value: Any) -> Iterator[dict[str, Any]]:
    """Yield every JSON-LD object that carries properties (not bare @id references)."""
    if isinstance(value, dict):
        if len(value) > 1 or "@id" not in value:
            yield value
        for child in value.values():
            yield from iter_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_nodes(child)


def node_types(node: dict[str, Any]) -> set[str]:
    raw = node.get("@type")
    return {str(t) for t in (raw if isinstance(raw, list) else [raw]) if t}


def norm_phone(value: Any) -> str:
    digits = re.sub(r"\D", "", str(value))
    return digits[1:] if len(digits) == 11 and digits.startswith("1") else digits


def norm_email(value: Any) -> str:
    text = str(value).strip().lower()
    return text[len("mailto:"):] if text.startswith("mailto:") else text


def norm_text(value: Any) -> str:
    return " ".join(str(value).split()).casefold()


def _locality(node: dict[str, Any]) -> str | None:
    address = node.get("address")
    if isinstance(address, dict) and address.get("addressLocality"):
        return str(address["addressLocality"])
    return None


def _as_list(value: Any) -> list[Any]:
    if value is None or value == "":
        return []
    return value if isinstance(value, list) else [value]


def own_nodes(nodes: list[dict[str, Any]], site_origin: str) -> list[dict[str, Any]]:
    """Organization-type nodes that describe this business, plus their contact points."""
    own = []
    for node in nodes:
        types = node_types(node)
        if types & ORG_TYPES:
            name = norm_text(node.get("name", ""))
            ident = str(node.get("@id") or node.get("url") or "")
            if BRAND_TOKEN in name.replace(" ", "") or ident.startswith(site_origin):
                own.append(node)
                own.extend(cp for cp in _as_list(node.get("contactPoint")) if isinstance(cp, dict))
    return own


# --------------------------------------------------------------------------- #
# Sites: a checkout on disk, or the deployed site over HTTPS
# --------------------------------------------------------------------------- #

class RepoSite:
    """Serves a checkout as if it were the site: a URL is 200 when its file exists."""

    mode = "checkout"

    def __init__(self, root: Path, site: str) -> None:
        self.root = root.resolve()
        self.site = site.rstrip("/")
        self.host = urllib.parse.urlsplit(self.site).hostname or ""

    def file_for(self, url: str) -> Path | None:
        path = urllib.parse.unquote(urllib.parse.urlsplit(url).path) or "/"
        if path.endswith("/"):
            path += "index.html"
        candidates = [path]
        if not Path(path).suffix:
            candidates += [path + ".html", path + "/index.html"]
        for candidate in candidates:
            file = (self.root / candidate.lstrip("/")).resolve()
            if (file == self.root or self.root in file.parents) and file.is_file():
                return file
        return None

    def get(self, url: str) -> tuple[int, str | None]:
        file = self.file_for(url)
        if file is None:
            return 404, None
        return 200, file.read_text(encoding="utf-8", errors="replace")

    def ref(self, url: str) -> str:
        file = self.file_for(url)
        return file.relative_to(self.root).as_posix() if file else urllib.parse.urlsplit(url).path

    def unavailable_detail(self, status: int) -> str:
        return "no source file in this checkout (the deployed site may still serve it; confirm with --live)"

    def extra_pages(self) -> list[str]:
        """Root-level HTML files, audited for structured data and placeholders even if unlisted."""
        return [f"{self.site}/{urllib.parse.quote(p.name)}" for p in sorted(self.root.glob("*.html"))]


Fetch = Callable[[str], tuple[int, str | None]]


class _SameHostRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, host: str) -> None:
        super().__init__()
        self.host = host

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        target = urllib.parse.urlsplit(newurl)
        if target.scheme != "https" or target.hostname != self.host:
            raise urllib.error.HTTPError(newurl, code, "redirect off the audited host refused", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def make_fetch(host: str, timeout: float = 20.0, pause: float = 0.1) -> Fetch:
    opener = urllib.request.build_opener(_SameHostRedirect(host))

    def fetch(url: str) -> tuple[int, str | None]:
        for attempt in range(2):
            time.sleep(pause if attempt == 0 else 1.5)
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            try:
                with opener.open(request, timeout=timeout) as response:
                    body = response.read(MAX_BODY_BYTES + 1)
                    if len(body) > MAX_BODY_BYTES:
                        return response.status, None
                    charset = response.headers.get_content_charset() or "utf-8"
                    return response.status, body.decode(charset, errors="replace")
            except urllib.error.HTTPError as exc:
                if exc.code in (429, 500, 502, 503, 504) and attempt == 0:
                    continue
                return exc.code, None
            except (urllib.error.URLError, TimeoutError, OSError):
                if attempt == 0:
                    continue
                return 0, None
        return 0, None

    return fetch


class LiveSite:
    mode = "live"

    def __init__(self, site: str, fetch: Fetch | None = None) -> None:
        self.site = site.rstrip("/")
        parts = urllib.parse.urlsplit(self.site)
        if parts.scheme != "https" or not parts.hostname:
            raise ValueError("--live needs an https:// URL")
        self.host = parts.hostname
        self._fetch = fetch or make_fetch(self.host)
        self._cache: dict[str, tuple[int, str | None]] = {}

    def get(self, url: str) -> tuple[int, str | None]:
        if url not in self._cache:
            self._cache[url] = self._fetch(url)
        return self._cache[url]

    def ref(self, url: str) -> str:
        return urllib.parse.urlsplit(url).path or "/"

    def unavailable_detail(self, status: int) -> str:
        return f"HTTP {status}" if status else "no response (network error or timeout)"

    def extra_pages(self) -> list[str]:
        return []


# --------------------------------------------------------------------------- #
# Audit
# --------------------------------------------------------------------------- #

def parse_sitemap(text: str) -> tuple[list[str], list[str]]:
    """Return (page URLs, nested sitemap URLs). Raises ET.ParseError on bad XML."""
    root = ET.fromstring(text)
    pages, nested = [], []
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag in ("url", "sitemap"):
            for child in element:
                if child.tag.rsplit("}", 1)[-1] == "loc" and child.text and child.text.strip():
                    (pages if tag == "url" else nested).append(child.text.strip())
    return pages, nested


def canonical_record(nodes: list[dict[str, Any]], source: str) -> dict[str, Any]:
    record: dict[str, Any] = {"name": None, "telephone": None, "email": None, "locality": None,
                              "source": source}
    orgs = [n for n in nodes if "Organization" in node_types(n)] + nodes
    for node in orgs:
        if record["name"] is None and node.get("name"):
            record["name"] = " ".join(str(node["name"]).split())
        if record["telephone"] is None and node.get("telephone"):
            record["telephone"] = str(node["telephone"])
        if record["email"] is None and node.get("email"):
            record["email"] = norm_email(node["email"])
        if record["locality"] is None and _locality(node):
            record["locality"] = _locality(node)
    return record


def _same_page(a: str, b: str) -> bool:
    def norm(url: str) -> tuple[str, str]:
        parts = urllib.parse.urlsplit(url)
        path = parts.path or "/"
        if path.endswith("/index.html"):
            path = path[: -len("index.html")]
        return (parts.hostname or "").lower(), path
    return norm(a) == norm(b)


def audit(site: RepoSite | LiveSite, *, locality: str = DEFAULT_LOCALITY,
          nap: dict[str, Any] | None = None, check_links: bool = True, link_cap: int = 400) -> dict[str, Any]:
    findings: list[Finding] = []
    origin = site.site
    home_url = origin + "/"
    # A checkout may not be what is deployed, so availability gaps there are warnings.
    severity = "error" if site.mode == "live" else "warning"
    status, home_html = site.get(home_url)
    if status != 200 or home_html is None:
        raise RuntimeError(f"homepage unavailable: {site.unavailable_detail(status)}")

    # Sitemaps
    sitemap_urls: list[str] = []
    status, robots = site.get(origin + "/robots.txt")
    if status == 200 and robots is not None:
        for line in robots.splitlines():
            key, _, value = line.partition(":")
            if key.strip().lower() == "sitemap" and value.strip():
                sitemap_urls.append(value.strip())
    else:
        findings.append(finding("robots-unavailable", "/robots.txt", site.unavailable_detail(status)))
    if not sitemap_urls:
        sitemap_urls = [origin + "/sitemap.xml"]

    page_urls: list[str] = []
    queue = list(dict.fromkeys(sitemap_urls))
    seen_sitemaps: set[str] = set()
    while queue and len(seen_sitemaps) < MAX_NESTED_SITEMAPS:
        sm_url = queue.pop(0)
        if sm_url in seen_sitemaps:
            continue
        seen_sitemaps.add(sm_url)
        if urllib.parse.urlsplit(sm_url).hostname != site.host:
            findings.append(finding("sitemap-url-off-host", sm_url, "sitemap is on another host; not fetched"))
            continue
        status, text = site.get(sm_url)
        if status != 200 or text is None:
            findings.append(finding("robots-sitemap-unavailable", site.ref(sm_url), site.unavailable_detail(status),
                                    severity=severity))
            continue
        try:
            pages, nested = parse_sitemap(text)
        except ET.ParseError as exc:
            findings.append(finding("sitemap-unparseable", site.ref(sm_url), str(exc)))
            continue
        queue.extend(nested)
        for url in pages:
            if urllib.parse.urlsplit(url).hostname != site.host:
                findings.append(finding("sitemap-url-off-host", site.ref(sm_url), url))
            elif url not in page_urls:
                page_urls.append(url)

    audited: dict[str, PageParser] = {}
    raw: dict[str, str] = {}
    available = 0
    for url in page_urls:
        status, html = site.get(url)
        if status != 200 or html is None:
            findings.append(finding("sitemap-url-unavailable", site.ref(url), site.unavailable_detail(status),
                                    severity=severity))
            continue
        available += 1
        audited[url] = parse_page(html)
        raw[url] = html
    if home_url not in audited and not any(_same_page(u, home_url) for u in audited):
        audited[home_url] = parse_page(home_html)
        raw[home_url] = home_html
    sitemap_set = set(page_urls)

    extras: dict[str, PageParser] = {}
    for url in site.extra_pages():
        if url in audited or any(_same_page(url, u) for u in audited):
            continue
        status, html = site.get(url)
        if status == 200 and html is not None:
            extras[url] = parse_page(html)
            raw[url] = html

    # Per-page checks
    parsed_nodes: dict[str, list[dict[str, Any]]] = {}
    for url, page in {**audited, **extras}.items():
        ref = site.ref(url)
        nodes: list[dict[str, Any]] = []
        for block, line in page.jsonld:
            try:
                nodes.extend(iter_nodes(json.loads(block)))
            except json.JSONDecodeError as exc:
                findings.append(finding("jsonld-invalid", ref, f"{exc.msg} (block line {exc.lineno})", line))
        parsed_nodes[url] = nodes
        for match in FICTIONAL_PHONE.finditer(raw[url]):
            line = raw[url].count("\n", 0, match.start()) + 1
            findings.append(finding("placeholder-phone", ref, f"fictional number {match.group(0)!r}", line))
        if url in sitemap_set:
            if any("noindex" in r for r in page.robots):
                findings.append(finding("sitemap-page-noindex", ref, "meta robots contains noindex"))
            if page.canonical:
                target = urllib.parse.urljoin(url, page.canonical)
                if not _same_page(target, url):
                    findings.append(finding("canonical-mismatch", ref, f"canonical is {target}"))
            if not page.title:
                findings.append(finding("missing-title", ref, "no <title> text"))
            if not (page.meta_description or "").strip():
                findings.append(finding("missing-meta-description", ref, "no meta description"))

    # Canonical NAP record
    home_key = next((u for u in audited if _same_page(u, home_url)), home_url)
    if nap is None:
        nap = canonical_record(own_nodes(parsed_nodes.get(home_key, []), origin), f"{site.ref(home_key)} JSON-LD")
    variants: dict[str, Counter[str]] = {k: Counter() for k in ("names", "telephones", "emails", "localities")}
    for url, nodes in parsed_nodes.items():
        ref = site.ref(url)
        for node in own_nodes(nodes, origin):
            name, tel, email, loc = node.get("name"), node.get("telephone"), node.get("email"), _locality(node)
            if name and "ContactPoint" not in node_types(node):
                variants["names"][" ".join(str(name).split())] += 1
                if nap.get("name") and norm_text(name) != norm_text(nap["name"]):
                    findings.append(finding("nap-name-variant", ref, f"{name!r} vs canonical {nap['name']!r}"))
            if tel:
                variants["telephones"][str(tel)] += 1
                if nap.get("telephone") and norm_phone(tel) != norm_phone(nap["telephone"]):
                    findings.append(finding("nap-phone-conflict", ref, f"{tel!r} vs canonical {nap['telephone']!r}"))
            if email:
                variants["emails"][norm_email(email)] += 1
                if nap.get("email") and norm_email(email) != norm_email(nap["email"]):
                    findings.append(finding("nap-email-conflict", ref,
                                            f"{norm_email(email)!r} vs canonical {nap['email']!r}"))
            if loc:
                variants["localities"][loc] += 1
                if nap.get("locality") and norm_text(loc) != norm_text(nap["locality"]):
                    findings.append(finding("nap-locality-conflict", ref, f"{loc!r} vs canonical {nap['locality']!r}"))

    # Local signals (sitemap pages and the homepage)
    target = locality.casefold()
    in_title = sorted(site.ref(u) for u, p in audited.items() if target in (p.title or "").casefold())
    in_h1 = sorted(site.ref(u) for u, p in audited.items() if any(target in h.casefold() for h in p.h1))
    mentions = {site.ref(u): " ".join(p.text).casefold().count(target) for u, p in audited.items()}
    area_served = sorted({site.ref(u) for u, nodes in parsed_nodes.items() if u in audited
                          for n in own_nodes(nodes, origin)
                          if target in json.dumps(n.get("areaServed", ""), ensure_ascii=False).casefold()})
    if not in_title and not in_h1:
        findings.append(finding("no-local-landing-page", "(site)",
                                f"no sitemap page has {locality!r} in its title or H1"))

    # Internal links
    links_checked, capped = 0, False
    if check_links:
        referrers: dict[str, list[str]] = {}
        for url, page in audited.items():
            for href, _line in page.links:
                href = href.strip()
                if not href or href.lower().startswith(SKIP_LINK_PREFIXES):
                    continue
                target_url = urllib.parse.urljoin(url, href)
                parts = urllib.parse.urlsplit(target_url)
                if parts.scheme not in ("http", "https") or parts.hostname != site.host:
                    continue
                clean = urllib.parse.urlunsplit(("https", parts.netloc, parts.path or "/", "", ""))
                referrers.setdefault(clean, [])
                if site.ref(url) not in referrers[clean]:
                    referrers[clean].append(site.ref(url))
        for target_url, refs in sorted(referrers.items()):
            if target_url in sitemap_set or any(_same_page(target_url, u) for u in audited):
                continue
            if links_checked >= link_cap:
                capped = True
                break
            links_checked += 1
            status, _ = site.get(target_url)
            if status != 200:
                shown = ", ".join(refs[:5]) + (f" and {len(refs) - 5} more" if len(refs) > 5 else "")
                findings.append(finding("internal-link-unavailable", site.ref(target_url),
                                        f"{site.unavailable_detail(status)}; linked from {shown}"))

    by_rule = Counter(f.rule for f in findings)
    by_severity = Counter(f.severity for f in findings)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "mode": site.mode,
        "site": origin,
        "locality": locality,
        "canonical_nap": nap,
        "counts": {
            "sitemaps": len(seen_sitemaps),
            "sitemap_urls": len(page_urls),
            "sitemap_urls_available": available,
            "pages_audited": len(audited),
            "extra_pages_audited": len(extras),
            "links_checked": links_checked,
            "links_capped": capped,
        },
        "local_signals": {
            "pages_with_locality_in_title": in_title,
            "pages_with_locality_in_h1": in_h1,
            "pages_mentioning_locality": sum(1 for n in mentions.values() if n),
            "top_mentions": dict(sorted(mentions.items(), key=lambda kv: (-kv[1], kv[0]))[:10]),
            "pages_with_locality_in_area_served": area_served,
        },
        "nap_variants": {k: dict(v.most_common()) for k, v in variants.items()},
        "summary": {
            "error": by_severity.get("error", 0),
            "warning": by_severity.get("warning", 0),
            "info": by_severity.get("info", 0),
            "by_rule": dict(sorted(by_rule.items())),
        },
        "findings": [asdict(f) for f in findings],
    }


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #

def render_markdown(report: dict[str, Any], per_rule: int = 12) -> str:
    c, s, sig, nap = report["counts"], report["summary"], report["local_signals"], report["canonical_nap"]
    lines = [
        f"# Local SEO audit: {report['site']} ({report['mode']})",
        "",
        f"Generated {report['generated_at']} by `tools/local_seo_audit.py`. Target locality: "
        f"{report['locality']}.",
        "",
        f"- Sitemaps read: {c['sitemaps']}; sitemap URLs: {c['sitemap_urls']}; available: "
        f"{c['sitemap_urls_available']}",
        f"- Pages audited: {c['pages_audited']} (plus {c['extra_pages_audited']} unlisted checkout pages); "
        f"internal link targets checked: {c['links_checked']}{' (capped)' if c['links_capped'] else ''}",
        f"- Findings: {s['error']} error, {s['warning']} warning, {s['info']} info",
        "",
        "## Canonical NAP record",
        "",
        f"- Source: {nap.get('source')}",
        f"- Name: {nap.get('name') or 'not declared'}",
        f"- Phone: {nap.get('telephone') or 'not declared'}",
        f"- Email: {nap.get('email') or 'not declared'}",
        f"- Locality: {nap.get('locality') or 'not declared'}",
        "",
        "## Local signals",
        "",
        f"- Pages with {report['locality']} in the title: {len(sig['pages_with_locality_in_title'])} "
        f"{sig['pages_with_locality_in_title'][:10]}",
        f"- Pages with {report['locality']} in an H1: {len(sig['pages_with_locality_in_h1'])} "
        f"{sig['pages_with_locality_in_h1'][:10]}",
        f"- Pages mentioning {report['locality']} in visible text: {sig['pages_mentioning_locality']}",
        f"- Pages whose structured data lists {report['locality']} in areaServed: "
        f"{sig['pages_with_locality_in_area_served']}",
        "",
        "## NAP variants in structured data",
        "",
    ]
    for kind, values in report["nap_variants"].items():
        lines.append(f"- {kind}: " + (", ".join(f"{k!r} x{v}" for k, v in values.items()) or "none"))
    lines += ["", "## Findings by rule", "", "| Rule | Severity | Count | Meaning |", "|---|---|---:|---|"]
    for rule, count in s["by_rule"].items():
        severity = next((f["severity"] for f in report["findings"] if f["rule"] == rule), RULES[rule][0])
        lines.append(f"| `{rule}` | {severity} | {count} | {RULES[rule][1]} |")
    for rule in s["by_rule"]:
        items = [f for f in report["findings"] if f["rule"] == rule]
        lines += ["", f"### `{rule}`", ""]
        for item in items[:per_rule]:
            where = f"{item['path']}:{item['line']}" if item["line"] else item["path"]
            lines.append(f"- `{where}`: {item['detail']}")
        if len(items) > per_rule:
            lines.append(f"- ... and {len(items) - per_rule} more (see the JSON report)")
    return "\n".join(lines) + "\n"


def load_nap(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not any(data.get(k) for k in ("name", "telephone", "email", "locality")):
        raise ValueError("--nap file needs at least one of name, telephone, email, locality")
    return {k: data.get(k) for k in ("name", "telephone", "email", "locality")} | {"source": str(path)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    where = parser.add_mutually_exclusive_group(required=True)
    where.add_argument("--root", type=Path, help="audit a checkout on disk")
    where.add_argument("--live", help="audit the deployed site, e.g. https://www.clearglassinc.com")
    parser.add_argument("--site", default="https://www.clearglassinc.com",
                        help="public origin the checkout is published at (checkout mode)")
    parser.add_argument("--locality", default=DEFAULT_LOCALITY)
    parser.add_argument("--nap", type=Path, help="JSON file with the canonical name/telephone/email/locality")
    parser.add_argument("--no-links", action="store_true", help="skip internal link checks")
    parser.add_argument("--link-cap", type=int, default=400)
    parser.add_argument("--json", type=Path, help="write the JSON report here")
    parser.add_argument("--markdown", type=Path, help="write a Markdown summary here")
    parser.add_argument("--check", action="store_true", help="exit 1 when an error-severity finding exists")
    args = parser.parse_args(argv)

    try:
        site: RepoSite | LiveSite
        if args.root is not None:
            if not args.root.is_dir():
                raise ValueError(f"{args.root} is not a directory")
            site = RepoSite(args.root, args.site)
        else:
            site = LiveSite(args.live)
        nap = load_nap(args.nap) if args.nap else None
        report = audit(site, locality=args.locality, nap=nap, check_links=not args.no_links,
                       link_cap=args.link_cap)
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"local-seo-audit: {exc}", file=sys.stderr)
        return 2

    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.json:
        args.json.write_text(text, encoding="utf-8")
    if args.markdown:
        args.markdown.write_text(render_markdown(report), encoding="utf-8")
    if not args.json and not args.markdown:
        sys.stdout.write(text)
    s = report["summary"]
    print(f"local-seo-audit: {report['mode']} {report['site']}: {report['counts']['pages_audited']} pages, "
          f"{s['error']} error, {s['warning']} warning, {s['info']} info", file=sys.stderr)
    return 1 if args.check and s["error"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
