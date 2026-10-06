"""Strict-ancestor context contracts shared by all three evidence classes."""
from pathlib import Path
import sys
from tests.support.execution import execute_xml
from tests.support.readable_cases import case_xml
import unittest
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = '{http://www.srcML.org/srcML/src}'
DIFF = '{http://www.srcML.org/srcDiff}'

class StructuralContextTests(unittest.TestCase):

    def test_strict_ancestors_across_evidence_classes(self):
        """Strict ancestors across evidence classes."""
        scenarios = [('same', None, None, 'stationary', 'same_anchor_interval'), ('wrap', None, 'while', 'restructured', 'ancestor_wrapped'), ('unwrap', 'while', None, 'restructured', 'ancestor_unwrapped'), ('incompatible', 'while', 'for', 'ambiguous', 'incompatible_context'), ('crossing', None, 'while', 'relocated', 'crossed_stable_sibling'), ('container', None, 'while', 'relocated', 'different_semantic_container'), ('file', None, 'while', 'relocated', 'different_file')]
        for kind in ('type1', 'type2c', 'type3'):
            for name, old_wrap, new_wrap, change, reason in scenarios:
                with self.subTest(kind=kind, scenario=name):
                    observation = execute_xml(case_xml('structural_context/' + name + '_' + kind), case_id=self.id(), modes=('results_only',))
                    data = observation.modes[0].payload()
                    candidates = {c['candidate_id']: c for c in data['diagnostics']['candidates']}
                    records = [r for r in data['diagnostics']['correspondences'] if r['correspondence_kind'] == kind and candidates[r['delete_candidate_id']]['construct'] == 'if_stmt']
                    self.assertEqual(len(records), 1)
                    record = records[0]
                    self.assertEqual((record['shadow_change'], record['classification_reason']), (change, reason))
                    for side, wrapper in [('before', old_wrap), ('after', new_wrap)]:
                        self.assertEqual(record[side + '_context']['meaningful_ancestors'], ['block'] + ([wrapper, 'block'] if wrapper else []))
                    self.assertFalse(record['carried_by_parent'])
                    expected = 'move' if change == 'relocated' else 'not_move'
                    self.assertEqual(record['current_result'], expected)
