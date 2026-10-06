from __future__ import annotations

import unittest

from tests.support.validation import check_summary_fields, validate_moves, xpaths_to_files


def move(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "move_id": "m1",
        "content_relationship": "type3",
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
        """Reject a selected move whose utility differs from the independently declared expected score."""
        expected = {"moves": [move(selection_utility=11999)]}
        failures = validate_moves(expected, {"moves": [move()]})
        self.assertTrue(any("selection_utility mismatch" in item for item in failures))

    def test_actual_move_requires_well_formed_score_and_reason_fields(self) -> None:
        """Reject a move missing confidence or carrying an empty selection reason."""
        actual = move()
        del actual["confidence_milli"]
        actual["selection_reason"] = ""
        failures = validate_moves({"moves": [move()]}, {"moves": [actual]})
        self.assertTrue(any("confidence_milli" in item for item in failures))
        self.assertTrue(any("selection_reason" in item for item in failures))

    def test_legacy_exact_content_relationship_is_rejected(self) -> None:
        """Reject the obsolete exact relationship value in place of the current Type-1 vocabulary."""
        failures = validate_moves(
            {"moves": [move()]}, {"moves": [move(content_relationship="exact")]}
        )
        self.assertTrue(any("content_relationship must be type1" in item for item in failures))

    def test_optional_identity_fields_are_compared_when_declared(self) -> None:
        """Check declared identity status and reason independently against the actual move."""
        expected = {"moves": [move(identity_status="tentative",
                                   identity_reason="uncorroborated_declaration")]}
        actual = {"moves": [move(identity_status="corroborated",
                                 identity_reason="continuing_name_corroborated")]}
        failures = validate_moves(expected, actual)
        self.assertTrue(any("identity_status mismatch" in item for item in failures))
        actual["moves"][0]["identity_status"] = "tentative"
        failures = validate_moves(expected, actual)
        self.assertTrue(any("identity_reason mismatch" in item for item in failures))

    def test_contradicted_identity_cannot_be_a_selected_move(self) -> None:
        """Reject a selected move carrying contradicted identity evidence."""
        failures = validate_moves({"moves": [move()]},
                                  {"moves": [move(identity_status="contradicted")]})
        self.assertTrue(any("identity_status is invalid" in item for item in failures))

    def test_endpoint_text_binding_cannot_be_swapped(self) -> None:
        """Reject swapped endpoint texts even when the endpoint paths remain unchanged."""
        expected = move(from_xpaths=["/a", "/b"],
                        from_raw_texts=["foo();", "foo( );"])
        actual = dict(expected, from_raw_texts=["foo( );", "foo();"])
        self.assertTrue(validate_moves({"moves": [expected]}, {"moves": [actual]}))

    def test_paired_endpoint_permutation_is_allowed(self) -> None:
        """Accept reordered endpoint pairs when each path remains bound to its original text."""
        expected = move(from_xpaths=["/b", "/a"], from_raw_texts=["b();", "a();"])
        actual = dict(expected, from_xpaths=["/a", "/b"], from_raw_texts=["a();", "b();"])
        self.assertEqual(validate_moves({"moves": [expected]}, {"moves": [actual]}), [])

    def test_duplicate_endpoint_multiplicity_is_preserved(self) -> None:
        """Reject collapsed duplicate endpoints while accepting their original multiplicity."""
        expected = move(from_xpaths=["/a", "/a"], from_raw_texts=["a();", "a();"])
        actual = move(from_xpaths=["/a"], from_raw_texts=["a();"])
        self.assertTrue(validate_moves({"moves": [expected]}, {"moves": [actual]}))
        self.assertEqual(validate_moves({"moves": [expected]}, {"moves": [expected]}), [])

    def test_duplicate_move_records_are_not_collapsed(self) -> None:
        """Require two expected move records to be satisfied by two actual records."""
        self.assertTrue(validate_moves({"moves": [move(), move()]}, {"moves": [move()]}))
        self.assertEqual(validate_moves({"moves": [move(), move()]},
                                        {"moves": [move(), move()]}), [])

    def test_both_actual_and_expected_length_mismatches_are_rejected(self) -> None:
        """Reject mismatched endpoint path and text counts in either actual or expected records."""
        malformed = move(from_raw_texts=[])
        for expected, actual in ((move(), malformed), (malformed, move())):
            with self.subTest(expected=expected):
                failures = validate_moves({"moves": [expected]}, {"moves": [actual]})
                self.assertTrue(any("endpoint lengths differ" in failure for failure in failures))

    def test_filename_predicates_support_both_quote_styles(self) -> None:
        """Extract unique filenames from XPath predicates using either single or double quotes."""
        self.assertEqual(xpaths_to_files(["/unit[@filename='a.cpp']/function",
                                         '/unit[@filename="b.cpp"]/function',
                                         "/unit[@filename='a.cpp']/function"]),
                         ["a.cpp", "b.cpp"])

    def test_type3_summary_count_is_required_and_compared(self) -> None:
        """Reject a result summary missing the independently expected Type-3 count."""
        expected = {"content_relationships": {"type1": 0, "type2c": 0, "type3": 1}}
        actual = {"content_relationships": {"type1": 0, "type2c": 0}}
        failures = check_summary_fields(actual, expected)
        self.assertIn("results.json content_relationships missing required field 'type3'", failures)


if __name__ == "__main__":
    unittest.main()
