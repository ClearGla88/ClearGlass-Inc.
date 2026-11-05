"""Tests for tools/repo_hygiene.py.

Credential-shaped strings are assembled at runtime so this file never contains
one literally (and so push-protection scanners have nothing to flag).
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools import repo_hygiene

ROOT = Path(__file__).resolve().parents[1]


def _fake_github_token() -> str:
    return "ghp" + "_" + "A1b2C3d4" * 5


def _fake_google_key() -> str:
    return "AI" + "za" + "Sy" + "x" * 33


class _GitRepo:
    def __init__(self, files: dict[str, bytes | str]):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        for name, content in files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            data = content.encode("utf-8") if isinstance(content, str) else content
            path.write_bytes(data)
        subprocess.run(["git", "-C", str(self.root), "add", "-A"], check=True)

    def baseline(self, entries: list[dict[str, str]]) -> Path:
        path = self.root / "baseline.json"
        path.write_text(json.dumps({"exceptions": entries}), encoding="utf-8")
        return path

    def run(self, baseline: Path | None = None) -> int:
        args = ["--root", str(self.root), "--baseline", str(baseline or self.root / "absent.json")]
        return repo_hygiene.main(args)

    def close(self) -> None:
        self._tmp.cleanup()


class RepoHygieneTests(unittest.TestCase):
    def make_repo(self, files: dict[str, bytes | str]) -> _GitRepo:
        repo = _GitRepo(files)
        self.addCleanup(repo.close)
        return repo

    def test_clean_tree_passes(self):
        repo = self.make_repo({"index.html": "<p>ok</p>", ".env.example": "API_KEY=\n", "tool.py": "x = 1\n"})
        self.assertEqual(repo.run(), 0)

    def test_path_rules_flag_forbidden_files(self):
        cases = {
            "notice.eml": "raw-email",
            "__pycache__/mod.cpython-312.pyc": "python-bytecode",
            "node_modules/pkg/index.js": "build-output",
            "target/debug/app": "build-output",
            ".env": "env-file",
            ".env.production": "env-file",
            "deploy.pem": "key-material",
            "infra/terraform.tfstate": "terraform-state",
        }
        for name, rule in cases.items():
            with self.subTest(name=name):
                self.assertEqual([f.rule for f in repo_hygiene.path_findings(name)], [rule])
        self.assertEqual(repo_hygiene.path_findings(".env.growth.example"), [])
        self.assertEqual(repo_hygiene.path_findings("src/main.rs"), [])

    def test_credential_is_reported_without_its_value(self):
        token = _fake_github_token()
        repo = self.make_repo({"config.js": f"const t = '{token}';\n"})
        findings = repo_hygiene.scan(repo.root, ["config.js"])
        self.assertEqual([(f.rule, f.line) for f in findings], [("github-token", 1)])
        self.assertNotIn(token, findings[0].render())
        self.assertEqual(repo.run(), 1)

    def test_key_embedded_in_base64_blob_is_not_flagged(self):
        blob = "data:video/mp4;base64," + "Q" * 40 + _fake_google_key() + "Q" * 40
        repo = self.make_repo({"film.html": f'<video src="{blob}"></video>\n'})
        self.assertEqual(repo_hygiene.scan(repo.root, ["film.html"]), [])

    def test_standalone_google_key_is_flagged(self):
        repo = self.make_repo({"maps.js": f'const key = "{_fake_google_key()}";\n'})
        self.assertEqual([f.rule for f in repo_hygiene.scan(repo.root, ["maps.js"])], ["google-api-key"])

    def test_binary_files_are_not_content_scanned(self):
        repo = self.make_repo({"clip.bin": b"\0\0" + _fake_github_token().encode()})
        self.assertEqual(repo_hygiene.content_findings(repo.root, "clip.bin"), [])

    def test_baseline_suppresses_listed_finding_only(self):
        repo = self.make_repo({"old.eml": "From: a\n", "new.eml": "From: b\n"})
        baseline = repo.baseline([{"path": "old.eml", "rule": "raw-email", "reason": "pending owner decision"}])
        self.assertEqual(repo.run(baseline), 1)
        (repo.root / "new.eml").unlink()
        subprocess.run(["git", "-C", str(repo.root), "rm", "-q", "--cached", "new.eml"], check=True)
        self.assertEqual(repo.run(baseline), 0)

    def test_stale_baseline_entry_fails(self):
        repo = self.make_repo({"index.html": "<p>ok</p>"})
        baseline = repo.baseline([{"path": "gone.eml", "rule": "raw-email", "reason": "already removed"}])
        self.assertEqual(repo.run(baseline), 1)

    def test_baseline_entries_require_a_reason(self):
        repo = self.make_repo({"old.eml": "From: a\n"})
        baseline = repo.baseline([{"path": "old.eml", "rule": "raw-email", "reason": " "}])
        self.assertEqual(repo.run(baseline), 2)

    def test_repository_passes_with_committed_baseline(self):
        """Gate: the real tree has no findings beyond the reviewed baseline."""
        self.assertEqual(repo_hygiene.main(["--root", str(ROOT)]), 0)


if __name__ == "__main__":
    unittest.main()
