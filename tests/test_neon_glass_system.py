"""Contract tests for the ClearGlass Neon Glass System.

Runs in the existing Baseline CI pytest job, stdlib only. Browser-level
behaviour (focus rings, reduced motion, reveal, broken-image fallback) is
covered separately by tests/browser/neon-system.mjs.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CSS = ROOT / "assets" / "css"
JS = ROOT / "assets" / "js"
SYSTEM = CSS / "cg-design-system.css"

SYSTEM_FILES = [
    CSS / "cg-design-system.css",
    CSS / "glass.css",
    CSS / "future-buttons.css",
    CSS / "cinematic-motion.css",
    CSS / "mission-control.css",
    JS / "cg-design-system.js",
    JS / "future-buttons.js",
    JS / "cinematic-motion.js",
]

# Max backdrop blur anywhere in the system, and in the always-on sticky nav.
BLUR_CEILING_PX = 18


def _read(path: Path) -> str:
    # A few uploaded pages are not valid UTF-8; their markup still scans fine.
    return path.read_text(encoding="utf-8", errors="replace")


def _pages() -> list[Path]:
    return sorted(ROOT.glob("*.html"))


def _root_vars(text: str) -> dict[str, str]:
    """Custom properties declared in the first :root block."""
    block = re.search(r":root\s*\{(.*?)\n\}", text, re.S)
    assert block, "no :root block"
    body = re.sub(r"/\*.*?\*/", "", block.group(1), flags=re.S)
    return {m.group(1): " ".join(m.group(2).split()) for m in re.finditer(r"(--[\w-]+)\s*:\s*([^;]+);", body)}


@pytest.mark.parametrize("path", SYSTEM_FILES, ids=lambda p: p.name)
def test_system_file_exists(path: Path) -> None:
    assert path.is_file(), f"{path.relative_to(ROOT)} is linked by pages but missing"


def test_shared_assets_referenced_by_many_pages_exist() -> None:
    """A stylesheet or script under /assets that five or more pages load must
    exist. Before the Neon Glass System, five such files were 404s on up to
    94 pages each and nothing noticed."""
    refs: Counter[str] = Counter()
    pattern = re.compile(r'(?:href|src)="/?(assets/(?:css|js)/[^"?#]+)')
    for page in _pages():
        for ref in set(pattern.findall(_read(page))):
            refs[ref] += 1
    # platform.js injects these on every page it runs on.
    for injected in ("assets/css/cinematic-motion.css", "assets/js/cinematic-motion.js"):
        assert injected in _read(ROOT / "platform.js")
        refs[injected] += 5
    missing = sorted(ref for ref, n in refs.items() if n >= 5 and not (ROOT / ref).is_file())
    assert not missing, f"shared assets linked by 5+ pages are missing: {missing}"


def test_mirrored_tokens_match_tokens_css() -> None:
    ours = _root_vars(_read(SYSTEM))
    source = _root_vars(_read(ROOT / "tokens.css"))
    mirrored = [
        "--cg-r-pill", "--cg-r-lg", "--cg-r-md", "--cg-r-sm", "--cg-r-xs",
        "--cg-sp-1", "--cg-sp-2", "--cg-sp-3", "--cg-sp-4", "--cg-sp-5", "--cg-sp-6",
        "--cg-serif", "--cg-sans", "--cg-mono",
        "--cg-dur-1", "--cg-dur-2", "--cg-dur-3",
    ]
    norm = lambda v: v.replace(" ", "")  # noqa: E731 - tokens.css writes some values unspaced
    drift = {k: (ours.get(k), source.get(k)) for k in mirrored if norm(ours.get(k, "")) != norm(source.get(k, ""))}
    assert not drift, f"tokens drifted from tokens.css (ours, tokens.css): {drift}"
    for k in ("--cg-ease", "--cg-spring"):
        assert norm(ours[k]) == norm(source[k]), k


def test_neon_triplets_match_ui_css() -> None:
    ours = _root_vars(_read(SYSTEM))
    ui = dict(re.findall(r"(--cg-neon-(?:cyan|blue|violet|magenta))\s*:\s*([^;]+);", _read(ROOT / "ui.css")))
    for name, value in ui.items():
        assert ours[name].replace(" ", "") == value.replace(" ", ""), name


def test_palette_has_one_primary_secondary_accent_and_distinct_status() -> None:
    ours = _root_vars(_read(SYSTEM))
    assert ours["--cg-neon-primary"] == "var(--cg-neon-cyan)"
    assert ours["--cg-neon-secondary"] == "var(--cg-neon-violet)"
    assert ours["--cg-neon-accent"] == "var(--cg-neon-magenta)"
    status = {ours[k] for k in ("--cg-success", "--cg-warning", "--cg-danger", "--cg-info")}
    assert len(status) == 4, "status colours must be distinct"
    assert ours["--cg-danger"] != ours["--cg-neon-magenta"], "danger must not reuse the accent"


def _luminance(hex_colour: str) -> float:
    channels = [int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


@pytest.mark.parametrize("token", ["--cg-text", "--cg-text-muted", "--cg-text-dim"])
def test_text_tokens_meet_wcag_aa_on_canvas(token: str) -> None:
    ours = _root_vars(_read(SYSTEM))
    fg, bg = _luminance(ours[token]), _luminance(ours["--cg-bg-0"])
    ratio = (max(fg, bg) + 0.05) / (min(fg, bg) + 0.05)
    assert ratio >= 4.5, f"{token} contrast {ratio:.2f}:1 on --cg-bg-0"


def test_backdrop_blur_is_capped() -> None:
    ours = _root_vars(_read(SYSTEM))
    for k in ("--cg-blur-sm", "--cg-blur-md", "--cg-blur-lg"):
        assert int(ours[k].rstrip("px")) <= BLUR_CEILING_PX, k
    for path in (p for p in SYSTEM_FILES if p.suffix == ".css"):
        for px in re.findall(r"blur\((\d+)px\)", _read(path)):
            assert int(px) <= BLUR_CEILING_PX, f"{path.name}: blur({px}px)"
    nav = _read(ROOT / "nav.js")
    for px in re.findall(r"backdrop-filter:blur\((\d+)px\)", nav):
        assert int(px) <= BLUR_CEILING_PX, f"nav.js sticky bar blur({px}px) repaints on every scroll frame"


@pytest.mark.parametrize("selector", [
    ".cg-glass", ".cg-glass-elevated", ".cg-neon-border", ".cg-neon-title", ".cg-neon-button",
    ".cg-status-live", ".cg-scanline", ".cg-grid-bg", ".cg-aurora", ".cg-reveal",
])
def test_component_class_is_defined(selector: str) -> None:
    css = "".join(_read(p) for p in SYSTEM_FILES if p.suffix == ".css")
    assert re.search(re.escape(selector) + r"(?![\w-])", css), f"{selector} is not defined"


def test_safety_rules_present() -> None:
    css = _read(SYSTEM)
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert "html.cg-low-power" in css and "html.cg-motion-reduced" in css
    assert "html[data-cg-hidden]" in css and "animation-play-state: paused" in css
    assert "img[data-cg-img-missing]" in css
    assert "@layer cg-defaults" in css, "global defaults must stay layered so page rules win"
    motion = _read(CSS / "cinematic-motion.css")
    assert "html.cg-reveal-ready" in motion, "reveal must only hide content once the runtime is ready"


def test_runtime_scripts_are_idempotent() -> None:
    for name, flag in (("cg-design-system.js", "__cgDesignSystem"),
                       ("future-buttons.js", "__cgFutureButtons"),
                       ("cinematic-motion.js", "__cgCinematicMotionRuntime")):
        assert f"if (window.{flag}) return;" in _read(JS / name), name


def test_mobile_fit_blocks_are_single_and_marked() -> None:
    for page in _pages():
        n = _read(page).count("<style data-cg-mobile-fit>")
        assert n <= 1, f"{page.name} has {n} mobile-fit blocks"
