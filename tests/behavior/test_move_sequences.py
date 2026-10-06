"""Semantic contracts for additive, order-preserving move sequence reporting.

These are paired endpoint examples, not a claim about developer editing actions.
The five-declaration case reduces the retained OpenCV JacobiSVDImpl_ transfer to
its first unchanged declaration run, deliberately omitting its edited parent.
"""
from __future__ import annotations
import unittest
from tests.support.readable_cases import evaluate_case
from tests.support.behavior import assert_runs

class MoveSequenceTests(unittest.TestCase):

    def test_five_adjacent_declarations_preserve_five_atomic_moves(self):
        """Five adjacent declarations preserve five atomic moves."""
        names = ['vblas', 'Wbuf', 'W', 'iteration', 'rotation']
        payload = evaluate_case(self, 'move_sequences/five_adjacent_declarations_preserve_five_atomic_moves')
        self.assertEqual(payload['move_group_count'], 5)
        self.assertEqual(payload['move_count'], 5)
        self.assertEqual(payload['move_pair_count'], 5)
        self.assertEqual(payload['annotated_region_count'], 10)
        assert_runs(self, payload, [[f'int {name} = 1;' for name in names]])
        self.assertEqual(payload['sequence_reporting_unit_count'], 1)
        self.assertEqual(payload['reported_move_count'], 1)
        self.assertEqual(len(payload['reported_moves'][0]['member_move_ids']), 5)

    def test_partial_source_run_reports_only_shared_middle(self):
        """Partial source run reports only shared middle."""
        payload = evaluate_case(self, 'move_sequences/partial_source_run_reports_only_shared_middle')
        assert_runs(self, payload, [[f'int {name} = 1;' for name in 'cdef']])
        compound = [report for report in payload['reported_moves'] if report['report_kind'] == 'ordered_sequence']
        self.assertEqual(len(compound), 1)
        self.assertEqual(compound[0]['from_raw_texts'], [f'int {name} = 1;' for name in 'cdef'])

    def test_overlapping_runs_report_only_shared_suffix_prefix(self):
        """Overlapping runs report only shared suffix prefix."""
        payload = evaluate_case(self, 'move_sequences/overlapping_runs_report_only_shared_suffix_prefix')
        assert_runs(self, payload, [[f'int {name} = 1;' for name in 'efg']])

    def test_cyclic_reordering_keeps_ordered_pair_and_singleton(self):
        """Cyclic reordering keeps ordered pair and singleton."""
        payload = evaluate_case(self, 'move_sequences/cyclic_reordering_keeps_ordered_pair_and_singleton')
        self.assertEqual(payload['move_group_count'], 3)
        assert_runs(self, payload, [['int a = 1;', 'int b = 1;']])
        self.assertEqual(payload['sequence_reporting_unit_count'], 2)

    def test_mixed_child_kinds_and_fragmented_diff_wrappers(self):
        """Mixed child kinds and fragmented diff wrappers."""
        payload = evaluate_case(self, 'move_sequences/mixed_child_kinds_and_fragmented_diff_wrappers')
        self.assertEqual(payload['move_group_count'], 2)
        assert_runs(self, payload, [['int state = 1;', 'consume(state);']])

    def test_unchanged_child_gap_breaks_adjacency(self):
        """Unchanged child gap breaks adjacency."""
        payload = evaluate_case(self, 'move_sequences/unchanged_child_gap_breaks_adjacency')
        self.assertEqual(payload['move_group_count'], 2)
        assert_runs(self, payload, [])

    def test_unmatched_child_gap_breaks_adjacency(self):
        """Unmatched child gap breaks adjacency."""
        payload = evaluate_case(self, 'move_sequences/unmatched_child_gap_breaks_adjacency')
        self.assertEqual(payload['move_group_count'], 2)
        assert_runs(self, payload, [])

    def test_different_structural_parents_do_not_join(self):
        """Different structural parents do not join."""
        payload = evaluate_case(self, 'move_sequences/different_structural_parents_do_not_join')
        self.assertEqual(payload['move_group_count'], 2)
        assert_runs(self, payload, [])

    def test_repeated_group_does_not_choose_ordered_partners(self):
        """Repeated group does not choose ordered partners."""
        payload = evaluate_case(self, 'move_sequences/repeated_group_does_not_choose_ordered_partners')
        residual = next((move for move in payload['moves'] if move['selection_reason'] == 'unresolved_exact_residual'))
        supported = next((move for move in payload['moves'] if move['selection_reason'] == 'exact_neighbor_correspondence'))
        self.assertEqual(residual['from_raw_texts'], ['int repeat = 1;'])
        self.assertIn('/diff:delete[1]/', residual['from_xpaths'][0])
        self.assertIn('/diff:insert[1]/', residual['to_xpaths'][0])
        self.assertIn('/diff:delete[2]/', supported['from_xpaths'][0])
        self.assertIn('/diff:insert[2]/', supported['to_xpaths'][0])
        self.assertEqual(payload['group_kinds']['copy_or_repeat'], 1)
        self.assertTrue(all((residual['move_id'] not in sequence['member_move_ids'] for sequence in payload['move_sequences'])))
        assert_runs(self, payload, [['int repeat = 1;', 'int unique = 1;']])

    def test_filtered_destination_child_gap_does_not_join(self):
        """Filtered destination child gap does not join."""
        payload = evaluate_case(self, 'move_sequences/filtered_destination_child_gap_does_not_join')
        self.assertEqual(payload['move_group_count'], 2)
        assert_runs(self, payload, [])

    def test_full_reversal_has_no_order_preserving_run(self):
        """Full reversal has no order preserving run."""
        payload = evaluate_case(self, 'move_sequences/full_reversal_has_no_order_preserving_run')
        self.assertEqual(payload['move_group_count'], 3)
        assert_runs(self, payload, [])

    def test_comments_and_whitespace_are_transparent(self):
        """Comments and whitespace are transparent."""
        payload = evaluate_case(self, 'move_sequences/comments_and_whitespace_are_transparent')
        self.assertEqual(payload['move_group_count'], 2)
        assert_runs(self, payload, [['int a = 1;', 'int b = 1;']])

    def test_preprocessor_directive_between_members_is_a_barrier(self):
        """Preprocessor directive between members is a barrier."""
        payload = evaluate_case(self, 'move_sequences/preprocessor_directive_between_members_is_a_barrier')
        self.assertEqual(payload['move_group_count'], 2)
        assert_runs(self, payload, [])

    def test_preprocessor_directive_inside_member_is_a_barrier(self):
        """Preprocessor directive inside member is a barrier."""
        payload = evaluate_case(self, 'move_sequences/preprocessor_directive_inside_member_is_a_barrier')
        self.assertEqual(payload['move_group_count'], 2)
        assert_runs(self, payload, [])

    def test_nonwhitespace_direct_sibling_text_is_a_barrier(self):
        """Nonwhitespace direct sibling text is a barrier."""
        payload = evaluate_case(self, 'move_sequences/nonwhitespace_direct_sibling_text_is_a_barrier')
        self.assertEqual(payload['move_group_count'], 2)
        assert_runs(self, payload, [])

    def test_empty_opposite_revision_wrapper_inside_member_is_a_barrier(self):
        """Empty opposite revision wrapper inside member is a barrier."""
        payload = evaluate_case(self, 'move_sequences/empty_opposite_revision_wrapper_inside_member_is_a_barrier')
        self.assertEqual(payload['move_group_count'], 2)
        assert_runs(self, payload, [])

    def test_separate_revision_files_do_not_join(self):
        """Separate revision files do not join."""
        payload = evaluate_case(self, 'move_sequences/separate_revision_files_do_not_join')
        self.assertEqual(payload['move_group_count'], 2)
        assert_runs(self, payload, [])
if __name__ == '__main__':
    unittest.main()
