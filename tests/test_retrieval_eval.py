from __future__ import annotations

import argparse
import contextlib
import io
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mneme.cli import handle_eval_retrieval  # noqa: E402
from mneme.retrieval_eval import (  # noqa: E402
    built_in_retrieval_eval_cases,
    run_retrieval_eval_cases,
)


class RetrievalEvalTests(unittest.TestCase):
    def test_built_in_retrieval_eval_cases_pass(self) -> None:
        results = run_retrieval_eval_cases()

        self.assertEqual(len(results), len(built_in_retrieval_eval_cases()))
        self.assertTrue(all(result.passed for result in results))

    def test_handle_eval_retrieval_renders_summary(self) -> None:
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout):
            result = handle_eval_retrieval(argparse.Namespace())

        rendered = stdout.getvalue()

        self.assertEqual(result, 0)
        self.assertIn("retrieval_eval_cases: 4", rendered)
        self.assertIn("passed: 4", rendered)
        self.assertIn("failed: 0", rendered)
        self.assertIn("- tax_receipts_direct_match: ok", rendered)
        self.assertIn("- blocked_now_thread_support: ok", rendered)
        self.assertIn("- recent_fallback_no_match: ok", rendered)
        self.assertIn("- unsupported_ai_citation: ok", rendered)


if __name__ == "__main__":
    unittest.main()
