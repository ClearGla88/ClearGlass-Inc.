"""Tests for tools/build_pages_site.py and the Pages workflow that runs it.

The website shares the repository root with source code, CI files and office
documents. The Pages workflow used to publish that root verbatim, so all of it
was downloadable from the public site. These tests pin the publish rule and
check, against the real tree, that every file a page links to still ships.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
import unittest
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

from tools import build_pages_site

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "jekyll-gh-pages.yml"

# File types that are not website content in this tree. None may be published.
NOT_SITE_SUFFIXES = {
    ".docx", ".py", ".rs", ".toml", ".lock", ".ps1", ".sh", ".yml", ".yaml", ".mdc", ".example",
    ".ts", ".tsx", ".sql", ".cedar",
}
NOT_SITE_DIRS = {".github", "src", "tests", "tools"}
APP_MANIFESTS = {"package.json", "pyproject.toml", "Cargo.toml", "go.mod"}


def _app_project_dirs(files: set[str]) -> set[str]:
    """Top-level directories that hold a build manifest: separately built apps, not the site."""
    return {
        PurePosixPath(path).parts[0] for path in files
        if len(PurePosixPath(path).parts) > 1 and PurePosixPath(path).name in APP_MANIFESTS
    }

# Broader than the builder's own href/src scan: also CSS url() and media posters.
_REFERENCE = re.compile(
    r"""(?:src|href|poster|data-src)\s*=\s*["']([^"']+)["']|url\(\s*["']?([^"')]+)["']?\s*\)""",
    re.IGNORECASE,
)


class _GitRepo:
    def __init__(self, tracked: dict[str, str], untracked: dict[str, str] | None = None):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "repo"
        self.out = Path(self._tmp.name) / "site"
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        for name, content in tracked.items():
            self._write(name, content)
        subprocess.run(["git", "-C", str(self.root), "add", "-A"], check=True)
        for name, content in (untracked or {}).items():
            self._write(name, content)

    def _write(self, name: str, content: str) -> None:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def build(self) -> int:
        return build_pages_site.main(["--root", str(self.root), "--out", str(self.out)])

    def published(self) -> set[str]:
        if not self.out.exists():
            return set()
        return {p.relative_to(self.out).as_posix() for p in self.out.rglob("*") if p.is_file()}

    def cleanup(self) -> None:
        self._tmp.cleanup()


def _tracked(root: Path) -> list[str]:
    out = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], check=True, capture_output=True)
    return [f for f in out.stdout.decode("utf-8", "surrogateescape").split("\0") if f]


def _resolve(page: str, value: str) -> str | None:
    parts = urlsplit(value.strip())
    if parts.scheme or parts.netloc or not parts.path:
        return None
    path = unquote(parts.path)
    joined = PurePosixPath(path.lstrip("/")) if path.startswith("/") else PurePosixPath(page).parent / path
    stack: list[str] = []
    for seg in joined.parts:
        if seg == "..":
            if stack:
                stack.pop()
        elif seg not in (".", ""):
            stack.append(seg)
    return "/".join(stack) or None


class WorkflowTests(unittest.TestCase):
    def test_pages_workflow_publishes_the_built_site_not_the_repository_root(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("tools/build_pages_site.py", text)
        self.assertNotRegex(
            text, r"(?m)^\s*(?:-\s*)?uses:\s*actions/jekyll-build-pages",
            "jekyll-build-pages copies the whole root verbatim under .nojekyll",
        )
        self.assertNotRegex(text, r"(?m)^\s*source:\s*\./?\s*$")


class RealTreeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls._tmp.name) / "site"
        cls.exit_code = build_pages_site.main(["--root", str(ROOT), "--out", str(cls.out)])
        cls.published = {p.relative_to(cls.out).as_posix() for p in cls.out.rglob("*") if p.is_file()}
        cls.tracked = set(_tracked(ROOT))
        cls.excluded_dirs = NOT_SITE_DIRS | _app_project_dirs(cls.tracked)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_build_succeeds(self):
        self.assertEqual(self.exit_code, 0)

    def test_no_source_ci_office_or_app_project_files_are_published(self):
        leaked = sorted(
            path for path in self.published
            if PurePosixPath(path).suffix.lower() in NOT_SITE_SUFFIXES
            or PurePosixPath(path).parts[0] in self.excluded_dirs
        )
        self.assertEqual(leaked, [])

    def test_every_tracked_page_is_published(self):
        pages = {
            path for path in self.tracked
            if path.lower().endswith((".html", ".htm")) and PurePosixPath(path).parts[0] not in self.excluded_dirs
        }
        self.assertTrue(pages)
        self.assertEqual(sorted(pages - self.published), [])

    def test_hosting_files_are_published(self):
        for name in ("CNAME", ".nojekyll", "index.html", "404.html", "sw.js", "sitemap.xml", "robots.txt"):
            with self.subTest(name=name):
                self.assertIn(name, self.published)

    def test_every_tracked_file_a_published_page_or_stylesheet_links_to_is_published(self):
        withheld_but_linked = set()
        for page in self.published:
            if not page.lower().endswith((".html", ".htm", ".css")):
                continue
            text = (self.out / page).read_text(encoding="utf-8", errors="replace")
            for match in _REFERENCE.finditer(text):
                target = _resolve(page, next(group for group in match.groups() if group))
                if target in self.tracked and target not in self.published:
                    withheld_but_linked.add(f"{page} -> {target}")
        self.assertEqual(sorted(withheld_but_linked), [])

    def test_published_bytes_match_the_tracked_files(self):
        for name in ("index.html", "sw.js", "CNAME"):
            with self.subTest(name=name):
                self.assertEqual((self.out / name).read_bytes(), (ROOT / name).read_bytes())


class PublishRuleTests(unittest.TestCase):
    def setUp(self):
        self.repos: list[_GitRepo] = []

    def tearDown(self):
        for repo in self.repos:
            repo.cleanup()

    def _repo(self, tracked, untracked=None) -> _GitRepo:
        repo = _GitRepo(tracked, untracked)
        self.repos.append(repo)
        return repo

    def test_publishes_web_files_and_linked_documents_only(self):
        repo = self._repo({
            "index.html": '<a href="guide.md">Guide</a><a href="/docs/spec.md">Spec</a>',
            "site.css": "body{}",
            "guide.md": "# linked",
            "docs/spec.md": "# linked by root-absolute path",
            "notes.md": "# not linked",
            "plan.docx": "office document",
            "agent.py": "print()",
            "deploy.yml": "on: push",
            "CNAME": "example.com",
            ".nojekyll": "",
            "tests/fixture.html": "<p>test page</p>",
            "tools/report.json": "{}",
        })
        self.assertEqual(repo.build(), 0)
        self.assertEqual(
            repo.published(),
            {"index.html", "site.css", "guide.md", "docs/spec.md", "CNAME", ".nojekyll"},
        )

    def test_link_to_a_never_published_type_fails_closed(self):
        repo = self._repo({
            "index.html": '<a href="Business%20Plan.docx">plan</a>',
            "Business Plan.docx": "office document",
        })
        self.assertEqual(repo.build(), 1)
        self.assertEqual(repo.published(), set(), "a refused build must not leave a partial site")

    def test_link_into_a_non_site_directory_fails_closed(self):
        repo = self._repo({
            "index.html": '<a href="src/main.rs">source</a>',
            "src/main.rs": "fn main() {}",
        })
        self.assertEqual(repo.build(), 1)
        self.assertEqual(repo.published(), set())

    def test_untracked_files_are_never_published(self):
        repo = self._repo({"index.html": "<p>home</p>"}, untracked={"draft.html": "<p>wip</p>"})
        self.assertEqual(repo.build(), 0)
        self.assertEqual(repo.published(), {"index.html"})

    def test_external_and_fragment_links_are_ignored(self):
        repo = self._repo({
            "index.html": (
                '<a href="https://example.com/x.docx">ext</a><a href="#top">top</a>'
                '<a href="mailto:a@example.com">mail</a><a href="?q=1">query</a>'
            ),
        })
        self.assertEqual(repo.build(), 0)
        self.assertEqual(repo.published(), {"index.html"})

    def test_app_project_directories_are_not_published(self):
        repo = self._repo({
            "index.html": '<script src="widget/app.js"></script>',
            "package.json": "{}",  # the root's own manifest must not hide the site
            "widget/app.js": "// site section without a manifest",
            "console/apps/web/package.json": "{}",
            "console/apps/web/next.config.js": "module.exports = {}",
            "console/apps/web/public/logo.svg": "<svg/>",
            "console/README.md": "# app",
            "agentpkg/pyproject.toml": "[project]",
            "agentpkg/static/index.html": "<p>app ui</p>",
            "agentpkg/schema.json": "{}",
        })
        self.assertEqual(repo.build(), 0)
        self.assertEqual(repo.published(), {"index.html", "package.json", "widget/app.js"})

    def test_link_into_an_app_project_fails_closed(self):
        repo = self._repo({
            "index.html": '<a href="agentpkg/static/index.html">console</a>',
            "agentpkg/pyproject.toml": "[project]",
            "agentpkg/static/index.html": "<p>app ui</p>",
        })
        self.assertEqual(repo.build(), 1)
        self.assertEqual(repo.published(), set())

    def test_refuses_a_non_empty_output_directory(self):
        repo = self._repo({"index.html": "<p>home</p>"})
        repo.out.mkdir()
        (repo.out / "stale.docx").write_text("left over", encoding="utf-8")
        self.assertEqual(repo.build(), 2)
        self.assertEqual(repo.published(), {"stale.docx"}, "existing output must be left untouched")


if __name__ == "__main__":
    unittest.main()
