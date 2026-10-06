"""Unresolved exact groups need positive displacement evidence, not pair identity."""
from __future__ import annotations
import unittest
from tests.support.readable_cases import evaluate_case

class RepeatedGroupLocationTests(unittest.TestCase):

    def repeated_moves(self, payload: dict) -> list[dict]:
        return [move for move in payload['moves'] if move['from_raw_texts'] and all((text == 'repeat_work(state);' for text in move['from_raw_texts']))]

    def assert_group(self, payload: dict, deletes=2, inserts=2):
        moves = self.repeated_moves(payload)
        self.assertEqual(len(moves), 1)
        self.assertEqual(len(moves[0]['from_xpaths']), deletes)
        self.assertEqual(len(moves[0]['to_xpaths']), inserts)
        self.assertEqual(payload['move_sequences'], [])
        self.assertEqual(moves[0]['selection_reason'], 'greedy_utility')

    def test_same_file_unmapped_repeated_endpoints_are_withheld(self):
        """Same file unmapped repeated endpoints are withheld."""
        payload = evaluate_case(self, 'repeated_group_location/same_file_unmapped_repeated_endpoints_are_withheld')
        self.assertEqual(self.repeated_moves(payload), [])
        self.assertEqual(payload['move_group_count'], 0)

    def test_same_mapped_container_interval_repeated_endpoints_are_withheld(self):
        """Same mapped container interval repeated endpoints are withheld."""
        payload = evaluate_case(self, 'repeated_group_location/same_mapped_container_interval_repeated_endpoints_are_withheld')
        self.assertEqual(self.repeated_moves(payload), [])
        self.assertEqual(payload['move_group_count'], 0)

    def test_cross_file_one_to_many_copy_is_retained(self):
        """Cross file one to many copy is retained."""
        self.assert_group(evaluate_case(self, 'repeated_group_location/cross_file_one_to_many_copy_is_retained'), 1, 2)

    def test_cross_file_many_to_one_repeat_is_retained(self):
        """Cross file many to one repeat is retained."""
        self.assert_group(evaluate_case(self, 'repeated_group_location/cross_file_many_to_one_repeat_is_retained'), 2, 1)

    def test_different_mapped_containers_support_unresolved_group(self):
        """Different mapped containers support unresolved group."""
        self.assert_group(evaluate_case(self, 'repeated_group_location/different_mapped_containers_support_unresolved_group'))

    def test_varied_source_containers_retain_possible_displacement(self):
        """Varied source containers retain possible displacement."""
        self.assert_group(evaluate_case(self, 'repeated_group_location/varied_source_containers_retain_possible_displacement'), 2, 1)

    def test_crossed_common_anchor_supports_unresolved_group(self):
        """Crossed common anchor supports unresolved group."""
        self.assert_group(evaluate_case(self, 'repeated_group_location/crossed_common_anchor_supports_unresolved_group'))

    def test_unknown_file_cannot_use_container_displacement(self):
        """Unknown file cannot use container displacement."""
        payload = evaluate_case(self, 'repeated_group_location/unknown_file_cannot_use_container_displacement')
        self.assertEqual(self.repeated_moves(payload), [])
        self.assertEqual(payload['move_group_count'], 0)
if __name__ == '__main__':
    unittest.main()
