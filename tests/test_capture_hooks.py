from __future__ import annotations

import io
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mneme.cli import build_parser  # noqa: E402
from mneme.db import connect, initialize, insert_capture  # noqa: E402
import mneme.mcp_server as mcp_server  # noqa: E402
from mneme.tools import get_artifact_tool  # noqa: E402


class CaptureHookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "mneme.db"
        self.conn = connect(self.db_path)
        initialize(self.conn)

    def tearDown(self) -> None:
        self.conn.close()
        self.tempdir.cleanup()

    def test_cli_capture_can_run_triggered_preview(self) -> None:
        first = insert_capture(
            self.conn,
            raw_text="Taxes are overdue and I need to file them today.",
            domains=["Money"],
        )

        parser = build_parser()
        args = parser.parse_args(
            [
                "--db",
                str(self.db_path),
                "capture",
                "Still overdue on taxes and missing a few receipts.",
                "--domain",
                "Money",
                "--trigger-consolidation",
                "--consolidation-days",
                "30",
                "--consolidation-limit",
                "10",
            ]
        )

        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = args.handler(args)

        self.assertEqual(exit_code, 0)
        rendered = output.getvalue()
        self.assertIn("trigger_execution_mode: preview", rendered)
        self.assertIn("trigger_decision_reason: capture_trigger_requires_preview", rendered)
        artifact_id = re.search(r"trigger_artifact_id: (.+)", rendered)
        self.assertIsNotNone(artifact_id)
        capture_id = re.search(r"\[(.+?)\] stored", rendered)
        self.assertIsNotNone(capture_id)

        artifact = get_artifact_tool(self.conn, artifact_id=artifact_id.group(1).strip())
        self.assertEqual(artifact["content"]["trigger"], "capture")
        self.assertEqual(artifact["content"]["execution_mode"], "preview")
        self.assertEqual(
            {row["capture_id"] for row in artifact["evidence"]},
            {first.id, capture_id.group(1)},
        )

    def test_mcp_create_capture_can_run_triggered_preview(self) -> None:
        first = insert_capture(
            self.conn,
            raw_text="Taxes are overdue and I need to file them today.",
            domains=["Money"],
        )

        with patch.object(mcp_server, "DEFAULT_SERVER_DB_PATH", str(self.db_path)):
            result = mcp_server.create_capture(
                text="Still overdue on taxes and missing a few receipts.",
                domains=["Money"],
                run_consolidation=True,
                consolidation_days=30,
                consolidation_limit=10,
            )

        self.assertEqual(result["triggered_consolidation"]["execution_mode"], "preview")
        self.assertEqual(
            result["triggered_consolidation"]["decision_reason"],
            "capture_trigger_requires_preview",
        )

        artifact = get_artifact_tool(
            self.conn,
            artifact_id=result["triggered_consolidation"]["artifact_id"],
        )
        self.assertEqual(artifact["content"]["trigger"], "capture")
        self.assertEqual(artifact["content"]["execution_mode"], "preview")
        self.assertEqual(
            {row["capture_id"] for row in artifact["evidence"]},
            {first.id, result["id"]},
        )


if __name__ == "__main__":
    unittest.main()
