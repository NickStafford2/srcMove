"""Blind identifier equality observes extra evidence without selecting moves."""
from __future__ import annotations
from tests.support.execution import require_success, require_tool

import json
from tests.support.execution import artifact_directory, run_logged
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
        with artifact_directory(case_id=self.id()) as directory:
            work = Path(directory)
            source = work / 'input.xml'
            source.write_text(text)
            payloads, annotations, profiles = [], [], []
            for diagnostics, results_only in ((False, False), (True, False), (True, True)):
                output, annotation = work / 'results.json', work / 'output.xml'
                command = [str(binary), str(source)]
                if not results_only:
                    command.append(str(annotation))
                command += ['--results', str(output), '--profile']
                if diagnostics:
                    command.append('--diagnostics')
                if results_only:
                    command.append('--results-only')
                process = run_logged(command, capture_output=True, text=True)
                require_success(process)
                payloads.append(json.loads(output.read_text()))
                profiles.append(process.stderr)
                if not results_only:
                    annotations.append(annotation.read_bytes())
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
        diagnostics = self.run_modes(FIXTURE.read_text())
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
        text = FIXTURE.read_text()
        with self.subTest(kind='consistent'):
            self.assertEqual(self.run_modes(text.replace('<name>c</name></expr>', '<name>b</name></expr>'))['type2b_groups'], [])
        tree = ET.fromstring(text)
        deleted = tree.find('.//' + DIFF + 'delete/' + SRC + 'function')
        inserted = tree.find('.//' + DIFF + 'insert')
        inserted.clear()
        inserted.append(ET.fromstring(ET.tostring(deleted)))
        with self.subTest(kind='exact'):
            self.assertEqual(self.run_modes(ET.tostring(tree, encoding='unicode'))['type2b_groups'], [])

    def test_repeated_and_mixed_groups_do_not_claim_pairing(self):
        text = FIXTURE.read_text()
        tree = ET.fromstring(text)
        inserted = tree.find('.//' + DIFF + 'insert')
        inserted.append(ET.fromstring(ET.tostring(inserted[0])))
        for mixed in (False, True):
            with self.subTest(mixed=mixed):
                if mixed:
                    # One partner is consistent; the other remains blind-only.
                    names = inserted[1].find('.//' + SRC + 'return').findall('.//' + SRC + 'name')
                    names[-1].text = 'b'
                groups = self.run_modes(ET.tostring(tree, encoding='unicode'))['type2b_groups']
                self.assertEqual(len(groups), 1)
                self.assertEqual(groups[0]['cardinality'], 'ambiguous')
                self.assertEqual(len(groups[0]['delete_candidate_ids']), 1)
                self.assertEqual(len(groups[0]['insert_candidate_ids']), 2)
                self.assertEqual(groups[0]['blind_only_pair_count'], 1 if mixed else 2)
                self.assertNotIn('location_change', groups[0])

    def test_repeated_deletions_remain_ambiguous(self):
        tree = ET.fromstring(FIXTURE.read_text())
        deleted = tree.find('.//' + DIFF + 'delete')
        deleted.append(ET.fromstring(ET.tostring(deleted[0])))
        group = self.run_modes(ET.tostring(tree, encoding='unicode'))['type2b_groups'][0]
        self.assertEqual(group['cardinality'], 'ambiguous')
        self.assertEqual(len(group['delete_candidate_ids']), 2)
        self.assertEqual(len(group['insert_candidate_ids']), 1)
        self.assertEqual(group['blind_only_pair_count'], 2)

    def test_literal_categories_are_preserved(self):
        text = FIXTURE.read_text()
        text = text.replace('<name>a</name> <operator>+</operator> <name>a</name>',
                            '<name>z</name> <operator>+</operator> <literal type="number">42</literal>')
        text = text.replace('<name>b</name> <operator>+</operator> <name>c</name>',
                            '<name>b</name> <operator>+</operator> <literal type="number">7</literal>')
        self.assertEqual(self.run_modes(text)['type2b_groups'][0]['blind_only_pair_count'], 1)
        for literal in ('<literal type="string">"7"</literal>',
                        '<literal type="number">7.0</literal>'):
            with self.subTest(literal=literal):
                altered = text.replace('<literal type="number">7</literal>', literal)
                self.assertEqual(self.run_modes(altered)['type2b_groups'], [])

    def test_blind_equality_retains_operators_and_empty_statements(self):
        tree = ET.fromstring(FIXTURE.read_text())
        operator = tree.find('.//' + DIFF + 'insert//' + SRC + 'operator')
        operator.text = '-'
        self.assertEqual(self.run_modes(ET.tostring(tree, encoding='unicode'))['type2b_groups'], [])
        text = FIXTURE.read_text().replace('<return>return <expr><name>b</name>', '<empty_stmt>;</empty_stmt><return>return <expr><name>b</name>')
        self.assertEqual(self.run_modes(text)['type2b_groups'], [])


if __name__ == '__main__':
    unittest.main()
