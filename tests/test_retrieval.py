from __future__ import annotations

import tempfile
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mneme.db import connect, initialize, insert_capture  # noqa: E402
from mneme.memory import create_thread, record_thread_state  # noqa: E402
from mneme.retrieval import build_context_packet, render_context_packet  # noqa: E402


class RetrievalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "mneme.db"
        self.conn = connect(self.db_path)
        initialize(self.conn)

    def tearDown(self) -> None:
        self.conn.close()
        self.tempdir.cleanup()

    def test_context_packet_ranks_matching_captures_and_threads_with_citations(self) -> None:
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
        insert_capture(
            self.conn,
            raw_text="Need to buy groceries and refill soap.",
            domains=["Home"],
        )

        tax_thread_id = create_thread(
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
            thread_id=tax_thread_id,
            attention="active",
            pressure="high",
            posture="blocked",
            momentum="stable",
            affect="draining",
            horizon="now",
            evidence_ids=[receipt_note.id],
        )
        create_thread(
            self.conn,
            title="Restock pantry",
            kind="obligation",
            summary="Buy groceries and cleaning supplies.",
            domains=["Home"],
            salience=0.3,
        )

        packet = build_context_packet(self.conn, "What is the status of my tax receipts?", days=30)

        self.assertEqual(packet["query_terms"], ["status", "tax", "receipt"])
        self.assertFalse(packet["used_recent_fallback"])
        self.assertEqual(packet["relevant_captures"][0]["id"], receipt_note.id)
        self.assertEqual(packet["relevant_captures"][0]["matched_terms"], ["tax", "receipt"])

        self.assertEqual(packet["threads"][0]["id"], tax_thread_id)
        self.assertEqual(packet["threads"][0]["matched_terms"], ["tax", "receipt"])
        self.assertEqual(packet["threads"][0]["current_state"]["pressure"], "high")
        self.assertEqual(
            {row["capture_id"] for row in packet["threads"][0]["citations"]},
            {tax_note.id, receipt_note.id},
        )
        self.assertIn(
            "thread_state",
            {row["subject_type"] for row in packet["threads"][0]["citations"]},
        )

        rendered = render_context_packet(packet)
        self.assertIn("Relevant threads:", rendered)
        self.assertIn("File overdue taxes", rendered)
        self.assertIn("citations:", rendered)
        self.assertIn(receipt_note.id, rendered)

    def test_context_packet_keeps_recent_fallback_when_no_query_terms_match(self) -> None:
        capture = insert_capture(
            self.conn,
            raw_text="Need to buy groceries and refill soap.",
            domains=["Home"],
        )

        packet = build_context_packet(self.conn, "Meditation retreat planning", days=30)

        self.assertTrue(packet["used_recent_fallback"])
        self.assertEqual(packet["relevant_captures"][0]["id"], capture.id)
        self.assertEqual(packet["relevant_captures"][0]["matched_terms"], [])
        self.assertEqual(packet["threads"], [])


if __name__ == "__main__":
    unittest.main()
