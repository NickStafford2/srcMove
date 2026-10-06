"""Whitespace containers cannot conceal meaningful sequence boundaries."""
from __future__ import annotations
import unittest
from tests.support import behavior as fixture
from tests.support.readable_cases import evaluate_case

class MoveSequenceBarrierTests(unittest.TestCase):

    def assert_atomic_pair(self, payload: dict) -> None:
        self.assertEqual(payload['move_group_count'], 2)
        self.assertEqual(payload['move_sequences'], [])

    def test_whitespace_only_container_is_transparent(self):
        """Whitespace only container is transparent."""
        payload = evaluate_case(self, 'move_sequence_barriers/whitespace_only_container_is_transparent')
        self.assertEqual(payload['sequence_cluster_count'], 1)

    def test_nonwhitespace_container_text_is_a_barrier(self):
        """Nonwhitespace container text is a barrier."""
        self.assert_atomic_pair(evaluate_case(self, 'move_sequence_barriers/nonwhitespace_container_text_is_a_barrier'))

    def test_source_element_under_whitespace_container_is_a_barrier(self):
        """Source element under whitespace container is a barrier."""
        self.assert_atomic_pair(evaluate_case(self, 'move_sequence_barriers/source_element_under_whitespace_container_is_a_barrier'))

    def test_empty_source_element_under_whitespace_container_is_a_barrier(self):
        """Empty source element under whitespace container is a barrier."""
        self.assert_atomic_pair(evaluate_case(self, 'move_sequence_barriers/empty_source_element_under_whitespace_container_is_a_barrier'))

    def test_comment_under_whitespace_container_remains_transparent(self):
        """Comment under whitespace container remains transparent."""
        payload = evaluate_case(self, 'move_sequence_barriers/comment_under_whitespace_container_remains_transparent')
        self.assertEqual(payload['sequence_cluster_count'], 1)

    def test_substantive_container_inside_member_excludes_that_member(self):
        """Substantive container inside member excludes that member."""
        self.assert_atomic_pair(evaluate_case(self, 'move_sequence_barriers/substantive_container_inside_member_excludes_that_member'))

    def test_destination_only_substantive_container_is_a_barrier(self):
        """Destination only substantive container is a barrier."""
        self.assert_atomic_pair(evaluate_case(self, 'move_sequence_barriers/destination_only_substantive_container_is_a_barrier'))

    def test_nested_whitespace_container_marks_outer_structural_parent(self):
        """Nested whitespace container marks outer structural parent."""
        self.assert_atomic_pair(evaluate_case(self, 'move_sequence_barriers/nested_whitespace_container_marks_outer_structural_parent'))

    def test_barrier_does_not_disable_later_ordered_run(self):
        """Barrier does not disable later ordered run."""
        payload = evaluate_case(self, 'move_sequence_barriers/barrier_does_not_disable_later_ordered_run')
        self.assertEqual(payload['move_group_count'], 3)
        fixture.assert_runs(self, payload, [['int b = 1;', 'int c = 1;']])

    def test_unknown_diff_tag_between_members_is_a_barrier(self):
        """Unknown diff tag between members is a barrier."""
        self.assert_atomic_pair(evaluate_case(self, 'move_sequence_barriers/unknown_diff_tag_between_members_is_a_barrier'))

    def test_unknown_diff_tag_inside_member_excludes_that_member(self):
        """Unknown diff tag inside member excludes that member."""
        self.assert_atomic_pair(evaluate_case(self, 'move_sequence_barriers/unknown_diff_tag_inside_member_excludes_that_member'))

    def test_unknown_diff_ancestor_excludes_members(self):
        """Unknown diff ancestor excludes members."""
        self.assert_atomic_pair(evaluate_case(self, 'move_sequence_barriers/unknown_diff_ancestor_excludes_members'))

    def test_unknown_diff_tag_inside_comment_is_transparent(self):
        """Unknown diff tag inside comment is transparent."""
        payload = evaluate_case(self, 'move_sequence_barriers/unknown_diff_tag_inside_comment_is_transparent')
        self.assertEqual(payload['sequence_cluster_count'], 1)
if __name__ == '__main__':
    unittest.main()
