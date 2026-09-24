from __future__ import annotations

import unittest

from tests.support.validation import check_summary_fields, validate_moves


def move(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "move_id": "m1",
        "match_kind": "type3",
        "confidence_milli": 825,
        "selection_utility": 12000,
        "matched_units": 14,
        "selection_reason": "greedy_utility",
        "from_xpaths": ["/from"],
        "to_xpaths": ["/to"],
        "from_raw_texts": ["old();"],
        "to_raw_texts": ["new();"],
    }
    value.update(overrides)
    return value


class ResultValidationTests(unittest.TestCase):
    def test_move_score_fields_are_compared_when_golden_declares_them(self) -> None:
        expected = {"moves": [move(selection_utility=11999)]}
        failures = validate_moves(expected, {"moves": [move()]})
        self.assertTrue(any("selection_utility mismatch" in item for item in failures))

    def test_actual_move_requires_well_formed_score_and_reason_fields(self) -> None:
        actual = move()
        del actual["confidence_milli"]
        actual["selection_reason"] = ""
        failures = validate_moves({"moves": [move()]}, {"moves": [actual]})
        self.assertTrue(any("confidence_milli" in item for item in failures))
        self.assertTrue(any("selection_reason" in item for item in failures))

    def test_type3_summary_count_is_required_and_compared(self) -> None:
        expected = {"match_kinds": {"exact": 0, "type2": 0, "type3": 1}}
        actual = {"match_kinds": {"exact": 0, "type2": 0}}
        failures = check_summary_fields(actual, expected)
        self.assertIn("results.json match_kinds missing required field 'type3'", failures)


if __name__ == "__main__":
    unittest.main()
