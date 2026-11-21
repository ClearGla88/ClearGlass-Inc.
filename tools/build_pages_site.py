#!/usr/bin/env python3
"""Assemble the GitHub Pages site from the website files in this repository.

The website shares the repository root with source code, CI files, and office
documents. Publishing that root verbatim, which is what jekyll-build-pages does
when ``.nojekyll`` is present, put every one of those files on the public site.
This builds the site from an explicit rule instead. A tracked file is published
when it is:

* a web file (HTML, CSS, JS, JSON, XML, text, images, media, fonts), or
* a hosting file at the root (CNAME, .nojekyll, _headers, _redirects), or
* any other file that a published page links to with ``href``/``src``, such as
  the Markdown documents some pages link to.

Nothing under ``.github/``, ``src/``, ``tests/`` or ``tools/`` is published,
and nothing under a top-level directory that is a separately built project:
one holding a ``package.json``, ``pyproject.toml``, ``Cargo.toml`` or
``go.mod`` at any depth (the Next.js apps and Python packages). The root's own
manifests do not count. A new app project is therefore kept off the site
without anyone having to list it here. Only tracked files are considered
(``git ls-files``).

A page that links to a file of a type that is never published (an office
document, source code, CI config) or to a file under a non-site directory fails
the build. An owner then decides whether that file belongs on the site; the
build does not drop the file silently and leave the link broken.

Usage::

    python3 tools/build_pages_site.py --out _site

Exit status: 0 built, 1 refused (a page links to a never-published file),
2 cannot run (bad output directory, git or file error). On any failure the
output directory is left absent or untouched.

stdlib only, so it runs on a bare CI runner.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

WEB_SUFFIXES = frozenset({
    ".html", ".htm", ".css", ".js", ".mjs", ".json", ".xml", ".txt", ".webmanifest",
    ".ico", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".avif",
    ".mp4", ".webm", ".woff", ".woff2", ".ttf", ".otf",
})
ROOT_HOSTING_FILES = frozenset({"CNAME", ".nojekyll", "_headers", "_redirects"})
NON_SITE_DIRS = frozenset({".git", ".github", "src", "tests", "tools"})
# A top-level directory holding one of these is a separately built project.
PROJECT_MANIFESTS = frozenset({"package.json", "pyproject.toml", "Cargo.toml", "go.mod"})
# Never published, even when a page links to one: the build refuses instead.
NEVER_PUBLISHED_SUFFIXES = frozenset({
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods", ".odp", ".rtf",
    ".eml", ".mbox", ".msg",
    ".py", ".pyc", ".rs", ".toml", ".lock", ".ps1", ".sh", ".bat", ".mdc",
    ".yml", ".yaml", ".env", ".example", ".pem", ".key", ".p12", ".pfx",
})

_LINK = re.compile(r"""\b(?:href|src)\s*=\s*["']([^"']+)["']""", re.IGNORECASE)


class BuildRefused(Exception):
    """A published page links to a file the site must not publish."""


def tracked_files(root: Path) -> list[str]:
    result = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], check=True, capture_output=True)
    return [item for item in result.stdout.decode("utf-8", "surrogateescape").split("\0") if item]


def non_site_dirs(files: list[str]) -> frozenset[str]:
    """The fixed non-site directories plus every top-level project directory."""
    projects = set()
    for path in files:
        parts = PurePosixPath(path).parts
        if len(parts) > 1 and parts[-1] in PROJECT_MANIFESTS:
            projects.add(parts[0])
    return NON_SITE_DIRS | projects


def _in_non_site_dir(path: str, excluded: frozenset[str]) -> bool:
    return PurePosixPath(path).parts[0] in excluded


def _is_web_file(path: str, excluded: frozenset[str]) -> bool:
    posix = PurePosixPath(path)
    if _in_non_site_dir(path, excluded):
        return False
    return posix.suffix.lower() in WEB_SUFFIXES or (len(posix.parts) == 1 and posix.name in ROOT_HOSTING_FILES)


def _resolve(page: str, value: str) -> str | None:
    """Map an href/src value on ``page`` to a repository path, or None if not local."""
    parts = urlsplit(value.strip())
    if parts.scheme or parts.netloc or not parts.path:
        return None
    path = unquote(parts.path)
    # Root-absolute links resolve against the repository root, which is the site root.
    joined = PurePosixPath(path.lstrip("/")) if path.startswith("/") else PurePosixPath(page).parent / path
    stack: list[str] = []
    for segment in joined.parts:
        if segment == "..":
            if stack:
                stack.pop()
        elif segment not in (".", ""):
            stack.append(segment)
    return "/".join(stack) or None


def linked_files(root: Path, page: str, tracked: set[str]) -> set[str]:
    text = (root / page).read_text(encoding="utf-8", errors="replace")
    targets = (_resolve(page, value) for value in _LINK.findall(text))
    return {target for target in targets if target in tracked}


def select(root: Path, files: list[str]) -> list[str]:
    """Return the tracked files to publish; raise BuildRefused on a forbidden link."""
    tracked = set(files)
    excluded = non_site_dirs(files)
    chosen = {path for path in files if _is_web_file(path, excluded)}
    refused: list[str] = []
    for page in sorted(chosen):
        if not page.lower().endswith((".html", ".htm")):
            continue
        for target in sorted(linked_files(root, page, tracked) - chosen):
            if _in_non_site_dir(target, excluded) or PurePosixPath(target).suffix.lower() in NEVER_PUBLISHED_SUFFIXES:
                refused.append(f"{page} -> {target}")
            else:
                chosen.add(target)
    if refused:
        raise BuildRefused(refused)
    return sorted(chosen)


def build(root: Path, out: Path) -> list[str]:
    """Write the site to ``out`` (which must not exist or be empty) and return the paths."""
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise FileExistsError(f"output must be absent or an empty directory: {out}")
    selected = select(root, tracked_files(root))
    out.parent.mkdir(parents=True, exist_ok=True)
    # Stage next to the destination and rename, so a failure never leaves a partial site.
    with tempfile.TemporaryDirectory(dir=out.parent, prefix=".pages-staging-") as tmp:
        staging = Path(tmp) / "site"
        for path in selected:
            source = root / path
            if source.is_symlink() or not source.is_file():
                raise OSError(f"tracked file is missing or not a regular file: {path}")
            destination = staging / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        if out.exists():
            out.rmdir()
        staging.rename(out)
    return selected


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--out", type=Path, required=True, help="output directory (absent or empty)")
    args = parser.parse_args(argv)
    root, out = args.root.resolve(), args.out.resolve()

    try:
        published = build(root, out)
    except BuildRefused as exc:
        for link in exc.args[0]:
            print(f"REFUSED  {link}  (this file type or directory is never published)", file=sys.stderr)
        print("pages-site: build refused; remove the link or decide to publish the file", file=sys.stderr)
        return 1
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"pages-site: cannot build: {exc}", file=sys.stderr)
        return 2

    pages = sum(1 for path in published if path.lower().endswith((".html", ".htm")))
    print(f"pages-site: published {len(published)} files ({pages} pages) to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
