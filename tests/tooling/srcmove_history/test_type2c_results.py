"""Admission checks for the current content-classification reporting contract."""
import copy
import unittest

from srcmove_history.presentation import render_status
from srcmove_history.results import normalize_compactable_results
from benchmarking.results import validate_results_schema
from tests.tooling.results_fixtures import schema3_fixture


class Type2cResultsTests(unittest.TestCase):
    def payload(self):
        move = dict(move_id='move-1', content_relationship='type2c',
                    from_xpaths=['/old'], to_xpaths=['/new'],
                    from_raw_texts=['int a;'], to_raw_texts=['int b;'])
        return schema3_fixture(dict(results_schema_version=3, move_count=1, move_group_count=1,
                    move_pair_count=1, annotated_region_count=2, moves=[move],
                    group_kinds={'move_1_to_1': 1}, content_relationships={'type2c': 1}))

    def test_admission_and_scorer_accept_current_classification(self):
        payload = self.payload()
        moves, counts = normalize_compactable_results(payload)
        self.assertEqual(moves[0]['content_relationship'], 'type2c')
        self.assertEqual(counts['content_relationships'], {'type1': 0, 'type2c': 1, 'type3': 0})
        self.assertEqual(validate_results_schema(payload), [])

    def test_incompatible_reporting_and_counts_are_rejected(self):
        baseline = self.payload()
        mutations = [
            lambda p: p.update(results_schema_version=1),
            lambda p: p['summary'].update(atomic_move_group_count=2),
            lambda p: p.update(match_kinds={'type2c': 1}),
            lambda p: p['atomic_move_groups'][0].update(match_kind='type2c'),
            lambda p: p['atomic_move_groups'][0].update(content_relationship='type2'),
            lambda p: p['atomic_move_groups'][0].update(content_relationship='type2b'),
            lambda p: p['summary'].update(atomic_content_relationships={'type2': 1}),
            lambda p: p['summary']['atomic_content_relationships'].update(type2c=0),
        ]
        for mutation in mutations:
            payload = copy.deepcopy(baseline)
            mutation(payload)
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    normalize_compactable_results(payload)
                self.assertTrue(validate_results_schema(payload))

    def test_text_presents_current_category_counts(self):
        text = render_status(dict(move_group_count=3, content_relationships={'type2c': 3}))
        self.assertIn('3 Type 2c', text)
