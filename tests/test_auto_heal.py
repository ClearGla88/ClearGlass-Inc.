"""Regression tests for auto_heal.py's fail-closed preflight.

auto_heal.py locates its state files relative to its own path. When that state
directory is missing (as in the flattened upload, where ROOT resolves outside
the repository), the controller used to call the GitHub API — creating labels,
re-running jobs, opening issues — and only then crash while saving history.
Without saved history the next run repeats those side effects.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import auto_heal


def _patch_control(directory: Path):
    return mock.patch.multiple(
        auto_heal,
        CONTROL=directory,
        PATTERNS_PATH=directory / "error-patterns.json",
        STRATEGIES_PATH=directory / "healing-strategies.json",
        HISTORY_PATH=directory / "run-history.json",
        FLAKY_PATH=directory / "flaky-tests.json",
    )


FAILED_RUN = {
    "id": 101,
    "run_attempt": 1,
    "name": "CI",
    "conclusion": "failure",
    "head_sha": "0" * 40,
    "head_branch": "main",
    "html_url": "https://github.com/example/repo/actions/runs/101",
}


class AutoHealPreflightTests(unittest.TestCase):
    def test_missing_state_directory_fails_before_any_api_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "does-not-exist"
            with _patch_control(missing), \
                 mock.patch.object(auto_heal, "api") as api, \
                 mock.patch.object(auto_heal, "try_api") as try_api:
                exit_code = auto_heal.main()
            self.assertEqual(exit_code, 2)
            api.assert_not_called()
            try_api.assert_not_called()
            self.assertFalse(missing.exists(), "preflight must not create state outside the repo")

    def test_state_directory_present_records_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = Path(tmp)

            def fake_try_api(method, path, payload=None):
                if path.endswith("/actions/runs?status=completed&per_page=50"):
                    return {"workflow_runs": [FAILED_RUN]}
                if path.endswith("/jobs?per_page=100"):
                    return {"jobs": []}
                if method == "GET" and "/issues?" in path:
                    return []
                if method == "POST" and path.endswith("/issues"):
                    return {"number": 7}
                return None

            with _patch_control(control), \
                 mock.patch.object(auto_heal, "api"), \
                 mock.patch.object(auto_heal, "try_api", side_effect=fake_try_api):
                exit_code = auto_heal.main()

            self.assertEqual(exit_code, 0)
            history = (control / "run-history.json").read_text(encoding="utf-8")
            self.assertIn('"run_id": 101', history)
            self.assertIn('"issue_number": 7', history)


if __name__ == "__main__":
    unittest.main()
