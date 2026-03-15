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
        self.assertEqual(
            packet["relevant_captures"][0]["ranking_reason"],
            {
                "matched_term_count": 2,
                "direct_match_count": 2,
                "thread_support_count": 0,
                "matched_terms": ["tax", "receipt"],
            },
        )

        self.assertEqual(packet["threads"][0]["id"], tax_thread_id)
        self.assertEqual(packet["threads"][0]["matched_terms"], ["tax", "receipt"])
        self.assertEqual(packet["threads"][0]["current_state"]["pressure"], "high")
        self.assertEqual(
            packet["threads"][0]["ranking_reason"],
            {
                "matched_term_count": 2,
                "surface_match_count": 2,
                "state_match_count": 0,
                "evidence_match_count": 2,
                "matched_terms": ["tax", "receipt"],
            },
        )
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
        self.assertIn("ranking: matched_terms=tax, receipt; direct=2; thread_support=0", rendered)
        self.assertIn("ranking: matched_terms=tax, receipt; surface=2; state=0; evidence=2", rendered)
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
        self.assertEqual(
            packet["relevant_captures"][0]["ranking_reason"],
            {
                "matched_term_count": 0,
                "direct_match_count": 0,
                "thread_support_count": 0,
                "matched_terms": [],
                "fallback": "recent",
            },
        )
        self.assertEqual(packet["threads"], [])

    def test_context_packet_ranks_threads_by_current_state_terms(self) -> None:
        stalled_capture = insert_capture(
            self.conn,
            raw_text="Tax filing is still waiting on missing receipts.",
            domains=["Money"],
        )
        winning_thread_id = create_thread(
            self.conn,
            title="Finish filing",
            kind="obligation",
            summary="Close out the filing workflow.",
            domains=["Money"],
            evidence_ids=[stalled_capture.id],
            salience=0.4,
        )
        record_thread_state(
            self.conn,
            thread_id=winning_thread_id,
            attention="active",
            pressure="high",
            posture="blocked",
            momentum="stable",
            affect="draining",
            horizon="now",
            evidence_ids=[stalled_capture.id],
        )

        other_capture = insert_capture(
            self.conn,
            raw_text="Blocked on a package delivery.",
            domains=["Home"],
        )
        create_thread(
            self.conn,
            title="Restock kitchen",
            kind="obligation",
            summary="Buy missing supplies.",
            domains=["Home"],
            evidence_ids=[other_capture.id],
            salience=0.9,
        )

        packet = build_context_packet(self.conn, "What is blocked right now?", days=30)

        self.assertFalse(packet["used_recent_fallback"])
        self.assertEqual(packet["relevant_captures"][0]["id"], stalled_capture.id)
        self.assertEqual(packet["relevant_captures"][0]["matched_terms"], [])
        self.assertEqual(packet["relevant_captures"][0]["thread_matched_terms"], ["blocked", "now"])
        self.assertEqual(packet["relevant_captures"][0]["supporting_thread_ids"], [winning_thread_id])
        self.assertEqual(
            packet["relevant_captures"][0]["ranking_reason"],
            {
                "matched_term_count": 2,
                "direct_match_count": 0,
                "thread_support_count": 2,
                "matched_terms": ["blocked", "now"],
            },
        )
        self.assertEqual(packet["threads"][0]["id"], winning_thread_id)
        self.assertEqual(packet["threads"][0]["matched_terms"], ["blocked", "now"])
        self.assertEqual(
            packet["threads"][0]["ranking_reason"],
            {
                "matched_term_count": 2,
                "surface_match_count": 0,
                "state_match_count": 2,
                "evidence_match_count": 0,
                "matched_terms": ["blocked", "now"],
            },
        )
        rendered = render_context_packet(packet)
        self.assertIn("thread support: blocked, now via", rendered)
        self.assertIn("ranking: matched_terms=blocked, now; direct=0; thread_support=2", rendered)
        self.assertIn("matched: blocked, now", rendered)
        self.assertIn("ranking: matched_terms=blocked, now; surface=0; state=2; evidence=0", rendered)
        self.assertIn("posture=blocked", rendered)

    def test_context_packet_ranks_threads_by_thread_status(self) -> None:
        capture = insert_capture(
            self.conn,
            raw_text="The passport renewal can wait until summer.",
            domains=["Home"],
        )
        dormant_thread_id = create_thread(
            self.conn,
            title="Renew passport",
            kind="obligation",
            summary="Handle passport renewal later.",
            domains=["Home"],
            status="dormant",
            evidence_ids=[capture.id],
            salience=0.3,
        )
        create_thread(
            self.conn,
            title="Book travel",
            kind="obligation",
            summary="Choose flights for the trip.",
            domains=["Home"],
            salience=0.8,
        )

        packet = build_context_packet(self.conn, "What is dormant?", days=30)

        self.assertFalse(packet["used_recent_fallback"])
        self.assertEqual(packet["relevant_captures"][0]["id"], capture.id)
        self.assertEqual(packet["relevant_captures"][0]["thread_matched_terms"], ["dormant"])
        self.assertEqual(packet["relevant_captures"][0]["supporting_thread_ids"], [dormant_thread_id])
        self.assertEqual(packet["threads"][0]["id"], dormant_thread_id)
        self.assertEqual(packet["threads"][0]["matched_terms"], ["dormant"])

    def test_context_packet_prefers_broader_thread_match_over_more_salient_partial_match(self) -> None:
        partial_capture = insert_capture(
            self.conn,
            raw_text="Taxes need attention this week.",
            domains=["Money"],
        )
        full_capture = insert_capture(
            self.conn,
            raw_text="Still missing tax receipts for filing.",
            domains=["Money"],
        )

        partial_thread_id = create_thread(
            self.conn,
            title="File taxes",
            kind="obligation",
            summary="Handle the filing soon.",
            domains=["Money"],
            evidence_ids=[partial_capture.id],
            salience=0.95,
        )
        full_thread_id = create_thread(
            self.conn,
            title="Paperwork cleanup",
            kind="obligation",
            summary="Administrative loose ends.",
            domains=["Money"],
            evidence_ids=[full_capture.id],
            salience=0.2,
        )

        packet = build_context_packet(self.conn, "What about tax receipts?", days=30)

        self.assertEqual(packet["threads"][0]["id"], full_thread_id)
        self.assertEqual(packet["threads"][0]["matched_terms"], ["tax", "receipt"])
        self.assertEqual(packet["threads"][1]["id"], partial_thread_id)

    def test_context_packet_matches_name_aliases_with_expanded_ranking_reason(self) -> None:
        insert_capture(
            self.conn,
            raw_text="Drop off the mail on the way home.",
            domains=["Home"],
        )
        robert_capture = insert_capture(
            self.conn,
            raw_text="Need to pay Robert back for concert tickets.",
            domains=["Social"],
        )
        self.conn.execute(
            "UPDATE captures SET created_at = datetime('now', '-45 days') WHERE id = ?",
            (robert_capture.id,),
        )

        robert_thread_id = create_thread(
            self.conn,
            title="Pay Robert back",
            kind="obligation",
            summary="Settle the concert ticket reimbursement.",
            domains=["Social"],
            evidence_ids=[robert_capture.id],
            salience=0.6,
        )
        self.conn.execute(
            "UPDATE threads SET last_seen_at = datetime('now', '-45 days') WHERE id = ?",
            (robert_thread_id,),
        )
        self.conn.commit()

        packet = build_context_packet(self.conn, "What do I owe Bob?", days=30)

        self.assertEqual(packet["query_terms"], ["owe", "bob"])
        self.assertFalse(packet["used_recent_fallback"])
        self.assertEqual(packet["relevant_captures"][0]["id"], robert_capture.id)
        self.assertEqual(packet["relevant_captures"][0]["matched_terms"], ["bob"])
        self.assertEqual(
            packet["relevant_captures"][0]["ranking_reason"],
            {
                "matched_term_count": 1,
                "direct_match_count": 1,
                "thread_support_count": 0,
                "matched_terms": ["bob"],
                "expanded_matches": ["bob->robert"],
            },
        )

        self.assertEqual(packet["threads"][0]["id"], robert_thread_id)
        self.assertEqual(packet["threads"][0]["matched_terms"], ["bob"])
        self.assertEqual(
            packet["threads"][0]["ranking_reason"],
            {
                "matched_term_count": 1,
                "surface_match_count": 1,
                "state_match_count": 0,
                "evidence_match_count": 1,
                "matched_terms": ["bob"],
                "expanded_matches": ["bob->robert"],
            },
        )
        self.assertEqual(
            packet["threads"][0]["citations"][0]["expanded_matches"],
            ["bob->robert"],
        )

        rendered = render_context_packet(packet)
        self.assertIn("expanded=bob->robert", rendered)
        self.assertIn("| matched: bob | expanded: bob->robert", rendered)

    def test_context_packet_matches_synonyms_with_expanded_ranking_reason(self) -> None:
        insert_capture(
            self.conn,
            raw_text="Replace the kitchen light bulb.",
            domains=["Home"],
        )
        doctor_capture = insert_capture(
            self.conn,
            raw_text="Need to schedule a doctor appointment before June.",
            domains=["Body"],
        )
        self.conn.execute(
            "UPDATE captures SET created_at = datetime('now', '-45 days') WHERE id = ?",
            (doctor_capture.id,),
        )

        doctor_thread_id = create_thread(
            self.conn,
            title="Schedule doctor appointment",
            kind="obligation",
            summary="Book the annual doctor visit.",
            domains=["Body"],
            evidence_ids=[doctor_capture.id],
            salience=0.7,
        )
        self.conn.execute(
            "UPDATE threads SET last_seen_at = datetime('now', '-45 days') WHERE id = ?",
            (doctor_thread_id,),
        )
        self.conn.commit()

        packet = build_context_packet(self.conn, "What about my physician checkup?", days=30)

        self.assertEqual(packet["query_terms"], ["physician", "checkup"])
        self.assertFalse(packet["used_recent_fallback"])
        self.assertEqual(packet["relevant_captures"][0]["id"], doctor_capture.id)
        self.assertEqual(packet["relevant_captures"][0]["matched_terms"], ["physician", "checkup"])
        self.assertEqual(
            packet["relevant_captures"][0]["ranking_reason"],
            {
                "matched_term_count": 2,
                "direct_match_count": 2,
                "thread_support_count": 0,
                "matched_terms": ["physician", "checkup"],
                "expanded_matches": ["physician->doctor", "checkup->appointment"],
            },
        )

        self.assertEqual(packet["threads"][0]["id"], doctor_thread_id)
        self.assertEqual(packet["threads"][0]["matched_terms"], ["physician", "checkup"])
        self.assertEqual(
            packet["threads"][0]["ranking_reason"],
            {
                "matched_term_count": 2,
                "surface_match_count": 2,
                "state_match_count": 0,
                "evidence_match_count": 2,
                "matched_terms": ["physician", "checkup"],
                "expanded_matches": ["physician->doctor", "checkup->appointment"],
            },
        )
        self.assertEqual(
            packet["threads"][0]["citations"][0]["expanded_matches"],
            ["physician->doctor", "checkup->appointment"],
        )

        rendered = render_context_packet(packet)
        self.assertIn("expanded=physician->doctor, checkup->appointment", rendered)
        self.assertIn(
            "| matched: physician, checkup | expanded: physician->doctor, checkup->appointment",
            rendered,
        )

    def test_context_packet_matches_paraphrases_with_expanded_ranking_reason(self) -> None:
        insert_capture(
            self.conn,
            raw_text="Need to buy groceries after work.",
            domains=["Home"],
        )
        vehicle_capture = insert_capture(
            self.conn,
            raw_text="Need to renew vehicle registration before July.",
            domains=["Home"],
        )
        self.conn.execute(
            "UPDATE captures SET created_at = datetime('now', '-45 days') WHERE id = ?",
            (vehicle_capture.id,),
        )

        vehicle_thread_id = create_thread(
            self.conn,
            title="Renew vehicle registration",
            kind="obligation",
            summary="Handle the registration renewal paperwork.",
            domains=["Home"],
            evidence_ids=[vehicle_capture.id],
            salience=0.8,
        )
        self.conn.execute(
            "UPDATE threads SET last_seen_at = datetime('now', '-45 days') WHERE id = ?",
            (vehicle_thread_id,),
        )
        self.conn.commit()

        packet = build_context_packet(self.conn, "What about my car papers?", days=30)

        self.assertEqual(packet["query_terms"], ["car", "paper"])
        self.assertFalse(packet["used_recent_fallback"])
        self.assertEqual(packet["relevant_captures"][0]["id"], vehicle_capture.id)
        self.assertEqual(packet["relevant_captures"][0]["matched_terms"], ["car", "paper"])
        self.assertEqual(
            packet["relevant_captures"][0]["ranking_reason"],
            {
                "matched_term_count": 2,
                "direct_match_count": 2,
                "thread_support_count": 0,
                "matched_terms": ["car", "paper"],
                "expanded_matches": ["car->vehicle", "paper->registration"],
            },
        )

        self.assertEqual(packet["threads"][0]["id"], vehicle_thread_id)
        self.assertEqual(packet["threads"][0]["matched_terms"], ["car", "paper"])
        self.assertEqual(
            packet["threads"][0]["ranking_reason"],
            {
                "matched_term_count": 2,
                "surface_match_count": 2,
                "state_match_count": 0,
                "evidence_match_count": 2,
                "matched_terms": ["car", "paper"],
                "expanded_matches": ["car->vehicle", "paper->registration"],
            },
        )
        self.assertEqual(
            packet["threads"][0]["citations"][0]["expanded_matches"],
            ["car->vehicle", "paper->registration"],
        )

        rendered = render_context_packet(packet)
        self.assertIn("expanded=car->vehicle, paper->registration", rendered)
        self.assertIn(
            "| matched: car, paper | expanded: car->vehicle, paper->registration",
            rendered,
        )


if __name__ == "__main__":
    unittest.main()
