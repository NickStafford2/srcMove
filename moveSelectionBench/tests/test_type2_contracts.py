"""Independent location oracle for observation-only Type-2 adoption."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarking.tooling import find_srcmove
from moveSelectionBench.shadow_contracts import (
    ShadowContractError,
    assert_shadow_expectation,
    evaluate_shadow_diagnostics,
    load_shadow_contracts,
    validate_srcdiff_precondition,
)

CATALOG = REPO_ROOT / 'moveSelectionBench/type2_contracts.json'


class Type2ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = load_shadow_contracts(CATALOG, correspondence_kind='type2')

    def test_type1_catalog_cannot_silently_accept_type2_contracts(self) -> None:
        with self.assertRaisesRegex(ShadowContractError, 'expected type1 evidence'):
            load_shadow_contracts(CATALOG)

    def test_reviewed_matrix_and_srcdiff_preconditions(self) -> None:
        self.assertEqual(len(self.cases), 18)
        self.assertEqual(
            {case['expected_shadow']['change_kind'] for case in self.cases},
            {'stationary', 'relocated', 'restructured', 'ambiguous'},
        )
        for case in self.cases:
            with self.subTest(case=case['id']):
                validate_srcdiff_precondition(case, case['fixture']['srcdiff'])

    def test_shared_decisions_match_oracle_and_output_modes(self) -> None:
        srcmove = find_srcmove(REPO_ROOT, None)
        self.assertIsNotNone(srcmove)
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            for case in self.cases:
                with self.subTest(case=case['id']):
                    outputs = []
                    annotations = []
                    for mode, diagnostics, results_only in (
                        ('ordinary', False, False),
                        ('observed', True, False),
                        ('results_only', True, True),
                    ):
                        output = temporary / f'{mode}.json'
                        annotation = temporary / f'{mode}.xml'
                        command = [str(srcmove), str(case['fixture']['srcdiff']),
                                   '--results', str(output), '--min-granularity', 'fragment']
                        if diagnostics:
                            command.append('--diagnostics')
                        if results_only:
                            command.append('--results-only')
                        else:
                            command.insert(2, str(annotation))
                        result = subprocess.run(command, cwd=REPO_ROOT, text=True,
                                                capture_output=True, check=False)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        payload = json.loads(output.read_text())
                        if diagnostics:
                            actual = evaluate_shadow_diagnostics(case, payload)
                            assert_shadow_expectation(case, actual)
                            if case['srcdiff_precondition']['cardinality'] == 'one_to_one':
                                precondition = case['srcdiff_precondition']
                                candidates = payload['diagnostics']['candidates']
                                paths = {
                                    side: {
                                        item['xpath'] for item in candidates
                                        if item['side'] == side
                                        and item['construct'] == precondition['element']
                                        and " ".join(item['raw_text'].split())
                                        == precondition[text]
                                    }
                                    for side, text in (('delete', 'before_text'), ('insert', 'after_text'))
                                }
                                selected = any(
                                    move.get('match_kind') == 'type2'
                                    and paths['delete'].intersection(move.get('from_xpaths', []))
                                    and paths['insert'].intersection(move.get('to_xpaths', []))
                                    for move in payload['moves']
                                )
                                self.assertEqual(actual['current_result'],
                                                 'move' if selected else 'not_move')
                                self.assertEqual(actual['current_result'],
                                                 case['expected_type2_output'])
                                if case.get('expected_selection') == 'covered_by_selected_parent':
                                    self.assertTrue(any(
                                        move.get('match_kind') == 'type2'
                                        and any(child.startswith(parent + '/')
                                                for child in paths['delete']
                                                for parent in move.get('from_xpaths', []))
                                        and any(child.startswith(parent + '/')
                                                for child in paths['insert']
                                                for parent in move.get('to_xpaths', []))
                                        for move in payload['moves']
                                    ), 'selection loss must be explained by a selected parent')
                            correspondence_ids = [
                                (item['delete_candidate_id'], item['insert_candidate_id'])
                                for item in payload['diagnostics']['correspondences']
                            ]
                            self.assertEqual(correspondence_ids, sorted(correspondence_ids))
                            if mode == 'observed':
                                observed_diagnostics = payload['diagnostics']
                            else:
                                self.assertEqual(observed_diagnostics, payload['diagnostics'])
                        payload.pop('diagnostics', None)
                        outputs.append(payload)
                        if not results_only:
                            annotations.append(annotation.read_bytes())
                    self.assertEqual(outputs[0], outputs[1])
                    self.assertEqual(outputs[0], outputs[2])
                    self.assertEqual(annotations[0], annotations[1])


if __name__ == '__main__':
    unittest.main()
