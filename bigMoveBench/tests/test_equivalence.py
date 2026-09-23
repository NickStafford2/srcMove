from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from bigMoveBench.equivalence import compare_case_csv


FIELDS = (
    "case_id",
    "outcome",
    "case_kind",
    "syntactic_type",
    "expected_match_kind",
    "observed_match_kind",
    "move_count",
    "semantic_reason",
    "type3_strength_stratum",
    "from_text_validation",
    "to_text_validation",
    "attempt_id",
    "input_sha256",
)


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


class EquivalenceTests(unittest.TestCase):
    def test_compares_scientific_fields_and_ignores_execution_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            left = root / "left.csv"
            right = root / "right.csv"
            row = {
                "case_id": "case-1",
                "outcome": "oracle_pass",
                "case_kind": "positive",
                "syntactic_type": "1",
                "expected_match_kind": "exact",
                "observed_match_kind": "exact",
                "move_count": "1",
                "semantic_reason": "payload_exposed",
                "type3_strength_stratum": "",
                "from_text_validation": "strict",
                "to_text_validation": "strict",
                "attempt_id": "attempt-one",
                "input_sha256": "a" * 64,
            }
            write_csv(left, [row])
            write_csv(
                right,
                [row | {"attempt_id": "attempt-two", "input_sha256": "b" * 64}],
            )
            comparison = compare_case_csv(left, right)
            self.assertTrue(comparison["equivalent"])
            self.assertEqual(comparison["differences"], [])

    def test_reports_missing_cases_and_field_differences(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            left = root / "left.csv"
            right = root / "right.csv"
            write_csv(
                left,
                [
                    {"case_id": "case-1", "outcome": "oracle_pass"},
                    {"case_id": "case-2", "outcome": "srcmove_miss"},
                ],
            )
            write_csv(
                right,
                [{"case_id": "case-1", "outcome": "srcmove_miss"}],
            )
            comparison = compare_case_csv(left, right)
            self.assertFalse(comparison["equivalent"])
            self.assertEqual(comparison["missing_case_ids"], ["case-2"])
            self.assertEqual(
                comparison["differences"],
                [
                    {
                        "case_id": "case-1",
                        "field": "outcome",
                        "snapshot": "oracle_pass",
                        "normalized": "srcmove_miss",
                    }
                ],
            )


if __name__ == "__main__":
    unittest.main()
