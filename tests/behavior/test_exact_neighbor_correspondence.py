"""Repeated exact endpoints need independent, mutually unique sibling evidence."""
from __future__ import annotations
import unittest
from tests.support import behavior as fixture
from tests.support.readable_cases import evaluate_case

class ExactNeighborCorrespondenceTests(unittest.TestCase):

    def repeated_moves(self, payload: dict) -> list[dict]:
        return [move for move in payload['moves'] if move['from_raw_texts'] and all((text == 'repeat_work(state);' for text in move['from_raw_texts']))]

    def assert_unresolved(self, payload: dict, deletes=2, inserts=2):
        moves = self.repeated_moves(payload)
        self.assertEqual(len(moves), 1)
        self.assertEqual(len(moves[0]['from_xpaths']), deletes)
        self.assertEqual(len(moves[0]['to_xpaths']), inserts)

    def test_unique_neighbors_resolve_reordered_repeated_pairs(self):
        """Unique neighbors resolve reordered repeated pairs."""
        payload = evaluate_case(self, 'exact_neighbor_correspondence/unique_neighbors_resolve_reordered_repeated_pairs')
        moves = self.repeated_moves(payload)
        self.assertEqual(len(moves), 2)
        self.assertTrue(all((len(move['from_xpaths']) == len(move['to_xpaths']) == 1 for move in moves)))
        self.assertTrue(all((move['selection_reason'] == 'exact_neighbor_correspondence' for move in moves)))
        ordered = sorted(moves, key=lambda move: move['from_xpaths'])
        self.assertGreater(ordered[0]['to_xpaths'][0], ordered[1]['to_xpaths'][0])
        fixture.assert_runs(self, payload, [['repeat_work(state);', 'unique_a(state);'], ['repeat_work(state);', 'unique_b(state);']])

    def test_partial_wrapper_coverage_cannot_override_resolved_children(self):
        """Partial wrapper coverage cannot override resolved children."""
        payload = evaluate_case(self, 'exact_neighbor_correspondence/partial_wrapper_coverage_cannot_override_resolved_children')
        moves = self.repeated_moves(payload)
        self.assertEqual(len(moves), 2)
        self.assertTrue(all((len(move['from_xpaths']) == len(move['to_xpaths']) == 1 for move in moves)))
        self.assertTrue(all((move['selection_reason'] == 'exact_neighbor_correspondence' for move in moves)))

    def test_inferred_pairs_do_not_seed_further_correspondences(self):
        """Inferred pairs do not seed further correspondences."""
        payload = evaluate_case(self, 'exact_neighbor_correspondence/inferred_pairs_do_not_seed_further_correspondences')
        self.assertEqual(len(self.repeated_moves(payload)), 2)
        remaining = [move for move in payload['moves'] if move['from_raw_texts'] == ['other_repeat(state);'] * 2]
        self.assertEqual(len(remaining), 1)
        self.assertEqual(len(remaining[0]['from_xpaths']), 2)
        self.assertEqual(len(remaining[0]['to_xpaths']), 2)

    def test_no_original_unique_neighbors_preserves_equivalence_group(self):
        """No original unique neighbors preserves equivalence group."""
        self.assert_unresolved(evaluate_case(self, 'exact_neighbor_correspondence/no_original_unique_neighbors_preserves_equivalence_group'))

    def test_partial_resolution_does_not_infer_partner_by_elimination(self):
        """Partial resolution does not infer partner by elimination."""
        payload = evaluate_case(self, 'exact_neighbor_correspondence/partial_resolution_does_not_infer_partner_by_elimination')
        moves = self.repeated_moves(payload)
        self.assertEqual(len(moves), 2)
        supported = next((move for move in moves if move['selection_reason'] == 'exact_neighbor_correspondence'))
        residual = next((move for move in moves if move['selection_reason'] == 'unresolved_exact_residual'))
        self.assertIn('/diff:delete[2]/', supported['from_xpaths'][0])
        self.assertIn('/diff:insert[2]/', supported['to_xpaths'][0])
        self.assertIn('/diff:delete[1]/', residual['from_xpaths'][0])
        self.assertIn('/diff:insert[1]/', residual['to_xpaths'][0])
        self.assertEqual(payload['group_kinds']['copy_or_repeat'], 1)
        self.assertTrue(all((residual['move_id'] not in sequence['member_move_ids'] for sequence in payload['move_sequences'])))
        fixture.assert_runs(self, payload, [['repeat_work(state);', 'unique_a(state);']])

    def test_conflicting_neighbors_preserve_whole_group(self):
        """Conflicting neighbors preserve whole group."""
        self.assert_unresolved(evaluate_case(self, 'exact_neighbor_correspondence/conflicting_neighbors_preserve_whole_group'))

    def test_one_to_many_copy_group_is_preserved_with_neighbor_evidence(self):
        """One to many copy group is preserved with neighbor evidence."""
        self.assert_unresolved(evaluate_case(self, 'exact_neighbor_correspondence/one_to_many_copy_group_is_preserved_with_neighbor_evidence'), 1, 2)

    def test_many_to_one_repeat_group_is_preserved_with_neighbor_evidence(self):
        """Many to one repeat group is preserved with neighbor evidence."""
        self.assert_unresolved(evaluate_case(self, 'exact_neighbor_correspondence/many_to_one_repeat_group_is_preserved_with_neighbor_evidence'), 2, 1)

    def test_resolved_stationary_pairs_are_not_reported_as_moves(self):
        """Resolved stationary pairs are not reported as moves."""
        payload = evaluate_case(self, 'exact_neighbor_correspondence/resolved_stationary_pairs_are_not_reported_as_moves')
        self.assertEqual(self.repeated_moves(payload), [])
        self.assertEqual(payload['move_sequences'], [])
if __name__ == '__main__':
    unittest.main()
