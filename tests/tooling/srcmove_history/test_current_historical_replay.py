"""Safety and scoring contracts for a new replay of sealed historical targets."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from moveSelectionBench.historical_study import current_replay as replay


class CurrentHistoricalReplayTests(unittest.TestCase):
    def test_requires_safe_local_dedicated_state(self):
        valid = '.srcmove-ch7-pass2-20261013-reviewed'
        self.assertEqual(replay.validate_state_name(valid), valid)
        for value in ('.srcmove', '.srcmove-historical-type12-20260927', '../' + valid,
                      valid + '/nested', valid + ';echo', ''):
            with self.subTest(value=value), self.assertRaises(ValueError):
                replay.validate_state_name(value)

    def test_existing_output_or_any_repository_state_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / 'new-output'
            state_name = '.srcmove-ch7-pass2-test'
            with patch.object(replay, 'ROOT', root):
                states = replay.fresh_paths(output, state_name, ['a', 'b'])
                states[1].mkdir(parents=True)
                marker = states[1] / 'prior-evidence'
                marker.write_text('preserve')
                with self.assertRaises(ValueError):
                    replay.fresh_paths(output, state_name, ['a', 'b'])
                self.assertEqual(marker.read_text(), 'preserve')
                output.mkdir()
                with self.assertRaises(ValueError):
                    replay.fresh_paths(output, state_name, ['a'])

    def test_identity_drift_is_rejected(self):
        expected = {'protocol_sha256': 'p', 'srcmove_sha256': 'm', 'srcdiff_sha256': 'd'}
        for field in expected:
            changed = {**expected, field: 'changed'}
            with self.subTest(field=field), patch.object(replay, 'identities', return_value=changed), self.assertRaises(ValueError):
                replay.verify_identities(expected, Path('m'), Path('d'), Path('p'))

    def test_recovery_and_current_content_classification_are_distinct(self):
        events = []
        for name, expected, actual, outcome, admitted in (
            ('correct', 'type2', ['type2c'], 'detected', True),
            ('wrong-content', 'type2', ['type1'], 'detected', True),
            ('missed', 'type1', [], 'needs_miss_review', True),
            ('unresolved-source', 'type2', ['type2c'], 'detected', False),
        ):
            events.append({'id': name, 'expected_type': expected, 'selected_types': actual,
                           'outcome': outcome, 'count_in_strict_recall': admitted,
                           'selected_indices': [0] if actual else []})
        summary = replay.classification_summary({'cases': [{'repository': 'a', 'id': 'pair', 'events': events}]})
        self.assertEqual(summary['counts'], {
            'admitted_targets': 3, 'source_label_not_admitted': 1,
            'exact_endpoint_recovered': 2, 'exact_endpoint_and_content_recovered': 1})
        self.assertEqual(summary['events'][0]['frozen_expected_type'], 'type2')
        self.assertEqual(summary['events'][0]['expected_current_content_relationship'], 'type2c')
        self.assertEqual(len(summary['events']), 3)

    def test_primary_sequence_does_not_manufacture_whole_endpoint_recovery(self):
        namespace = replay.study.NS['src']
        tree = ET.ElementTree(ET.fromstring(
            f'<unit xmlns="{namespace}"><unit filename="a.cpp"><expr_stmt>a();</expr_stmt>'
            '<expr_stmt>b();</expr_stmt></unit></unit>'))
        paths = [f'/src:unit[@filename="a.cpp"]/src:expr_stmt[{i}]' for i in (1, 2)]
        sequence = {'from_xpaths': paths, 'to_xpaths': paths}
        self.assertEqual(replay.study.match_event(tree, [sequence], ('a.cpp', 'a();b();'), ('a.cpp', 'a();b();')), [])
        atoms = [{'from_xpaths': [path], 'to_xpaths': [path]} for path in paths]
        self.assertEqual(replay.study.match_event(tree, atoms, ('a.cpp', 'a();'), ('a.cpp', 'a();')), [0])
        self.assertEqual(replay.study.match_event(tree, atoms, ('a.cpp', 'a();b();'), ('a.cpp', 'a();b();')), [])

    def test_sealed_inventory_has_exactly_106_distinct_comparisons(self):
        inventory = replay.sealed_cases()
        self.assertEqual(sum(map(len, inventory.values())), 106)


if __name__ == '__main__':
    unittest.main()
