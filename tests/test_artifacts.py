from __future__ import annotations

import argparse
import contextlib
import io
import tempfile
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mneme.ai import AIResult  # noqa: E402
from mneme.artifacts import store_review_artifact  # noqa: E402
from mneme.cli import handle_ask  # noqa: E402
from mneme.db import connect, initialize, insert_capture  # noqa: E402
from mneme.memory import create_thread, record_thread_state  # noqa: E402
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

    def test_handle_ask_stores_question_answer_artifact_with_linked_evidence(self) -> None:
        tax_note = insert_capture(
            self.conn,
            raw_text="Taxes are overdue and I need to file them this weekend.",
            domains=["Money"],
        )
        receipt_note = insert_capture(
            self.conn,
            raw_text="I am still missing tax receipts needed for filing.",
            domains=["Money"],
        )
        thread_id = create_thread(
            self.conn,
            title="File overdue taxes",
            kind="obligation",
            summary="Finish tax filing and gather missing receipts.",
            domains=["Money"],
            evidence_ids=[tax_note.id],
            salience=0.9,
        )
        record_thread_state(
            self.conn,
            thread_id=thread_id,
            attention="active",
            pressure="high",
            posture="blocked",
            momentum="stable",
            affect="draining",
            horizon="now",
            evidence_ids=[receipt_note.id],
        )

        args = argparse.Namespace(
            db=self.db_path,
            question="What is the status of my tax receipts?",
            local_only=True,
            provider="openai",
            model="gpt-5.4",
            agent="memory",
        )
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            result = handle_ask(args)

        self.assertEqual(result, 0)
        rendered = stdout.getvalue()
        artifact = self._latest_chat_artifact()

        self.assertEqual(artifact["content"]["artifact_kind"], "question_answer")
        self.assertEqual(artifact["content"]["response"]["mode"], "local-only")
        self.assertEqual(artifact["content"]["response"]["provider"], "local")
        self.assertIsNone(artifact["content"]["response"]["request_id"])
        self.assertEqual(
            artifact["content"]["retrieval"]["query_terms"],
            ["status", "tax", "receipt"],
        )
        self.assertEqual(
            artifact["content"]["retrieval"]["relevant_capture_ids"],
            [receipt_note.id, tax_note.id],
        )
        self.assertEqual(
            artifact["content"]["retrieval"]["thread_ids"],
            [thread_id],
        )
        self.assertEqual(
            {row["capture_id"] for row in artifact["evidence"]},
            {tax_note.id, receipt_note.id},
        )
        self.assertEqual(
            {row["note"] for row in artifact["evidence"]},
            {
                "relevant_capture, thread_citation",
                "relevant_capture, thread_state_citation",
            },
        )
        self.assertIn(f"artifact_id: {artifact['id']}", rendered)
        self.assertIn(
            f"supporting_capture_ids: {receipt_note.id}, {tax_note.id}",
            rendered,
        )
        self.assertIn(f"relevant_thread_ids: {thread_id}", rendered)
        self.assertIn("used_recent_fallback: false", rendered)

    def test_handle_ask_records_ai_request_metadata_separately_from_context_packet(self) -> None:
        insert_capture(
            self.conn,
            raw_text="Still missing tax receipts for filing.",
            domains=["Money"],
        )
        args = argparse.Namespace(
            db=self.db_path,
            question="What is the status of my tax receipts?",
            local_only=False,
            provider="openai",
            model="gpt-5.4",
            agent="memory",
        )

        stdout = io.StringIO()
        with (
            patch("mneme.cli.provider_ready", return_value=(True, None)),
            patch(
                "mneme.cli.answer_question",
                return_value=AIResult(
                    text="Answer\n\nObservations\n\nUncertainties\n\nCitations",
                    provider="openai",
                    agent="memory",
                    model="gpt-5.4",
                    request_id="req_123",
                ),
            ),
            contextlib.redirect_stdout(stdout),
        ):
            result = handle_ask(args)

        self.assertEqual(result, 0)
        rendered = stdout.getvalue()
        artifact = self._latest_chat_artifact()

        self.assertEqual(artifact["model"], "gpt-5.4")
        self.assertEqual(artifact["content"]["response"]["provider"], "openai")
        self.assertEqual(artifact["content"]["response"]["agent"], "memory")
        self.assertEqual(artifact["content"]["response"]["request_id"], "req_123")
        self.assertNotIn("request_id", artifact["content"]["context_packet"])
        self.assertIn("Answer", rendered)
        self.assertIn(f"artifact_id: {artifact['id']}", rendered)
        self.assertIn("used_recent_fallback: false", rendered)

    def test_handle_ask_footer_reports_recent_fallback_when_no_matches_exist(self) -> None:
        recent = insert_capture(
            self.conn,
            raw_text="Need to buy groceries and refill soap.",
            domains=["Home"],
        )
        args = argparse.Namespace(
            db=self.db_path,
            question="Meditation retreat planning",
            local_only=True,
            provider="openai",
            model="gpt-5.4",
            agent="memory",
        )

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            result = handle_ask(args)

        self.assertEqual(result, 0)
        rendered = stdout.getvalue()
        artifact = self._latest_chat_artifact()

        self.assertIn(f"artifact_id: {artifact['id']}", rendered)
        self.assertIn(f"supporting_capture_ids: {recent.id}", rendered)
        self.assertIn("used_recent_fallback: true", rendered)
        self.assertNotIn("relevant_thread_ids:", rendered)

    def _latest_chat_artifact(self) -> dict[str, object]:
        rows = list_artifacts_tool(self.conn, artifact_type="chat_turn", limit=10)
        self.assertEqual(len(rows), 1)
        return get_artifact_tool(self.conn, artifact_id=rows[0]["id"])


if __name__ == "__main__":
    unittest.main()
