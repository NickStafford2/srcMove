"""Independent capability checks for narrowing movement location evidence.

Each target has a source-level displacement: it crosses a continuing sibling,
changes function, or changes file. Continuation alone must not erase those
capabilities when restructuring false positives are suppressed.
"""
from __future__ import annotations
import unittest
from tests.support import behavior as fixture
from tests.support.readable_cases import case_xml, evaluate_case
TARGET_TEXT = 'transfer_payload(state);'

class CorrespondenceRecallReviewTests(unittest.TestCase):

    def moved_targets(self, payload: dict) -> list[dict]:
        return [move for move in payload['moves'] if TARGET_TEXT in move['from_raw_texts']]

    def assert_single_target(self, xml: str) -> dict:
        payload = fixture.evaluate(self, xml)
        moves = self.moved_targets(payload)
        self.assertEqual(len(moves), 1)
        self.assertEqual(moves[0]['content_relationship'], 'type1')
        self.assertEqual(moves[0]['from_raw_texts'], [TARGET_TEXT])
        self.assertEqual(moves[0]['to_raw_texts'], [TARGET_TEXT])
        return payload

    def test_reorder_past_unchanged_conditional_remains_a_move(self):
        """Reorder past unchanged conditional remains a move."""
        self.assert_single_target(case_xml('correspondence_recall_review/reorder_past_unchanged_conditional_remains_a_move'))

    def test_reorder_past_unchanged_loop_remains_a_move(self):
        """Reorder past unchanged loop remains a move."""
        self.assert_single_target(case_xml('correspondence_recall_review/reorder_past_unchanged_loop_remains_a_move'))

    def test_equal_neighboring_context_does_not_hide_cross_function_transfer(self):
        """Equal neighboring context does not hide cross function transfer."""
        self.assert_single_target(case_xml('correspondence_recall_review/equal_neighboring_context_does_not_hide_cross_function_transfer'))

    def test_repeated_cross_file_copy_equivalence_remains_available(self):
        """Repeated cross file copy equivalence remains available."""
        payload = evaluate_case(self, 'correspondence_recall_review/repeated_cross_file_copy_equivalence_remains_available')
        moves = self.moved_targets(payload)
        self.assertEqual(len(moves), 1)
        self.assertEqual(len(moves[0]['from_xpaths']), 1)
        self.assertEqual(len(moves[0]['to_xpaths']), 2)

    def test_crossed_leaf_inside_added_wrapper_remains_a_move(self):
        """Crossed leaf inside added wrapper remains a move."""
        self.assert_single_target(case_xml('correspondence_recall_review/crossed_leaf_inside_added_wrapper_remains_a_move'))

    def test_stationary_continuation_leaves_real_cross_function_copies(self):
        """Stationary continuation leaves real cross function copies."""
        payload = evaluate_case(self, 'correspondence_recall_review/stationary_continuation_leaves_real_cross_function_copies')
        moves = self.moved_targets(payload)
        self.assertEqual(len(moves), 1)
        self.assertEqual(len(moves[0]['from_xpaths']), 1)
        self.assertEqual(len(moves[0]['to_xpaths']), 2)
        self.assertTrue(all(("src:name='copy_" in path for path in moves[0]['to_xpaths'])))
        self.assertEqual(moves[0]['selection_reason'], 'continuing_source_copy')

    def test_one_residual_copy_does_not_become_an_ordinary_one_to_one_move(self):
        """One residual copy does not become an ordinary one to one move."""
        payload = evaluate_case(self, 'correspondence_recall_review/one_residual_copy_does_not_become_an_ordinary_one_to_one_move')
        moves = self.moved_targets(payload)
        self.assertEqual(len(moves), 1)
        self.assertEqual(len(moves[0]['from_xpaths']), 1)
        self.assertEqual(len(moves[0]['to_xpaths']), 1)
        self.assertIn("src:name='copy_one'", moves[0]['to_xpaths'][0])
        self.assertEqual(moves[0]['selection_reason'], 'continuing_source_copy')
        self.assertEqual(payload['group_kinds']['copy_or_repeat'], 1)

    def test_learned_child_order_does_not_hide_whole_loop_relocation(self):
        """Learned child order does not hide whole loop relocation."""
        payload = evaluate_case(self, 'correspondence_recall_review/learned_child_order_does_not_hide_whole_loop_relocation')
        self.assertTrue(any((any((text.startswith('while') and TARGET_TEXT in text for text in move['from_raw_texts'])) or (TARGET_TEXT in move['from_raw_texts'] and any(('/src:while[' in path for path in move['from_xpaths']))) for move in payload['moves'])))

    def test_learned_same_kind_block_map_does_not_hide_real_transfer(self):
        """Learned same kind block map does not hide real transfer."""
        payload = evaluate_case(self, 'correspondence_recall_review/learned_same_kind_block_map_does_not_hide_real_transfer')
        moves = self.moved_targets(payload)
        self.assertEqual(len(moves), 1)
        self.assertEqual(moves[0]['from_raw_texts'], [TARGET_TEXT])
        self.assertEqual(moves[0]['to_raw_texts'], [TARGET_TEXT])

    def test_reorder_past_continuing_conditional_with_edited_body_is_retained(self):
        """Reorder past continuing conditional with edited body is retained."""
        self.assert_single_target(case_xml('correspondence_recall_review/reorder_past_continuing_conditional_with_edited_body_is_retained'))

    def test_unresolved_deleted_origin_prevents_residual_copy_provenance_claim(self):
        """Unresolved deleted origin prevents residual copy provenance claim."""
        payload = evaluate_case(self, 'correspondence_recall_review/unresolved_deleted_origin_prevents_residual_copy_provenance_claim')
        self.assertFalse(any((move['selection_reason'] == 'continuing_source_copy' for move in self.moved_targets(payload))))
if __name__ == '__main__':
    unittest.main()
