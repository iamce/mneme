from __future__ import annotations

import tempfile
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mneme.db import connect, initialize, insert_capture  # noqa: E402
from mneme.tools import get_artifact_tool, run_triggered_consolidation_tool  # noqa: E402


class TriggeredConsolidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "mneme.db"
        self.conn = connect(self.db_path)
        initialize(self.conn)

    def tearDown(self) -> None:
        self.conn.close()
        self.tempdir.cleanup()

    def test_capture_trigger_previews_and_stores_artifact(self) -> None:
        first = insert_capture(
            self.conn,
            raw_text="Taxes are overdue and I need to file them today.",
            domains=["Money"],
        )
        second = insert_capture(
            self.conn,
            raw_text="Still overdue on taxes and missing a few receipts.",
            domains=["Money"],
        )

        result = run_triggered_consolidation_tool(self.conn, trigger="capture", days=30, limit=10)

        self.assertEqual(result["execution_mode"], "preview")
        self.assertEqual(result["decision_reason"], "capture_trigger_requires_preview")
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) AS count FROM threads").fetchone()["count"],
            0,
        )

        artifact = get_artifact_tool(self.conn, artifact_id=result["artifact_id"])
        self.assertEqual(artifact["content"]["trigger"], "capture")
        self.assertEqual(artifact["content"]["execution_mode"], "preview")
        self.assertTrue(artifact["content"]["dry_run"])
        self.assertEqual(
            {row["capture_id"] for row in artifact["evidence"]},
            {first.id, second.id},
        )

    def test_schedule_trigger_applies_when_plan_has_no_reviewable_skips(self) -> None:
        first = insert_capture(
            self.conn,
            raw_text="Taxes are overdue and I need to file them today.",
            domains=["Money"],
        )
        second = insert_capture(
            self.conn,
            raw_text="Still overdue on taxes and missing a few receipts.",
            domains=["Money"],
        )

        result = run_triggered_consolidation_tool(self.conn, trigger="schedule", days=30, limit=10)

        self.assertEqual(result["execution_mode"], "apply")
        self.assertEqual(result["decision_reason"], "schedule_safe_to_apply")
        self.assertFalse(result["dry_run"])
        self.assertEqual(result["created_thread_count"], 1)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) AS count FROM threads").fetchone()["count"],
            1,
        )

        artifact = get_artifact_tool(self.conn, artifact_id=result["artifact_id"])
        self.assertEqual(artifact["content"]["trigger"], "schedule")
        self.assertEqual(artifact["content"]["execution_mode"], "apply")
        self.assertFalse(artifact["content"]["dry_run"])
        self.assertEqual(
            {row["capture_id"] for row in artifact["evidence"]},
            {first.id, second.id},
        )

    def test_schedule_trigger_previews_when_reviewable_skip_is_present(self) -> None:
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
        leftover = insert_capture(
            self.conn,
            raw_text="I should compare a few savings account options.",
            domains=["Money"],
        )

        result = run_triggered_consolidation_tool(self.conn, trigger="schedule", days=30, limit=10)

        self.assertEqual(result["execution_mode"], "preview")
        self.assertEqual(result["decision_reason"], "reviewable_skips_present")
        self.assertTrue(result["dry_run"])
        self.assertIn(
            {
                "domain": "Money",
                "capture_ids": [leftover.id],
                "reason": "low_overlap",
            },
            result["skipped"],
        )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) AS count FROM threads").fetchone()["count"],
            0,
        )


if __name__ == "__main__":
    unittest.main()
