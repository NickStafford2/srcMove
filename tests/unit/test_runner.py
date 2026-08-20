from __future__ import annotations

import unittest
import sys
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parents[1]
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

import run
from support.cases import regression_case_names


class TestInventoryTests(unittest.TestCase):
    def test_expected_regression_cases_are_discoverable(self) -> None:
        self.assertIn("1x1_basic", regression_case_names("xml"))
        self.assertIn("blocks_swapped", regression_case_names("source"))

    def test_case_selection_routes_to_owning_suite(self) -> None:
        selected = run.select_regression_cases(
            ["xml", "source"], ["1x1_basic", "blocks_swapped"]
        )

        self.assertEqual(selected["xml"], ["1x1_basic"])
        self.assertEqual(selected["source"], ["blocks_swapped"])

    def test_unknown_case_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "case not found"):
            run.select_regression_cases(["xml", "source"], ["does-not-exist"])


if __name__ == "__main__":
    unittest.main()
