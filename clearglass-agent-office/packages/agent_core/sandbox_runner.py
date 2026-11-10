"""Run allow-listed test suites for ``tests.run_sandbox``.

Safety properties:

- Agents name a suite id; the command comes only from ``config/sandbox.json``.
- Every suite's argv must start with ``{python}`` (this interpreter). No shell.
- The child gets a scrubbed environment: PATH, locale, and PYTHONPATH only. No
  OFFICE_* settings, secrets, API keys, or tokens reach it.
- A timeout kills runaway suites; output is truncated before it is stored.

Not a network sandbox: a suite can open sockets. Containerized isolation is a
roadmap item (docs/ROADMAP.md). The passing run's task id is the evidence that
``deploy.production`` requires (see the policy engine, step 4).
"""

from __future__ import annotations

import json
import os
import subprocess  # noqa: S404 - fixed, reviewed argv only; see module docstring
import sys
import time
from pathlib import Path
from typing import Any

KEEP_ENV = ("PATH", "LANG", "LC_ALL", "SYSTEMROOT", "TMPDIR", "TEMP", "TMP")
MAX_OUTPUT_CHARS = 4000
MAX_TIMEOUT_S = 1800


class SandboxError(ValueError):
    pass


def validate_suites(suites: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for suite_id, spec in suites.items():
        argv = spec.get("argv")
        if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
            raise SandboxError(f"suite {suite_id}: argv must be a non-empty list of strings")
        if argv[0] != "{python}":
            raise SandboxError(f"suite {suite_id}: argv must start with {{python}}")
        timeout = spec.get("timeout_s", 300)
        if not isinstance(timeout, int) or not 1 <= timeout <= MAX_TIMEOUT_S:
            raise SandboxError(f"suite {suite_id}: timeout_s must be 1-{MAX_TIMEOUT_S}")
        out[suite_id] = {"argv": list(argv), "timeout_s": timeout, "description": str(spec.get("description", ""))}
    return out


class SandboxRunner:
    def __init__(self, base_dir: Path, suites: dict[str, Any] | None = None) -> None:
        self.base_dir = Path(base_dir)
        self.suites = validate_suites(suites or {})

    @classmethod
    def from_config(cls, path: Path, base_dir: Path) -> SandboxRunner:
        if not path.exists():
            return cls(base_dir, {})
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(base_dir, raw.get("suites", {}))

    def _env(self) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if k in KEEP_ENV}
        env["PYTHONPATH"] = os.pathsep.join([str(self.base_dir / "packages"), str(self.base_dir)])
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        return env

    def run(self, suite_id: str) -> dict[str, Any]:
        spec = self.suites.get(suite_id)
        if spec is None:
            raise SandboxError(f"unknown sandbox suite {suite_id!r}; allowed: {sorted(self.suites)}")
        argv = [sys.executable if a == "{python}" else a for a in spec["argv"]]
        started = time.monotonic()
        try:
            proc = subprocess.run(  # noqa: S603 - argv comes from reviewed config, never from agent input
                argv,
                cwd=self.base_dir,
                env=self._env(),
                capture_output=True,
                text=True,
                timeout=spec["timeout_s"],
                check=False,
            )
            returncode, output = proc.returncode, (proc.stdout or "") + (proc.stderr or "")
        except subprocess.TimeoutExpired:
            returncode, output = -1, f"timed out after {spec['timeout_s']}s"
        return {
            "suite": suite_id,
            "passed": returncode == 0,
            "returncode": returncode,
            "duration_s": round(time.monotonic() - started, 2),
            "output_tail": output[-MAX_OUTPUT_CHARS:],
            "environment": "sandbox-subprocess",
        }
