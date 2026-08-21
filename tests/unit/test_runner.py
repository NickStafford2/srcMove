from __future__ import annotations

import io
import unittest
import sys
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

TESTS_ROOT = Path(__file__).resolve().parents[1]
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

import run
from support.cases import regression_case_names


class TestInventoryTests(unittest.TestCase):
    def test_expected_regression_cases_are_discoverable(self) -> None:
        self.assertIn("1x1_basic", regression_case_names("xml"))
        self.assertIn("blocks_swapped", regression_case_names("source"))
        self.assertIn(
            "direct_numeric_literal", regression_case_names("policy")
        )

    def test_case_selection_routes_to_owning_suite(self) -> None:
        selected = run.select_regression_cases(
            ["xml", "source", "policy"],
            ["1x1_basic", "blocks_swapped", "direct_numeric_literal"],
        )

        self.assertEqual(selected["xml"], ["1x1_basic"])
        self.assertEqual(selected["source"], ["blocks_swapped"])
        self.assertEqual(selected["policy"], ["direct_numeric_literal"])

    def test_unknown_case_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "case not found"):
            run.select_regression_cases(["xml", "source"], ["does-not-exist"])

    def test_inventory_lists_focused_non_regression_suite(self) -> None:
        output = io.StringIO()

        with redirect_stdout(output):
            run.print_inventory()

        self.assertIn(
            "repository-analysis: focused repository-analysis unit tests",
            output.getvalue(),
        )

    def test_repository_analysis_suite_uses_nested_test_directory(self) -> None:
        steps = run.test_steps(
            SimpleNamespace(cases=None),
            ["repository-analysis"],
            {},
            None,
            None,
        )

        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0].name, "repository-analysis unit")
        self.assertEqual(
            steps[0].command[-6:],
            [
                "-s",
                "tests/unit/repository_analysis",
                "-t",
                ".",
                "-p",
                "test_*.py",
            ],
        )


if __name__ == "__main__":
    unittest.main()
