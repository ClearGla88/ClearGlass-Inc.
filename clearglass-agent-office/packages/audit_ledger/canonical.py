"""Canonical encoding, hashing, and secret redaction shared by every package.

Canonical JSON (sorted keys, no whitespace, UTF-8) is the only byte form that
is ever hashed. Two implementations that agree on this function agree on every
hash in the ledger and every approval digest.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

GENESIS_HASH = "0" * 64


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def digest(value: Any) -> str:
    """SHA-256 of the canonical JSON form of ``value``."""
    return sha256_hex(canonical_json(value))


# Credential-shaped strings. Same families as tools/repo_hygiene.py at the
# repository root. Matches are redacted from audit payloads and rejected from
# memory writes; the matched value is never logged.
_B = r"(?<![A-Za-z0-9+/=_-])"
SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("aws-access-key", re.compile(_B + r"AKIA[0-9A-Z]{16}(?![0-9A-Z])")),
    ("github-token", re.compile(_B + r"(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})")),
    ("stripe-secret-key", re.compile(_B + r"(?:sk|rk)_live_[A-Za-z0-9]{16,}")),
    ("slack-token", re.compile(_B + r"xox[abprs]-[A-Za-z0-9-]{10,}")),
    ("google-api-key", re.compile(_B + r"AIza[0-9A-Za-z_-]{35}(?![0-9A-Za-z_-])")),
    ("anthropic-key", re.compile(_B + r"sk-ant-[A-Za-z0-9_-]{20,}")),
    ("openai-key", re.compile(_B + r"sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}T3BlbkFJ[A-Za-z0-9_-]{20,}")),
    ("private-key-block", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----")),
    ("bearer-token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{24,}=*")),
)


def find_secrets(text: str) -> list[str]:
    """Return the rule ids that match ``text`` (never the matched values)."""
    return [rule for rule, pattern in SECRET_PATTERNS if pattern.search(text)]


def redact(value: Any) -> tuple[Any, list[str]]:
    """Recursively replace credential-shaped substrings. Returns (value, rules hit)."""
    hits: list[str] = []

    def _walk(node: Any) -> Any:
        if isinstance(node, str):
            out = node
            for rule, pattern in SECRET_PATTERNS:
                if pattern.search(out):
                    hits.append(rule)
                    out = pattern.sub(f"[REDACTED:{rule}]", out)
            return out
        if isinstance(node, dict):
            return {k: _walk(v) for k, v in node.items()}
        if isinstance(node, (list, tuple)):
            return [_walk(v) for v in node]
        return node

    return _walk(value), sorted(set(hits))
