from __future__ import annotations

import tempfile
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mneme.consolidation import consolidate_recent_captures  # noqa: E402
from mneme.db import connect, initialize, insert_capture  # noqa: E402
from mneme.memory import create_thread, get_thread_bundle, record_thread_state  # noqa: E402


class ThreadLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "mneme.db"
        self.conn = connect(self.db_path)
        initialize(self.conn)

    def tearDown(self) -> None:
        self.conn.close()
        self.tempdir.cleanup()

    def test_matched_thread_update_refreshes_status_summary_and_bundle_history(self) -> None:
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
        thread_id = first["consolidated"][0]["thread_id"]

        insert_capture(
            self.conn,
            raw_text="Finished filing taxes and sent the receipts.",
            domains=["Money"],
        )
        second = consolidate_recent_captures(self.conn, days=30, limit=10)

        self.assertEqual(second["updated_thread_count"], 1)
        thread = self.conn.execute(
            "SELECT status, canonical_summary FROM threads WHERE id = ?",
            (thread_id,),
        ).fetchone()
        self.assertEqual(thread["status"], "closed")
        self.assertIn("Finished filing taxes", thread["canonical_summary"])

        bundle = get_thread_bundle(self.conn, thread_id)
        self.assertEqual(bundle["thread"]["status"], "closed")
        self.assertEqual(len(bundle["state_history"]), 2)
        self.assertEqual(len(bundle["artifacts"]), 2)
        self.assertEqual(bundle["artifacts"][0]["content"]["status_after"], "closed")
        self.assertEqual(bundle["artifacts"][0]["content"]["action"], "update_thread")
        self.assertGreaterEqual(len(bundle["state_evidence"]), 3)
        self.assertEqual(bundle["thread_evidence"][0]["relation"], "updates")

    def test_consolidation_marks_deferred_thread_as_dormant(self) -> None:
        insert_capture(
            self.conn,
            raw_text="Eventually need to sort the garage storage bins.",
            domains=["Home"],
        )
        insert_capture(
            self.conn,
            raw_text="Garage storage can stay paused until later.",
            domains=["Home"],
        )

        result = consolidate_recent_captures(self.conn, days=30, limit=10)

        thread_id = result["consolidated"][0]["thread_id"]
        thread = self.conn.execute("SELECT status FROM threads WHERE id = ?", (thread_id,)).fetchone()
        self.assertEqual(thread["status"], "dormant")

    def test_record_thread_state_can_override_status(self) -> None:
        thread_id = create_thread(
            self.conn,
            title="Work: launch plan",
            kind="workstream",
            summary="Launch planning thread.",
            domains=["Work"],
        )

        record_thread_state(
            self.conn,
            thread_id=thread_id,
            attention="background",
            pressure="low",
            posture="waiting",
            momentum="stable",
            affect="neutral",
            horizon="later",
            status="closed",
        )

        thread = self.conn.execute("SELECT status FROM threads WHERE id = ?", (thread_id,)).fetchone()
        self.assertEqual(thread["status"], "closed")


if __name__ == "__main__":
    unittest.main()
