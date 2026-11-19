"""Synthetic honeytokens.

A honeytoken here is a random string in a fixed format ("cgdt_" + 32 base62
characters). It is registered with no service, so it grants no access anywhere.
Only its SHA-256 fingerprint is stored; the token is printed once when minted.
Detection is local: a sensor that sees a token-shaped string sends its
fingerprint, and the server matches it against the registry. Nothing calls out
to third-party tracking infrastructure.
"""

from __future__ import annotations

import re
import secrets
import sqlite3
import string
from datetime import datetime

from .util import iso, new_id, sha256_hex

PREFIX = "cgdt_"
HONEYTOKEN_RE = re.compile(r"cgdt_[A-Za-z0-9]{32}")
_ALPHABET = string.ascii_letters + string.digits
MAX_FINGERPRINTS = 8


def mint() -> str:
    return PREFIX + "".join(secrets.choice(_ALPHABET) for _ in range(32))


def fingerprint(token: str) -> str:
    return sha256_hex(token)


def fingerprints_in(text: str) -> list[str]:
    seen: list[str] = []
    for match in HONEYTOKEN_RE.findall(text):
        fp = fingerprint(match)
        if fp not in seen:
            seen.append(fp)
        if len(seen) >= MAX_FINGERPRINTS:
            break
    return seen


def register(c: sqlite3.Connection, token: str, *, label: str, placement: str, at: datetime) -> str:
    if not HONEYTOKEN_RE.fullmatch(token):
        raise ValueError("not a honeytoken")
    token_id = new_id("ht")
    c.execute(
        "INSERT INTO honeytokens (fingerprint, token_id, label, placement, created_at) VALUES (?,?,?,?,?)",
        (fingerprint(token), token_id, label[:200], placement[:300], iso(at)),
    )
    return token_id


def match(c: sqlite3.Connection, fingerprints: list[str]) -> list[str]:
    ids = []
    for fp in fingerprints[:MAX_FINGERPRINTS]:
        if not re.fullmatch(r"[0-9a-f]{64}", fp):
            continue
        row = c.execute("SELECT token_id FROM honeytokens WHERE fingerprint=?", (fp,)).fetchone()
        if row is not None:
            ids.append(row["token_id"])
    return ids
