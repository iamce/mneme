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
        self.assertEqual(link_count, 8)

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

    def test_domain_group_is_split_into_distinct_clusters(self) -> None:
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
        insert_capture(
            self.conn,
            raw_text="Car insurance renewal is due tomorrow.",
            domains=["Money"],
        )
        insert_capture(
            self.conn,
            raw_text="Still need the insurance card for the renewal paperwork.",
            domains=["Money"],
        )

        preview = consolidate_recent_captures(self.conn, days=30, limit=10, dry_run=True)

        self.assertEqual(preview["candidate_count"], 2)
        titles = {candidate["title"] for candidate in preview["candidates"]}
        self.assertEqual(titles, {"Money: taxes and receipts", "Money: insurance and renewal"})

        applied = consolidate_recent_captures(self.conn, days=30, limit=10)
        self.assertEqual(applied["created_thread_count"], 2)
        thread_count = self.conn.execute("SELECT COUNT(*) AS count FROM threads").fetchone()["count"]
        self.assertEqual(thread_count, 2)

    def test_low_overlap_singleton_is_skipped_instead_of_forcing_domain_candidate(self) -> None:
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

        preview = consolidate_recent_captures(self.conn, days=30, limit=10, dry_run=True)

        self.assertEqual(preview["candidate_count"], 1)
        self.assertIn(
            {
                "domain": "Money",
                "capture_ids": [leftover.id],
                "reason": "low_overlap",
            },
            preview["skipped"],
        )

    def test_generic_urgent_capture_without_topic_terms_is_skipped_as_ambiguous(self) -> None:
        capture = insert_capture(
            self.conn,
            raw_text="Need to pay this today.",
            domains=["Money"],
        )

        preview = consolidate_recent_captures(self.conn, days=30, limit=10, dry_run=True)

        self.assertEqual(preview["candidate_count"], 0)
        self.assertEqual(
            preview["skipped"],
            [
                {
                    "domain": "Money",
                    "capture_ids": [capture.id],
                    "reason": "ambiguous_topic",
                }
            ],
        )

    def test_apply_without_candidates_returns_zero_counts(self) -> None:
        result = consolidate_recent_captures(self.conn, days=30, limit=10)

        self.assertFalse(result["dry_run"])
        self.assertEqual(result["created_thread_count"], 0)
        self.assertEqual(result["updated_thread_count"], 0)
        self.assertEqual(result["state_count"], 0)
        self.assertEqual(result["consolidated"], [])
        self.assertNotIn("artifact_id", result)

    def test_existing_overlap_is_inspected_and_merged_before_matching_new_capture(self) -> None:
        overdue = insert_capture(
            self.conn,
            raw_text="Taxes are overdue and the filing is still blocked.",
            domains=["Money"],
        )
        receipts = insert_capture(
            self.conn,
            raw_text="Still missing a few tax receipts for the filing.",
            domains=["Money"],
        )
        backlog = insert_capture(
            self.conn,
            raw_text="Tax filing is stuck until I sort the receipts.",
            domains=["Money"],
        )

        canonical_thread_id = create_thread(
            self.conn,
            title="Money: taxes and receipts",
            kind="obligation",
            summary="Tax filing remains overdue and several receipts are still missing.",
            domains=["Money"],
            evidence_ids=[overdue.id, receipts.id],
            salience=0.8,
            confidence=0.8,
        )
        record_thread_state(
            self.conn,
            thread_id=canonical_thread_id,
            attention="active",
            pressure="high",
            posture="blocked",
            momentum="drifting",
            affect="draining",
            horizon="now",
            confidence=0.8,
            evidence_ids=[overdue.id],
        )

        duplicate_thread_id = create_thread(
            self.conn,
            title="Money: tax filing and receipts",
            kind="obligation",
            summary="Need to finish the tax filing and organize the receipts.",
            domains=["Money"],
            evidence_ids=[backlog.id],
            salience=0.6,
            confidence=0.7,
        )
        record_thread_state(
            self.conn,
            thread_id=duplicate_thread_id,
            attention="background",
            pressure="medium",
            posture="waiting",
            momentum="stable",
            affect="neutral",
            horizon="soon",
            confidence=0.7,
            evidence_ids=[backlog.id],
        )

        follow_up = insert_capture(
            self.conn,
            raw_text="Finished the tax filing and submitted the receipts.",
            domains=["Money"],
        )

        preview = consolidate_recent_captures(self.conn, days=30, limit=10, dry_run=True)

        self.assertEqual(preview["thread_merge_count"], 1)
        self.assertEqual(preview["candidate_count"], 1)
        merge = preview["thread_merges"][0]
        self.assertEqual(merge["canonical_thread_id"], canonical_thread_id)
        self.assertEqual(merge["duplicate_thread_id"], duplicate_thread_id)
        self.assertEqual(merge["reason"], "high_overlap")
        self.assertIn("tax", merge["shared_terms"])
        self.assertEqual(preview["candidates"][0]["matched_thread_id"], canonical_thread_id)

        applied = consolidate_recent_captures(self.conn, days=30, limit=10)

        self.assertEqual(applied["merged_thread_count"], 1)
        self.assertEqual(applied["created_thread_count"], 0)
        self.assertEqual(applied["updated_thread_count"], 1)
        self.assertIn("Existing thread merges: 1", applied["summary"])
        self.assertIn("Thread merges:", applied["summary"])

        thread_count = self.conn.execute("SELECT COUNT(*) AS count FROM threads").fetchone()["count"]
        self.assertEqual(thread_count, 1)

        duplicate_exists = self.conn.execute(
            "SELECT 1 FROM threads WHERE id = ?",
            (duplicate_thread_id,),
        ).fetchone()
        self.assertIsNone(duplicate_exists)

        bundle = get_thread_bundle(self.conn, canonical_thread_id)
        self.assertEqual(len(bundle["state_history"]), 3)
        evidence_capture_ids = {row["capture_id"] for row in bundle["thread_evidence"]}
        self.assertIn(backlog.id, evidence_capture_ids)
        self.assertIn(follow_up.id, evidence_capture_ids)
        self.assertTrue(
            any(artifact["content"].get("action") == "merge_thread" for artifact in bundle["artifacts"])
        )

    def test_existing_threads_with_distinct_topics_are_not_merged(self) -> None:
        tax_capture = insert_capture(
            self.conn,
            raw_text="Taxes are overdue and I still need receipts.",
            domains=["Money"],
        )
        insurance_capture = insert_capture(
            self.conn,
            raw_text="Car insurance renewal is due next week.",
            domains=["Money"],
        )

        create_thread(
            self.conn,
            title="Money: taxes and receipts",
            kind="obligation",
            summary="Tax filing remains overdue and receipts are missing.",
            domains=["Money"],
            evidence_ids=[tax_capture.id],
        )
        create_thread(
            self.conn,
            title="Money: insurance and renewal",
            kind="obligation",
            summary="Insurance renewal paperwork is due next week.",
            domains=["Money"],
            evidence_ids=[insurance_capture.id],
        )

        preview = consolidate_recent_captures(self.conn, days=30, limit=10, dry_run=True)

        self.assertEqual(preview["thread_merge_count"], 0)
        self.assertEqual(preview["thread_merges"], [])


if __name__ == "__main__":
    unittest.main()
