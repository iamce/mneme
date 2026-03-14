from __future__ import annotations

import tempfile
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mneme.artifacts import store_review_artifact  # noqa: E402
from mneme.db import connect, initialize, insert_capture  # noqa: E402
from mneme.tools import (  # noqa: E402
    build_review_summary,
    consolidate_recent_captures_tool,
    get_artifact_tool,
    list_artifacts_tool,
)


class ArtifactToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "mneme.db"
        self.conn = connect(self.db_path)
        initialize(self.conn)

    def tearDown(self) -> None:
        self.conn.close()
        self.tempdir.cleanup()

    def test_get_artifact_returns_consolidation_run_with_evidence(self) -> None:
        first = insert_capture(
            self.conn,
            raw_text="Taxes are overdue and I still need to file.",
            domains=["Money"],
        )
        second = insert_capture(
            self.conn,
            raw_text="Still missing tax receipts for filing.",
            domains=["Money"],
        )

        result = consolidate_recent_captures_tool(self.conn, days=30, limit=10)

        artifact = get_artifact_tool(self.conn, artifact_id=result["artifact_id"])

        self.assertEqual(artifact["model"], "local-consolidation")
        self.assertEqual(artifact["content"]["artifact_kind"], "consolidation_run")
        self.assertEqual(artifact["content"]["candidate_count"], 1)
        self.assertEqual(
            {row["capture_id"] for row in artifact["evidence"]},
            {first.id, second.id},
        )

    def test_list_artifacts_filters_recent_system_artifacts(self) -> None:
        insert_capture(
            self.conn,
            raw_text="Plan taxes this week and sort receipts.",
            domains=["Money"],
        )
        run = consolidate_recent_captures_tool(self.conn, days=30, limit=10)

        text_output, content, artifact_type = build_review_summary(self.conn, days=7)
        store_review_artifact(
            self.conn,
            text_output=text_output,
            content=content,
            artifact_type=artifact_type,
        )

        rows = list_artifacts_tool(
            self.conn,
            target_type="system",
            model="local-consolidation",
            limit=10,
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], run["artifact_id"])
        self.assertEqual(rows[0]["content"]["artifact_kind"], "consolidation_run")
        self.assertEqual(rows[0]["evidence_count"], 1)


if __name__ == "__main__":
    unittest.main()
