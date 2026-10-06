"""Independent location and competing-edge contracts for Type-3 observation."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from benchmarking.tooling import find_srcmove

SRC = '{http://www.srcML.org/srcML/src}'
DIFF = '{http://www.srcML.org/srcDiff}'
normalize = lambda text: ' '.join(text.split())


class Type3ContractTests(unittest.TestCase):
    def test_verified_edges_preserve_location_and_competition(self) -> None:
        catalog = json.loads((REPO_ROOT / 'moveSelectionBench/type3_contracts.json').read_text())
        self.assertEqual(len(catalog['cases']), 15)
        binary = find_srcmove(REPO_ROOT, None)
        self.assertIsNotNone(binary)
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            for case in catalog['cases']:
                with self.subTest(case=case['id']):
                    fixture = REPO_ROOT / 'moveSelectionBench' / case['fixture']
                    # Independently verify the exact reviewed constructs and revision membership.
                    endpoints = {'delete': [], 'insert': []}
                    def visit(node, side=None):
                        if node.tag in (DIFF+'delete', DIFF+'insert'):
                            side = node.tag.split('}')[1]
                        elif node.tag == DIFF+'common':
                            side = None
                        if side and node.tag == SRC+case['construct']:
                            endpoints[side].append(normalize(''.join(node.itertext())))
                        for child in node:
                            visit(child, side)
                    visit(ET.parse(fixture).getroot())
                    for edge in case['expected_edges']:
                        self.assertEqual(endpoints['delete'].count(edge['before_text']), 1)
                        self.assertEqual(endpoints['insert'].count(edge['after_text']), 1)
                    payloads, annotations = [], []
                    for mode in ('ordinary', 'diagnostic', 'results_only'):
                        output, xml = temp / f'{mode}.json', temp / f'{mode}.xml'
                        command = [str(binary), str(fixture), '--results', str(output)]
                        if mode != 'ordinary':
                            command.append('--diagnostics')
                        if mode == 'results_only':
                            command.append('--results-only')
                        else:
                            command.insert(2, str(xml))
                        result = subprocess.run(command, text=True, capture_output=True)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        payload = json.loads(output.read_text())
                        payloads.append(payload)
                        if mode != 'results_only':
                            annotations.append(xml.read_bytes())
                    self.assertEqual(annotations[0], annotations[1])
                    self.assertEqual(payloads[1], payloads[2])
                    observed = dict(payloads[1])
                    diagnostics = observed.pop('diagnostics')
                    self.assertEqual(observed, payloads[0])
                    self.assertEqual(diagnostics['schema_version'], 4)
                    candidates = {c['candidate_id']: c for c in diagnostics['candidates']}
                    records = diagnostics['correspondences']
                    ids = [(r['delete_candidate_id'], r['insert_candidate_id']) for r in records]
                    self.assertEqual(ids, sorted(set(ids)))
                    type3 = [r for r in records if r['correspondence_kind'] == 'type3']
                    verified = {(p['delete_candidate_id'], p['insert_candidate_id']) for p in diagnostics['type3_pairs']
                                if p['outcome'] in ('selected', 'selection_rejected')}
                    self.assertEqual({(r['delete_candidate_id'], r['insert_candidate_id']) for r in type3}, verified)
                    target = [r for r in type3 if candidates[r['delete_candidate_id']]['construct'] == case['construct']]
                    self.assertEqual(len(target), len(case['expected_edges']))
                    for edge in case['expected_edges']:
                        matched = [r for r in target
                                   if normalize(candidates[r['delete_candidate_id']]['raw_text']) == edge['before_text']
                                   and normalize(candidates[r['insert_candidate_id']]['raw_text']) == edge['after_text']]
                        self.assertEqual(len(matched), 1)
                        record = matched[0]
                        expected = edge
                        self.assertEqual(record['shadow_change'], expected['change'])
                        self.assertEqual(record['classification_reason'], expected['reason'])
                        self.assertEqual(record['delete_verified_partner_count'], edge['delete_partners'])
                        self.assertEqual(record['insert_verified_partner_count'], edge['insert_partners'])
                        competing = max(edge['delete_partners'], edge['insert_partners']) > 1
                        self.assertEqual(record['cardinality'], 'competing_edges' if competing else 'one_to_one')
                        if 'expected_current_result' in edge:
                            self.assertEqual(record['current_result'], edge['expected_current_result'])
                        if expected['change'] != 'relocated':
                            self.assertEqual(record['current_result'], 'not_move')
                        if edge.get('covered_by_type3_parent'):
                            deleted_path = candidates[record['delete_candidate_id']]['xpath']
                            inserted_path = candidates[record['insert_candidate_id']]['xpath']
                            self.assertTrue(any(m['content_relationship'] == 'type3'
                                                and deleted_path.startswith(m['from_xpaths'][0] + '/')
                                                and inserted_path.startswith(m['to_xpaths'][0] + '/')
                                                for m in observed['moves']))
                    for record in type3:
                        self.assertFalse(record['carried_by_parent'])
                        self.assertIsNone(record['parent_delete_candidate_id'])
                        self.assertIsNone(record['parent_insert_candidate_id'])
                        deleted = candidates[record['delete_candidate_id']]
                        inserted = candidates[record['insert_candidate_id']]
                        selected = any(m['content_relationship'] == 'type3' and m['from_xpaths'] == [deleted['xpath']]
                                       and m['to_xpaths'] == [inserted['xpath']] for m in observed['moves'])
                        self.assertEqual(record['current_result'], 'move' if selected else 'not_move')
                    if not case['expected_edges']:
                        self.assertTrue(any(p['outcome'] == 'below_threshold' for p in diagnostics['type3_pairs']))


if __name__ == '__main__':
    unittest.main()
