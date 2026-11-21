"""Contract tests for the generated homepage (index.html).

Runs in the Baseline CI pytest job, stdlib only. Browser-level behaviour
(layout at six widths, menu keyboard handling, reduced motion, no-JS) is
covered by tests/browser/homepage-audit.mjs.
"""

from __future__ import annotations

import dataclasses
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEBSITE = ROOT / "website"
INDEX = ROOT / "index.html"
CSS = ROOT / "assets" / "site" / "css" / "clearglass.css"

sys.path.insert(0, str(WEBSITE))
import build  # noqa: E402
from components import page  # noqa: E402
from site_config import SITE, Article, Contact, Person  # noqa: E402


class Collector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[tuple[str, dict[str, str]]] = []
        self.text: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, {k: v or "" for k, v in attrs}))
        if tag in {"script", "style"}:
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.text.append(data)


def parse(html: str) -> Collector:
    collector = Collector()
    collector.feed(html)
    return collector


@pytest.fixture(scope="module")
def doc() -> Collector:
    return parse(INDEX.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def visible_text(doc: Collector) -> str:
    return " ".join(" ".join(doc.text).split())


def test_index_is_fresh_and_config_is_valid() -> None:
    assert build.check_config(SITE) == []
    assert build.main(["--check"]) == 0, "run: python3 website/build.py"


def test_local_references_exist(doc: Collector) -> None:
    refs: set[str] = set()
    for _, attrs in doc.tags:
        for key in ("src", "href"):
            if key in attrs:
                refs.add(attrs[key])
        for key in ("srcset", "imagesrcset"):
            refs.update(part.strip().split(" ")[0] for part in attrs.get(key, "").split(",") if part.strip())
    css_urls = re.findall(r"url\(\"?([^\")]+)\"?\)", CSS.read_text(encoding="utf-8"))
    missing = [r for r in refs if r and not r.startswith(("#", "http", "mailto:")) and not (ROOT / r).exists()]
    missing += [u for u in css_urls if not u.startswith("data:") and not (CSS.parent / u).resolve().exists()]
    assert missing == []


def test_page_loads_nothing_from_third_parties(doc: Collector) -> None:
    external = [
        attrs.get("src") or attrs.get("href")
        for tag, attrs in doc.tags
        if tag in {"script", "img", "source", "link", "iframe"}
        and (attrs.get("src") or attrs.get("href") or "").startswith(("http:", "https:", "//"))
        and attrs.get("rel") != "canonical"
    ]
    assert external == []


def test_in_page_links_resolve(doc: Collector) -> None:
    ids = {attrs["id"] for _, attrs in doc.tags if "id" in attrs}
    targets = {attrs["href"][1:] for tag, attrs in doc.tags if tag == "a" and attrs.get("href", "").startswith("#")}
    assert targets - ids == set()
    # Old homepage anchors still linked from other pages keep landing somewhere.
    assert {"contact", "services", "products", "vision", "founder"} <= ids


def test_document_structure(doc: Collector) -> None:
    tags = [t for t, _ in doc.tags]
    assert tags.count("h1") == 1
    levels = [int(t[1]) for t in tags if re.fullmatch(r"h[1-6]", t)]
    assert all(b <= a + 1 for a, b in zip(levels, levels[1:])), levels
    assert tags.count("main") == 1 and "header" in tags and "footer" in tags
    first_link = next(attrs for tag, attrs in doc.tags if tag == "a")
    assert first_link.get("href") == "#main" and "skip-link" in first_link.get("class", "")
    html_attrs = next(attrs for tag, attrs in doc.tags if tag == "html")
    assert html_attrs.get("lang", "").startswith("en")


def test_images_have_alt_and_dimensions(doc: Collector) -> None:
    for tag, attrs in doc.tags:
        if tag == "img":
            assert "alt" in attrs, attrs
            assert attrs.get("width") and attrs.get("height"), attrs
    hero = [a for t, a in doc.tags if t == "img" and "hero__img" in a.get("class", "")]
    assert len(hero) == 1 and len(hero[0]["alt"]) > 40


def test_metadata_uses_the_configured_domain(doc: Collector) -> None:
    host = (ROOT / "CNAME").read_text(encoding="utf-8").strip()
    canonical = next(a["href"] for t, a in doc.tags if t == "link" and a.get("rel") == "canonical")
    assert canonical == f"https://{host}/"
    og_image = next(a["content"] for t, a in doc.tags if t == "meta" and a.get("property") == "og:image")
    assert og_image.startswith(canonical)
    assert (ROOT / og_image.removeprefix(canonical)).is_file()


# Things the page must never claim without evidence (see site_config docstring).
FORBIDDEN = [
    r"\bunclassified\b", r"\bclassified\b", r"\bclearance\b", r"\b2040\b",
    r"\bcertified\b", r"\bguarantee", r"\btestimonial", r"\baward", r"\btrusted by\b",
    r"\bgovernment\b", r"\bpartnered\b", r"\b\d+%",
]


@pytest.mark.parametrize("pattern", FORBIDDEN)
def test_no_unsupported_claims(visible_text: str, pattern: str) -> None:
    assert not re.search(pattern, visible_text, re.IGNORECASE)


def test_sentinel_core_is_labelled_as_a_demonstration() -> None:
    html = INDEX.read_text(encoding="utf-8")
    sentinel = html[html.index('<details class="sentinel"'):html.index("</details>")]
    text = " ".join(parse(sentinel).text).lower()
    assert "interface demo" in text and "not connected" in text
    assert not re.search(r"\b(online|secure|protected|live monitoring)\b", text)


def test_contact_form_is_off_and_explained_without_an_endpoint() -> None:
    assert SITE.contact.form_endpoint is None, "update this test when an endpoint is configured"
    html = INDEX.read_text(encoding="utf-8")
    assert '<fieldset class="contact-form__fields" disabled>' in html
    assert "Online submission is not set up yet." in html
    assert "mailto:" not in html  # no address is confirmed yet
    assert not re.search(r"message (was )?sent|thank you", html, re.IGNORECASE)


def test_configured_endpoint_enables_the_form() -> None:
    site = dataclasses.replace(SITE, contact=Contact(email="hello@example.com", form_endpoint="https://forms.example/f/x"))
    html = page(site, 2026)
    assert 'action="https://forms.example/f/x" method="post"' in html
    assert "disabled>" not in html and "not set up" not in html
    assert 'href="mailto:hello@example.com"' in html


def test_text_is_escaped() -> None:
    hostile = dataclasses.replace(SITE, supporting='<script>alert("x")</script>', tagline="A & B")
    html = page(hostile, 2026)
    assert "<script>alert" not in html
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;" in html
    assert "A &amp; B" in html


def test_insights_empty_state_and_article_cards() -> None:
    assert "No articles published yet" in page(SITE, 2026)
    article = Article("Title", "Summary", "https://example.com/a", "2026-12-01", "Governance")
    html = page(dataclasses.replace(SITE, articles=(article,)), 2026)
    assert "No articles published yet" not in html
    assert '<time datetime="2026-12-01">December 1, 2026</time>' in html


def test_people_render_only_when_configured() -> None:
    assert "Leadership" not in page(SITE, 2026)
    person = Person("A. Person", "Role", "Bio.")
    assert "Leadership" in page(dataclasses.replace(SITE, people=(person,)), 2026)


def test_animation_only_runs_when_motion_is_allowed() -> None:
    css = CSS.read_text(encoding="utf-8")
    depth = 0
    allowed_depth = None
    for line in css.splitlines():
        if "prefers-reduced-motion: no-preference" in line:
            allowed_depth = depth
        if re.search(r"^\s*animation\s*:", line):
            assert allowed_depth is not None, f"animation outside no-preference block: {line.strip()}"
        depth += line.count("{") - line.count("}")
        if allowed_depth is not None and depth <= allowed_depth:
            allowed_depth = None
    assert "prefers-reduced-motion: reduce" in css


def test_fonts_ship_with_their_licences() -> None:
    fonts = ROOT / "assets" / "site" / "fonts"
    for family in ("Cormorant-Garamond", "Urbanist", "IBM-Plex-Mono"):
        assert "SIL Open Font License" in (fonts / f"OFL-{family}.txt").read_text(encoding="utf-8")
