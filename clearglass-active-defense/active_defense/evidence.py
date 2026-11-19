"""Evidence artifacts, custody records, manifests and retention.

A SHA-256 hash shows that content has not changed since it was hashed. It does
not, by itself, prove who held the content or that the database was not
rewritten wholesale. Custody records and the hash-chained audit log narrow that
gap; they do not close it. See SECURITY.md, "Evidence limits".
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from .store import Store
from .util import canonical_json, iso, new_id, sha256_hex


def store_artifact(
    c: sqlite3.Connection, content: bytes, *, media_type: str, collector: str, received_by: str, at: datetime
) -> tuple[str, str]:
    artifact_id = new_id("art")
    digest = sha256_hex(content)
    c.execute(
        "INSERT INTO artifacts (artifact_id, sha256, size, media_type, content, collected_at, collector, received_by) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (artifact_id, digest, len(content), media_type, content, iso(at), collector, received_by),
    )
    add_custody(c, artifact_id, "collected", received_by, at, f"from {collector}; sha256 {digest}")
    return artifact_id, digest


def add_custody(c: sqlite3.Connection, artifact_id: str, action: str, actor: str, at: datetime, note: str) -> None:
    c.execute(
        "INSERT INTO custody (artifact_id, action, actor, at, note) VALUES (?,?,?,?,?)",
        (artifact_id, action, actor, iso(at), note),
    )


def case_artifacts(c: sqlite3.Connection, case_id: str) -> list[sqlite3.Row]:
    return c.execute(
        "SELECT a.* FROM artifacts a JOIN events e ON e.artifact_id = a.artifact_id "
        "JOIN case_events ce ON ce.event_pk = e.event_pk WHERE ce.case_id=? ORDER BY a.collected_at, a.artifact_id",
        (case_id,),
    ).fetchall()


def case_manifest(c: sqlite3.Connection, case_id: str, *, at: datetime) -> dict:
    items = [
        {
            "artifact_id": r["artifact_id"],
            "sha256": r["sha256"],
            "size": r["size"],
            "media_type": r["media_type"],
            "collected_at": r["collected_at"],
            "collector": r["collector"],
            "purged": r["purged_at"] is not None,
        }
        for r in case_artifacts(c, case_id)
    ]
    body = {"case_id": case_id, "artifacts": items}
    return {
        **body,
        "generated_at": iso(at),
        "manifest_sha256": sha256_hex(canonical_json(body)),
        "limits": "Hashes show the content is unchanged since collection; they do not prove custody on their own.",
    }


def verify_case(c: sqlite3.Connection, case_id: str) -> dict:
    problems = []
    rows = case_artifacts(c, case_id)
    for r in rows:
        if r["content"] is None:
            if r["purged_at"] is None:
                problems.append({"artifact_id": r["artifact_id"], "problem": "content missing without a purge record"})
            continue
        if sha256_hex(bytes(r["content"])) != r["sha256"] or len(r["content"]) != r["size"]:
            problems.append({"artifact_id": r["artifact_id"], "problem": "content does not match recorded hash"})
        custody = c.execute(
            "SELECT action FROM custody WHERE artifact_id=? ORDER BY seq LIMIT 1", (r["artifact_id"],)
        ).fetchone()
        if custody is None or custody["action"] != "collected":
            problems.append({"artifact_id": r["artifact_id"], "problem": "no collection custody record"})
    return {"case_id": case_id, "artifacts": len(rows), "ok": not problems, "problems": problems}


def apply_retention(store: Store, *, retention_days: int, at: datetime, actor: str) -> int:
    """Purge content older than the retention period. Hash and custody rows stay.

    Content tied to an open case or under legal hold is kept."""
    cutoff = iso(at - timedelta(days=retention_days))
    purged = 0
    with store.tx() as c:
        rows = c.execute(
            "SELECT a.artifact_id FROM artifacts a WHERE a.content IS NOT NULL AND a.legal_hold=0 "
            "AND a.collected_at < ? AND NOT EXISTS ("
            "  SELECT 1 FROM events e JOIN case_events ce ON ce.event_pk=e.event_pk "
            "  JOIN cases k ON k.case_id=ce.case_id WHERE e.artifact_id=a.artifact_id AND k.state != 'closed')",
            (cutoff,),
        ).fetchall()
        for r in rows:
            c.execute("UPDATE artifacts SET content=NULL, purged_at=? WHERE artifact_id=?", (iso(at), r["artifact_id"]))
            add_custody(c, r["artifact_id"], "purged", actor, at, f"retention {retention_days} days")
            purged += 1
        Store.audit(
            c, at=at, actor=actor, action="evidence.retention", subject="artifacts",
            details={"purged": purged, "retention_days": retention_days},
        )
    return purged
