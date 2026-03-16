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
        case_names = [case.name for case in built_in_retrieval_eval_cases()]

        self.assertIn(f"retrieval_eval_cases: {len(case_names)}", rendered)
        self.assertIn(f"passed: {len(case_names)}", rendered)
        self.assertIn("failed: 0", rendered)
        for case_name in case_names:
            self.assertIn(f"- {case_name}: ok", rendered)
        self.assertNotIn("known gap: paraphrase", rendered)
        self.assertNotIn("known gap: synonym", rendered)
        self.assertNotIn("known gap: alias", rendered)
        self.assertNotIn("known gap: cross-domain", rendered)


if __name__ == "__main__":
    unittest.main()
