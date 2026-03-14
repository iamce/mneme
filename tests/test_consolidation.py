from __future__ import annotations

import tempfile
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mneme.consolidation import consolidate_recent_captures
from mneme.db import connect, initialize, insert_capture


class ConsolidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "mneme.db"
        self.conn = connect(self.db_path)
        initialize(self.conn)

    def tearDown(self) -> None:
        self.conn.close()
        self.tempdir.cleanup()

    def test_dry_run_and_apply_create_thread_state_and_artifact(self) -> None:
        insert_capture(
            self.conn,
            raw_text="Taxes are overdue and I need to file them today.",
            domains=["Money"],
        )
        insert_capture(
            self.conn,
            raw_text="Still overdue on taxes and missing a few receipts.",
            domains=["Money"],
        )
        insert_capture(self.conn, raw_text="Loose thought without a domain.")

        preview = consolidate_recent_captures(self.conn, days=30, limit=10, dry_run=True)
        self.assertTrue(preview["dry_run"])
        self.assertEqual(preview["candidate_count"], 1)
        self.assertEqual(preview["candidates"][0]["action"], "create_thread")
        self.assertEqual(preview["candidates"][0]["domain"], "Money")
        self.assertIn(
            {"capture_id": preview["skipped"][0]["capture_id"], "reason": "missing_domain"},
            preview["skipped"],
        )

        applied = consolidate_recent_captures(self.conn, days=30, limit=10)
        self.assertFalse(applied["dry_run"])
        self.assertEqual(applied["created_thread_count"], 1)
        self.assertEqual(applied["updated_thread_count"], 0)
        self.assertEqual(applied["state_count"], 1)
        self.assertTrue(applied["artifact_id"].startswith("art_"))

        thread_count = self.conn.execute("SELECT COUNT(*) AS count FROM threads").fetchone()["count"]
        state_count = self.conn.execute("SELECT COUNT(*) AS count FROM thread_states").fetchone()["count"]
        link_count = self.conn.execute("SELECT COUNT(*) AS count FROM evidence_links").fetchone()["count"]

        self.assertEqual(thread_count, 1)
        self.assertEqual(state_count, 1)
        self.assertEqual(link_count, 6)

    def test_second_run_updates_matching_thread_instead_of_creating_duplicate(self) -> None:
        insert_capture(
            self.conn,
            raw_text="Taxes are overdue and I need to file them today.",
            domains=["Money"],
        )
        insert_capture(
            self.conn,
            raw_text="Still overdue on taxes and missing a few receipts.",
            domains=["Money"],
        )
        first = consolidate_recent_captures(self.conn, days=30, limit=10)
        original_thread_id = first["consolidated"][0]["thread_id"]

        insert_capture(
            self.conn,
            raw_text="Tax receipts are overdue again this week.",
            domains=["Money"],
        )
        second = consolidate_recent_captures(self.conn, days=30, limit=10)

        self.assertEqual(second["created_thread_count"], 0)
        self.assertEqual(second["updated_thread_count"], 1)
        self.assertEqual(second["consolidated"][0]["thread_id"], original_thread_id)

        thread_count = self.conn.execute("SELECT COUNT(*) AS count FROM threads").fetchone()["count"]
        state_count = self.conn.execute("SELECT COUNT(*) AS count FROM thread_states").fetchone()["count"]
        thread_evidence_count = self.conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM evidence_links
            WHERE subject_type = 'thread' AND subject_id = ?
            """,
            (original_thread_id,),
        ).fetchone()["count"]

        self.assertEqual(thread_count, 1)
        self.assertEqual(state_count, 2)
        self.assertEqual(thread_evidence_count, 3)

    def test_apply_without_candidates_returns_zero_counts(self) -> None:
        result = consolidate_recent_captures(self.conn, days=30, limit=10)

        self.assertFalse(result["dry_run"])
        self.assertEqual(result["created_thread_count"], 0)
        self.assertEqual(result["updated_thread_count"], 0)
        self.assertEqual(result["state_count"], 0)
        self.assertEqual(result["consolidated"], [])
        self.assertNotIn("artifact_id", result)


if __name__ == "__main__":
    unittest.main()
