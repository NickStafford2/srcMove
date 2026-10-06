"""Production Type-2 identity reservation and retained normalization evidence."""
from __future__ import annotations
from tests.support.execution import require_success, require_tool

import json
from pathlib import Path
import sys
from tests.support.execution import artifact_directory, run_logged
import unittest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarking.tooling import find_srcmove


class Type2AdoptionTests(unittest.TestCase):
    def run_fixture(self, fixture: Path) -> dict:
        binary = find_srcmove(REPO_ROOT, None)
        require_tool(binary)
        with artifact_directory(case_id=self.id()) as directory:
            output = Path(directory) / 'result.json'
            payloads = []
            for diagnostics in (False, True):
                command = [str(binary), str(fixture), '--results-only',
                           '--results', str(output)]
                if diagnostics:
                    command.append('--diagnostics')
                result = run_logged(command, capture_output=True, text=True)
                require_success(result)
                payloads.append(json.loads(output.read_text()))
            observed = dict(payloads[1])
            observed.pop('diagnostics')
            self.assertEqual(payloads[0], observed)
            return payloads[1]

    def test_unique_identity_reserves_both_endpoint_directions(self) -> None:
        fixtures = REPO_ROOT / 'tests/fixtures/selection/type2_reservation_cases'
        for side in ('insert', 'delete'):
            for mode in ('reserved', 'control'):
                with self.subTest(side=side, mode=mode):
                    result = self.run_fixture(fixtures / f'{side}_{mode}.xml')
                    if mode == 'control':
                        self.assertEqual(result['content_relationships']['type3'], 1)
                        continue
                    self.assertEqual(result['move_count'], 0)
                    evidence = result['diagnostics']
                    records = [r for r in evidence['correspondences']
                               if r['correspondence_kind'] == 'type2c']
                    self.assertEqual(len(records), 1)
                    record = records[0]
                    self.assertEqual(record['shadow_change'], 'stationary')
                    self.assertEqual(record['classification_reason'], 'same_anchor_interval')
                    self.assertEqual(record['current_result'], 'not_move')
                    for pair in evidence['type3_pairs']:
                        self.assertNotEqual(pair['delete_candidate_id'], record['delete_candidate_id'])
                        self.assertNotEqual(pair['insert_candidate_id'], record['insert_candidate_id'])

    def test_context_free_xml_retains_normalized_correspondences(self) -> None:
        contracts = json.loads((REPO_ROOT / 'tests/fixtures/selection/type2_normalization_contracts.json').read_text())
        self.assertEqual(len(contracts), 9)
        self.assertEqual(sum(map(len, contracts.values())), 10)
        for name, expected in contracts.items():
            with self.subTest(case=name):
                result = self.run_fixture(REPO_ROOT / 'tests/fixtures/xml/cases' / name / 'input.xml')
                self.assertEqual(result['moves'], [])
                evidence = result['diagnostics']
                candidates = {c['candidate_id']: c for c in evidence['candidates']}
                for correspondence in expected:
                    records = [r for r in evidence['correspondences']
                               if candidates[r['delete_candidate_id']]['xpath'] in correspondence['from_xpaths']
                               and candidates[r['insert_candidate_id']]['xpath'] in correspondence['to_xpaths']]
                    self.assertEqual(len(records), 1, correspondence)
                    record = records[0]
                    self.assertEqual(record['correspondence_kind'], 'type2c')
                    self.assertEqual(record['cardinality'], 'one_to_one')
                    self.assertEqual(record['shadow_change'], 'ambiguous')
                    self.assertEqual(record['classification_reason'], 'insufficient_context')
                    self.assertEqual(record['current_result'], 'not_move')
                    for side, prefix in (('delete', 'from'), ('insert', 'to')):
                        candidate = candidates[record[f'{side}_candidate_id']]
                        self.assertEqual([candidate['raw_text']], correspondence[f'{prefix}_raw_texts'])


if __name__ == '__main__':
    unittest.main()
