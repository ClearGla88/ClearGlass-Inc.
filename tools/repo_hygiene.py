#!/usr/bin/env python3
"""Fail CI when files that must never be public are tracked in this repository.

This repository is public and is mostly populated through GitHub web uploads.
``.gitignore`` only shapes ``git add`` in a local working tree; it never untracks
a committed file and does not stop files committed through other paths. This
check inspects what is actually tracked (``git ls-files``) and fails on:

* path rules  - raw email exports, Python bytecode, dependency/build output,
                environment files, private-key material, Terraform state;
* content rules - credential-shaped strings (cloud/API tokens, private keys).

Findings name the file, line, and rule only. Matched values are never printed.

Pre-existing findings that need an owner decision are listed, with a reason, in
``tools/repo_hygiene_baseline.json``. A baseline entry that no longer matches a
tracked finding is itself an error, so the baseline can only shrink.

Usage::

    python3 tools/repo_hygiene.py            # exit 1 on any non-baselined finding
    python3 tools/repo_hygiene.py --all      # also list baselined findings

stdlib only, so it runs on a bare CI runner.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

DEFAULT_BASELINE = Path(__file__).with_name("repo_hygiene_baseline.json")
MAX_SCAN_BYTES = 8 * 1024 * 1024
BINARY_SNIFF_BYTES = 8192

# (rule id, description, predicate on the POSIX path)
PATH_RULES: tuple[tuple[str, str, object], ...] = (
    ("raw-email", "raw email export (personal addresses, routing headers)",
     lambda p: p.suffix.lower() in {".eml", ".mbox", ".msg"}),
    ("python-bytecode", "Python bytecode cache",
     lambda p: "__pycache__" in p.parts or p.suffix.lower() in {".pyc", ".pyo"}),
    ("build-output", "dependency or build output directory",
     lambda p: bool({"node_modules", "target", ".next", "dist"} & set(p.parts[:-1]))),
    ("env-file", "environment file (use a *.example template instead)",
     lambda p: (p.name == ".env" or p.name.startswith(".env.")) and not p.name.endswith(".example")),
    ("key-material", "private key or certificate bundle",
     lambda p: p.suffix.lower() in {".pem", ".key", ".p12", ".pfx", ".jks", ".keystore"}),
    ("terraform-state", "Terraform state (contains infrastructure secrets)",
     lambda p: p.name.endswith((".tfstate", ".tfstate.backup"))),
)

# Lookbehinds stop matches that start mid-way through a longer token, such as a
# base64 media blob embedded in an HTML page.
_B = r"(?<![A-Za-z0-9+/=_-])"
CONTENT_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("aws-access-key", re.compile(_B + r"AKIA[0-9A-Z]{16}(?![0-9A-Z])")),
    ("github-token", re.compile(_B + r"(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})")),
    ("stripe-secret-key", re.compile(_B + r"(?:sk|rk)_live_[A-Za-z0-9]{16,}")),
    ("slack-token", re.compile(_B + r"xox[abprs]-[A-Za-z0-9-]{10,}")),
    ("slack-webhook", re.compile(r"https://hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[A-Za-z0-9]+")),
    ("discord-webhook", re.compile(r"https://(?:ptb\.|canary\.)?discord(?:app)?\.com/api/webhooks/\d+/[\w-]{20,}")),
    ("google-api-key", re.compile(_B + r"AIza[0-9A-Za-z_-]{35}(?![0-9A-Za-z_-])")),
    ("anthropic-key", re.compile(_B + r"sk-ant-[A-Za-z0-9_-]{20,}")),
    ("openai-key", re.compile(_B + r"sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}T3BlbkFJ[A-Za-z0-9_-]{20,}")),
    ("private-key-block", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----")),
)


@dataclass(frozen=True, order=True)
class Finding:
    path: str
    rule: str
    line: int = 0
    detail: str = ""

    def render(self) -> str:
        where = f"{self.path}:{self.line}" if self.line else self.path
        return f"{where}: [{self.rule}] {self.detail}"


def tracked_files(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        check=True, capture_output=True,
    )
    return [item for item in result.stdout.decode("utf-8", "surrogateescape").split("\0") if item]


def path_findings(path: str) -> list[Finding]:
    posix = PurePosixPath(path)
    return [Finding(path, rule, 0, desc) for rule, desc, matches in PATH_RULES if matches(posix)]


def content_findings(root: Path, path: str) -> list[Finding]:
    file_path = root / path
    try:
        if not file_path.is_file() or file_path.stat().st_size > MAX_SCAN_BYTES:
            return []
        data = file_path.read_bytes()
    except OSError:
        return []
    if b"\0" in data[:BINARY_SNIFF_BYTES]:
        return []
    text = data.decode("utf-8", "replace")
    findings: list[Finding] = []
    for rule, pattern in CONTENT_RULES:
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            findings.append(Finding(path, rule, line, "credential-shaped value (redacted)"))
    return findings


def scan(root: Path, files: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    for path in files:
        findings.extend(path_findings(path))
        findings.extend(content_findings(root, path))
    return sorted(findings)


def load_baseline(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data.get("exceptions", []) if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise ValueError(f"{path}: 'exceptions' must be a list")
    for entry in entries:
        if not isinstance(entry, dict) or not all(
            isinstance(entry.get(key), str) and entry[key].strip() for key in ("path", "rule", "reason")
        ):
            raise ValueError(f"{path}: every exception needs non-empty 'path', 'rule', and 'reason'")
    return entries


def evaluate(findings: list[Finding], baseline: list[dict[str, str]]) -> tuple[list[Finding], list[Finding], list[str]]:
    """Split findings into (new, baselined) and report stale baseline entries."""
    allowed = {(entry["path"], entry["rule"]) for entry in baseline}
    new = [item for item in findings if (item.path, item.rule) not in allowed]
    accepted = [item for item in findings if (item.path, item.rule) in allowed]
    present = {(item.path, item.rule) for item in findings}
    stale = sorted(f"{path} [{rule}]" for path, rule in allowed - present)
    return new, accepted, stale


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--all", action="store_true", help="also list baselined findings")
    args = parser.parse_args(argv)

    try:
        files = tracked_files(args.root)
        baseline = load_baseline(args.baseline)
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        print(f"repo-hygiene: cannot run: {exc}", file=sys.stderr)
        return 2

    new, accepted, stale = evaluate(scan(args.root, files), baseline)

    for item in new:
        print(f"FAIL  {item.render()}")
    for entry in stale:
        print(f"FAIL  stale baseline entry (no longer tracked or no longer matching): {entry}")
    if args.all:
        for item in accepted:
            print(f"KNOWN {item.render()}")
    print(
        f"repo-hygiene: {len(files)} tracked files, {len(new)} new finding(s), "
        f"{len(accepted)} baselined, {len(stale)} stale baseline entr{'y' if len(stale) == 1 else 'ies'}"
    )
    return 1 if new or stale else 0


if __name__ == "__main__":
    raise SystemExit(main())
