"""Blind identifier equality observes extra evidence without selecting moves."""
from __future__ import annotations
from tests.support.execution import require_success, require_tool

import json
from tests.support.execution import artifact_directory, run_logged
from tests.support.execution import execute_xml
from tests.support.readable_cases import case_xml
import unittest
from pathlib import Path
import xml.etree.ElementTree as ET

from benchmarking.tooling import find_srcmove

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / 'tests/fixtures/selection/type2b_cases/inconsistent_rename.xml'
SRC = '{http://www.srcML.org/srcML/src}'
DIFF = '{http://www.srcML.org/srcDiff}'
ET.register_namespace('', SRC[1:-1])
ET.register_namespace('diff', DIFF[1:-1])


class Type2bDiagnosticTests(unittest.TestCase):
    def run_modes(self, text):
        binary = find_srcmove(ROOT, None)
        observation = execute_xml(text, case_id=self.id(), binary=binary, extra_args=('--profile',))
        payloads = [mode.payload() for mode in observation.modes]
        annotations = [mode.output_xml.read_bytes() for mode in observation.modes if mode.output_xml is not None]
        profiles = [mode.completed.stderr for mode in observation.modes]
        ordinary = dict(payloads[1])
        ordinary.pop('diagnostics')
        self.assertEqual(payloads[0], ordinary)
        self.assertEqual(payloads[1], payloads[2])
        self.assertEqual(annotations[0], annotations[1])
        self.assertNotIn('diagnostics', payloads[0])
        self.assertNotIn('content_groups.type2b_', profiles[0])
        self.assertIn('content_groups.type2b_diagnostics_ms=', profiles[1])
        self.assertTrue(all(m['content_relationship'] != 'type2b' for m in ordinary['moves']))
        self.assertNotIn('type2b', ordinary['content_relationships'])
        return payloads[1]['diagnostics']

    def test_unique_inconsistent_rename_is_observation_only(self):
        """An inconsistent rename supplies location evidence but cannot become a production move."""
        diagnostics = self.run_modes(case_xml('type2b_diagnostics/inconsistent_rename'))
        self.assertEqual(len(diagnostics['type2b_groups']), 1)
        group = diagnostics['type2b_groups'][0]
        self.assertEqual(group['correspondence_kind'], 'type2b')
        self.assertIs(group['observation_only'], True)
        self.assertEqual(group['cardinality'], 'one_to_one')
        self.assertEqual(group['blind_only_pair_count'], 1)
        self.assertEqual(group['location_change'], 'relocated')
        self.assertEqual(group['location_reason'], 'different_file')
        candidates = {c['candidate_id']: c for c in diagnostics['candidates']}
        self.assertEqual(candidates[group['delete_candidate_ids'][0]]['construct'], 'function')
        self.assertIn('a + a', candidates[group['delete_candidate_ids'][0]]['raw_text'])
        self.assertIn('b + c', candidates[group['insert_candidate_ids'][0]]['raw_text'])

    def test_consistent_and_exact_pairs_add_no_blind_only_group(self):
        """Consistent renames and exact copies add no extra blind-only evidence group."""
        with self.subTest(kind='consistent'):
            self.assertEqual(self.run_modes(case_xml('type2b_diagnostics/consistent_rename'))['type2b_groups'], [])
        with self.subTest(kind='exact'):
            self.assertEqual(self.run_modes(case_xml('type2b_diagnostics/exact_pair'))['type2b_groups'], [])

    def test_repeated_and_mixed_groups_do_not_claim_pairing(self):
        """Repeated destinations remain ambiguous, even when one is a consistent rename."""
        for mixed in (False, True):
            with self.subTest(mixed=mixed):
                name = 'one_consistent_one_blind_destination' if mixed else 'two_blind_destinations'
                groups = self.run_modes(case_xml('type2b_diagnostics/' + name))['type2b_groups']
                self.assertEqual(len(groups), 1)
                self.assertEqual(groups[0]['cardinality'], 'ambiguous')
                self.assertEqual(len(groups[0]['delete_candidate_ids']), 1)
                self.assertEqual(len(groups[0]['insert_candidate_ids']), 2)
                self.assertEqual(groups[0]['blind_only_pair_count'], 1 if mixed else 2)
                self.assertNotIn('location_change', groups[0])

    def test_repeated_deletions_remain_ambiguous(self):
        """Two identical origins and one renamed destination must not acquire an arbitrary pairing."""
        group = self.run_modes(case_xml('type2b_diagnostics/two_origins'))['type2b_groups'][0]
        self.assertEqual(group['cardinality'], 'ambiguous')
        self.assertEqual(len(group['delete_candidate_ids']), 2)
        self.assertEqual(len(group['insert_candidate_ids']), 1)
        self.assertEqual(group['blind_only_pair_count'], 2)

    def test_literal_categories_are_preserved(self):
        """Integer changes can match blindly; changing literal category must prevent that match."""
        text = case_xml('type2b_diagnostics/number_literals')
        self.assertEqual(self.run_modes(text)['type2b_groups'][0]['blind_only_pair_count'], 1)
        for literal in ('<literal type="string">"7"</literal>',
                        '<literal type="number">7.0</literal>'):
            with self.subTest(literal=literal):
                name = 'string_literal' if 'type="string"' in literal else 'floating_literal'
                altered = case_xml('type2b_diagnostics/' + name)
                self.assertEqual(self.run_modes(altered)['type2b_groups'], [])

    def test_blind_equality_retains_operators_and_empty_statements(self):
        """A changed operator or an added empty statement breaks blind-only equality."""
        self.assertEqual(self.run_modes(case_xml('type2b_diagnostics/changed_operator'))['type2b_groups'], [])
        text = case_xml('type2b_diagnostics/added_empty_statement')
        self.assertEqual(self.run_modes(text)['type2b_groups'], [])


if __name__ == '__main__':
    unittest.main()
