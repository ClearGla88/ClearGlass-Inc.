import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = "clearcounsel.db"


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def connect():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS matters (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            entity TEXT NOT NULL,
            jurisdiction TEXT NOT NULL,
            owner TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS evidence (
            id INTEGER PRIMARY KEY,
            matter_id INTEGER NOT NULL REFERENCES matters(id),
            filename TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            source TEXT NOT NULL,
            recorded_by TEXT NOT NULL,
            recorded_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS deadlines (
            id INTEGER PRIMARY KEY,
            matter_id INTEGER NOT NULL REFERENCES matters(id),
            due_at TEXT NOT NULL,
            source TEXT NOT NULL,
            owner TEXT NOT NULL,
            verification TEXT NOT NULL,
            recorded_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS drafts (
            id INTEGER PRIMARY KEY,
            matter_id INTEGER NOT NULL REFERENCES matters(id),
            target TEXT NOT NULL,
            body TEXT NOT NULL,
            version INTEGER NOT NULL,
            payload_hash TEXT NOT NULL,
            approved_hash TEXT,
            approved_by TEXT,
            approved_at TEXT,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS audit (
            id INTEGER PRIMARY KEY,
            event TEXT NOT NULL,
            actor TEXT NOT NULL,
            details TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
    """)
    db.commit()
    return db


def audit(db, event, actor, details):
    db.execute(
        "INSERT INTO audit(event, actor, details, created_at) VALUES(?,?,?,?)",
        (event, actor, json.dumps(details, sort_keys=True), now()),
    )


def require_matter(db, matter_id):
    row = db.execute(
        "SELECT * FROM matters WHERE id=?", (matter_id,)
    ).fetchone()
    if row is None:
        raise ValueError("Matter not found.")
    return row


def draft_payload(matter_id, target, body, version):
    return {
        "matter_id": matter_id,
        "target": target,
        "body": body,
        "version": version,
    }


def run(args, db):
    actor = args.actor

    if args.command == "new":
        with db:
            cursor = db.execute(
                """INSERT INTO matters
                (title, entity, jurisdiction, owner, created_at)
                VALUES(?,?,?,?,?)""",
                (args.title, args.entity, args.jurisdiction, args.owner, now()),
            )
            matter_id = cursor.lastrowid
            audit(db, "MATTER_CREATED", actor, {"matter_id": matter_id})
        return {"matter_id": matter_id}

    if args.command == "evidence":
        require_matter(db, args.matter)
        path = Path(args.file)
        file_hash = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                file_hash.update(block)
        value = file_hash.hexdigest()

        with db:
            cursor = db.execute(
                """INSERT INTO evidence
                (matter_id, filename, sha256, source, recorded_by, recorded_at)
                VALUES(?,?,?,?,?,?)""",
                (args.matter, path.name, value, args.source, actor, now()),
            )
            audit(db, "EVIDENCE_REFERENCE_ADDED", actor, {
                "matter_id": args.matter,
                "evidence_id": cursor.lastrowid,
                "sha256": value,
            })
        return {
            "sha256": value,
            "notice": "File reference recorded. Original file was not copied."
        }

    if args.command == "deadline":
        require_matter(db, args.matter)
        due = datetime.fromisoformat(args.due.replace("Z", "+00:00"))
        if due.tzinfo is None or due.utcoffset() is None:
            raise ValueError("Deadline must include a timezone offset.")

        with db:
            cursor = db.execute(
                """INSERT INTO deadlines
                (matter_id, due_at, source, owner, verification, recorded_at)
                VALUES(?,?,?,?,?,?)""",
                (
                    args.matter,
                    due.astimezone(timezone.utc).isoformat(),
                    args.source,
                    args.owner,
                    "UNVERIFIED_HUMAN_ENTRY",
                    now(),
                ),
            )
            audit(db, "DEADLINE_RECORDED_UNVERIFIED", actor, {
                "matter_id": args.matter,
                "deadline_id": cursor.lastrowid,
            })
        return {"status": "UNVERIFIED_HUMAN_ENTRY"}

    if args.command == "draft":
        require_matter(db, args.matter)
        body = Path(args.body_file).read_text(encoding="utf-8")
        payload = draft_payload(args.matter, args.target, body, 1)
        value = digest(payload)

        with db:
            cursor = db.execute(
                """INSERT INTO drafts
                (matter_id, target, body, version, payload_hash, updated_at)
                VALUES(?,?,?,?,?,?)""",
                (args.matter, args.target, body, 1, value, now()),
            )
            draft_id = cursor.lastrowid
            audit(db, "DRAFT_CREATED", actor, {
                "draft_id": draft_id,
                "payload_hash": value,
            })
        return {"draft_id": draft_id, "payload_hash": value}

    if args.command == "revise":
        body = Path(args.body_file).read_text(encoding="utf-8")
        with db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM drafts WHERE id=?", (args.draft,)
            ).fetchone()
            if row is None:
                raise ValueError("Draft not found.")

            version = row["version"] + 1
            target = args.target if args.target is not None else row["target"]
            value = digest(
                draft_payload(row["matter_id"], target, body, version)
            )
            db.execute(
                """UPDATE drafts SET target=?, body=?, version=?,
                payload_hash=?, approved_hash=NULL, approved_by=NULL,
                approved_at=NULL, updated_at=? WHERE id=?""",
                (target, body, version, value, now(), args.draft),
            )
            audit(db, "DRAFT_REVISED_APPROVAL_CLEARED", actor, {
                "draft_id": args.draft,
                "version": version,
                "payload_hash": value,
            })
        return {"payload_hash": value, "approval": "CLEARED"}

    if args.command == "review":
        row = db.execute(
            "SELECT * FROM drafts WHERE id=?", (args.draft,)
        ).fetchone()
        if row is None:
            raise ValueError("Draft not found.")
        return dict(row)

    if args.command == "approve":
        with db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM drafts WHERE id=?", (args.draft,)
            ).fetchone()
            if row is None:
                raise ValueError("Draft not found.")
            expected = digest(draft_payload(
                row["matter_id"], row["target"], row["body"], row["version"]
            ))
            if expected != row["payload_hash"] or args.hash != expected:
                raise ValueError("Payload mismatch. Review the current draft.")
            db.execute(
                """UPDATE drafts SET approved_hash=?, approved_by=?,
                approved_at=? WHERE id=?""",
                (expected, actor, now(), args.draft),
            )
            audit(db, "LOCAL_APPROVAL_RECORDED", actor, {
                "draft_id": args.draft,
                "payload_hash": expected,
            })
        return {
            "status": "LOCAL_APPROVAL_RECORDED",
            "notice": "Not authenticated authorization or counsel approval."
        }

    if args.command == "report":
        matter = require_matter(db, args.matter)
        result = {"matter": dict(matter)}
        for table in ("evidence", "deadlines", "drafts"):
            result[table] = [
                dict(row) for row in db.execute(
                    f"SELECT * FROM {table} WHERE matter_id=?",
                    (args.matter,),
                ).fetchall()
            ]
        return result

    if args.command == "audit":
        return [
            dict(row) for row in db.execute(
                "SELECT * FROM audit ORDER BY id"
            ).fetchall()
        ]


def parser():
    root = argparse.ArgumentParser(
        description=(
            "ClearCounsel Guard local-only prototype. Not legal advice and does "
            "not create solicitor-client privilege."
        )
    )
    root.add_argument("--actor", required=True, help="Self-reported operator")
    commands = root.add_subparsers(dest="command", required=True)

    p = commands.add_parser("new")
    for field in ("title", "entity", "jurisdiction", "owner"):
        p.add_argument(f"--{field}", required=True)

    p = commands.add_parser("evidence")
    p.add_argument("--matter", type=int, required=True)
    p.add_argument("--file", required=True)
    p.add_argument("--source", required=True)

    p = commands.add_parser("deadline")
    p.add_argument("--matter", type=int, required=True)
    for field in ("due", "source", "owner"):
        p.add_argument(f"--{field}", required=True)

    p = commands.add_parser("draft")
    p.add_argument("--matter", type=int, required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--body-file", required=True)

    p = commands.add_parser("revise")
    p.add_argument("--draft", type=int, required=True)
    p.add_argument("--target")
    p.add_argument("--body-file", required=True)

    for command in ("review", "approve"):
        p = commands.add_parser(command)
        p.add_argument("--draft", type=int, required=True)
        if command == "approve":
            p.add_argument("--hash", required=True)

    p = commands.add_parser("report")
    p.add_argument("--matter", type=int, required=True)
    commands.add_parser("audit")
    return root


if __name__ == "__main__":
    database = None
    try:
        arguments = parser().parse_args()
        database = connect()
        result = run(arguments, database)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except (ValueError, OSError, sqlite3.Error) as error:
        raise SystemExit(f"ERROR: {error}")
    finally:
        if database is not None:
            database.close()
