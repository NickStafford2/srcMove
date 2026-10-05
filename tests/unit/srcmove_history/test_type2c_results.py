"""Current and legacy names for srcMove's consistent renaming category."""
import unittest

from srcmove_history.presentation import render_status
from srcmove_history.results import normalize_compactable_results


class Type2cResultsTests(unittest.TestCase):
    def test_admission_preserves_current_and_legacy_labels(self):
        for kind in ('type2', 'type2c'):
            with self.subTest(kind=kind):
                move = dict(match_kind=kind, from_xpaths=['/old'], to_xpaths=['/new'],
                            from_raw_texts=['int a;'], to_raw_texts=['int b;'])
                payload = dict(results_schema_version=1, move_count=1,
                               move_group_count=1, move_pair_count=1,
                               annotated_region_count=2, moves=[move],
                               group_kinds={'move_1_to_1': 1}, match_kinds={kind: 1})
                moves, counts = normalize_compactable_results(payload)
                self.assertEqual(moves[0]['match_kind'], kind)
                self.assertEqual(counts['match_kinds'], {kind: 1})

    def test_blind_matching_category_is_not_admitted(self):
        payload = dict(results_schema_version=1, move_count=1, move_group_count=1,
                       move_pair_count=1, annotated_region_count=2,
                       moves=[dict(match_kind='type2b')])
        with self.assertRaisesRegex(ValueError, 'invalid match kind'):
            normalize_compactable_results(payload)

    def test_text_combines_old_and_new_category_counts(self):
        text = render_status(dict(move_group_count=3, match_kinds={'type2': 1, 'type2c': 2}))
        self.assertIn('3 Type 2c', text)
        self.assertNotIn('1 type2', text)
