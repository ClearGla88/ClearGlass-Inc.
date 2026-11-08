import argparse
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import clearkounsel_guard as guard


class ClearCounselGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.database_path = Path(self.temp_dir.name) / "clearcounsel.db"
        self.database_patch = patch.object(guard, "DB_PATH", str(self.database_path))
        self.database_patch.start()
        self.addCleanup(self.database_patch.stop)
        self.db = guard.connect()
        self.addCleanup(self.db.close)
        self.matter_id = guard.run(
            argparse.Namespace(
                actor="test-operator",
                command="new",
                title="Test matter",
                entity="Example entity",
                jurisdiction="To verify",
                owner="Test owner",
            ),
            self.db,
        )["matter_id"]

    def test_deadline_requires_timezone_and_normalizes_to_utc(self):
        with self.assertRaisesRegex(ValueError, "timezone offset"):
            guard.run(
                argparse.Namespace(
                    actor="test-operator",
                    command="deadline",
                    matter=self.matter_id,
                    due="2026-11-07T18:00:00",
                    source="Human entry",
                    owner="Test owner",
                ),
                self.db,
            )

        result = guard.run(
            argparse.Namespace(
                actor="test-operator",
                command="deadline",
                matter=self.matter_id,
                due="2026-11-07T13:00:00-05:00",
                source="Human entry",
                owner="Test owner",
            ),
            self.db,
        )
        deadline = self.db.execute(
            "SELECT due_at, verification FROM deadlines"
        ).fetchone()

        self.assertEqual(result["status"], "UNVERIFIED_HUMAN_ENTRY")
        self.assertEqual(deadline["due_at"], "2026-11-07T18:00:00+00:00")
        self.assertEqual(deadline["verification"], "UNVERIFIED_HUMAN_ENTRY")

    def test_revising_draft_clears_approval_and_old_hash_cannot_approve(self):
        original_body = Path(self.temp_dir.name) / "original.txt"
        revised_body = Path(self.temp_dir.name) / "revised.txt"
        original_body.write_text("Original draft", encoding="utf-8")
        revised_body.write_text("Revised draft", encoding="utf-8")

        draft = guard.run(
            argparse.Namespace(
                actor="test-operator",
                command="draft",
                matter=self.matter_id,
                target="Unresolved recipient",
                body_file=str(original_body),
            ),
            self.db,
        )
        guard.run(
            argparse.Namespace(
                actor="test-operator",
                command="approve",
                draft=draft["draft_id"],
                hash=draft["payload_hash"],
            ),
            self.db,
        )

        revised = guard.run(
            argparse.Namespace(
                actor="test-operator",
                command="revise",
                draft=draft["draft_id"],
                target=None,
                body_file=str(revised_body),
            ),
            self.db,
        )
        current = guard.run(
            argparse.Namespace(
                actor="test-operator",
                command="review",
                draft=draft["draft_id"],
            ),
            self.db,
        )

        self.assertEqual(revised["approval"], "CLEARED")
        self.assertIsNone(current["approved_hash"])
        self.assertNotEqual(current["payload_hash"], draft["payload_hash"])
        with self.assertRaisesRegex(ValueError, "Payload mismatch"):
            guard.run(
                argparse.Namespace(
                    actor="test-operator",
                    command="approve",
                    draft=draft["draft_id"],
                    hash=draft["payload_hash"],
                ),
                self.db,
            )


if __name__ == "__main__":
    unittest.main()
