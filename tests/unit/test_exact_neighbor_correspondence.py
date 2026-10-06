"""Repeated exact endpoints need independent, mutually unique sibling evidence."""
from __future__ import annotations

import unittest

from tests.unit import test_move_sequences as fixture

expression, document = fixture.expression, fixture.document
GAP = '<return>return;</return>'


class ExactNeighborCorrespondenceTests(unittest.TestCase):
    def evaluate(self, before: list[str], after: list[str], *, same_file=False,
                 mixed_destination=False) -> dict:
        xml = document(before, after)
        if mixed_destination:
            xml = (fixture.PREFIX + fixture.run('delete', before) +
                   fixture.run('insert', after[:2], fragmented=False) +
                   fixture.run('insert', after[2:]) + '</unit>')
        if same_file:
            xml = xml.replace('before.cpp|after.cpp', 'same.cpp')
            xml = xml.replace('>' + fixture.run('delete', before),
                              '><function><type><name>void</name></type> <name>worker</name>'
                              '<parameter_list>()</parameter_list><block>{<block_content>' +
                              fixture.run('delete', before), 1)
            xml = xml.replace('</unit>', '</block_content>}</block></function></unit>')
        # The shared harness asserts annotation and result parity across ordinary,
        # diagnostic, and results-only modes, and checks sequence/report identity.
        return fixture.MoveSequenceTests().evaluate(xml)

    def repeated_moves(self, payload: dict) -> list[dict]:
        return [move for move in payload['moves']
                if move['from_raw_texts'] and
                all(text == 'repeat_work(state);' for text in move['from_raw_texts'])]

    def assert_unresolved(self, payload: dict, deletes=2, inserts=2):
        moves = self.repeated_moves(payload)
        self.assertEqual(len(moves), 1)
        self.assertEqual(len(moves[0]['from_xpaths']), deletes)
        self.assertEqual(len(moves[0]['to_xpaths']), inserts)

    def test_unique_neighbors_resolve_reordered_repeated_pairs(self):
        repeat, a, b = [expression(name) for name in ('repeat_work', 'unique_a', 'unique_b')]
        payload = self.evaluate([repeat, a, GAP, repeat, b],
                                [repeat, b, GAP, repeat, a])
        moves = self.repeated_moves(payload)
        self.assertEqual(len(moves), 2)
        self.assertTrue(all(len(move['from_xpaths']) == len(move['to_xpaths']) == 1
                            for move in moves))
        self.assertTrue(all(move['selection_reason'] == 'exact_neighbor_correspondence'
                            for move in moves))
        # The first repeated origin follows its unique_a context to the later
        # destination; source/destination ordinal order alone would be wrong.
        ordered = sorted(moves, key=lambda move: move['from_xpaths'])
        self.assertGreater(ordered[0]['to_xpaths'][0], ordered[1]['to_xpaths'][0])
        fixture.MoveSequenceTests().assert_runs(payload, [
            ['repeat_work(state);', 'unique_a(state);'],
            ['repeat_work(state);', 'unique_b(state);'],
        ])

    def test_partial_wrapper_coverage_cannot_override_resolved_children(self):
        repeat, a, b = [expression(name) for name in ('repeat_work', 'unique_a', 'unique_b')]
        payload = self.evaluate([repeat, a, GAP, repeat, b],
                                [repeat, b, GAP, repeat, a], mixed_destination=True)
        moves = self.repeated_moves(payload)
        self.assertEqual(len(moves), 2)
        self.assertTrue(all(len(move['from_xpaths']) == len(move['to_xpaths']) == 1
                            for move in moves))
        self.assertTrue(all(move['selection_reason'] == 'exact_neighbor_correspondence'
                            for move in moves))

    def test_inferred_pairs_do_not_seed_further_correspondences(self):
        a, b, repeat, other = [expression(name) for name in
                               ('unique_a', 'unique_b', 'repeat_work', 'other_repeat')]
        payload = self.evaluate([a, repeat, other, GAP, b, repeat, other],
                                [b, repeat, other, GAP, a, repeat, other])
        self.assertEqual(len(self.repeated_moves(payload)), 2)
        remaining = [move for move in payload['moves']
                     if move['from_raw_texts'] == ['other_repeat(state);'] * 2]
        self.assertEqual(len(remaining), 1)
        self.assertEqual(len(remaining[0]['from_xpaths']), 2)
        self.assertEqual(len(remaining[0]['to_xpaths']), 2)

    def test_no_original_unique_neighbors_preserves_equivalence_group(self):
        repeat = expression('repeat_work')
        self.assert_unresolved(self.evaluate([repeat, repeat], [repeat, repeat]))

    def test_partial_resolution_does_not_infer_partner_by_elimination(self):
        repeat, unique = expression('repeat_work'), expression('unique_a')
        payload = self.evaluate([repeat, repeat, unique], [repeat, repeat, unique])
        moves = self.repeated_moves(payload)
        self.assertEqual(len(moves), 2)
        supported = next(move for move in moves
                         if move['selection_reason'] == 'exact_neighbor_correspondence')
        residual = next(move for move in moves
                        if move['selection_reason'] == 'unresolved_exact_residual')
        # Only the repeat immediately before the original unique statement has
        # independent evidence. The first occurrence remains an equivalence.
        self.assertIn('/diff:delete[2]/', supported['from_xpaths'][0])
        self.assertIn('/diff:insert[2]/', supported['to_xpaths'][0])
        self.assertIn('/diff:delete[1]/', residual['from_xpaths'][0])
        self.assertIn('/diff:insert[1]/', residual['to_xpaths'][0])
        self.assertEqual(payload['group_kinds']['copy_or_repeat'], 1)
        self.assertTrue(all(residual['move_id'] not in sequence['member_move_ids']
                            for sequence in payload['move_sequences']))
        fixture.MoveSequenceTests().assert_runs(payload, [
            ['repeat_work(state);', 'unique_a(state);'],
        ])

    def test_conflicting_neighbors_preserve_whole_group(self):
        repeat, a, b, c, d = [expression(name) for name in
                              ('repeat_work', 'unique_a', 'unique_b', 'unique_c', 'unique_d')]
        self.assert_unresolved(self.evaluate([a, repeat, b, GAP, c, repeat, d],
                                            [a, repeat, d, GAP, c, repeat, b]))

    def test_one_to_many_copy_group_is_preserved_with_neighbor_evidence(self):
        repeat, unique = expression('repeat_work'), expression('unique_a')
        self.assert_unresolved(self.evaluate([repeat, unique],
                                            [repeat, unique, GAP, repeat]), 1, 2)

    def test_many_to_one_repeat_group_is_preserved_with_neighbor_evidence(self):
        repeat, unique = expression('repeat_work'), expression('unique_a')
        self.assert_unresolved(self.evaluate([repeat, unique, GAP, repeat],
                                            [repeat, unique]), 2, 1)

    def test_resolved_stationary_pairs_are_not_reported_as_moves(self):
        repeat, a, b = [expression(name) for name in ('repeat_work', 'unique_a', 'unique_b')]
        nodes = [repeat, a, GAP, repeat, b]
        payload = self.evaluate(nodes, nodes, same_file=True)
        self.assertEqual(self.repeated_moves(payload), [])
        self.assertEqual(payload['move_sequences'], [])


if __name__ == '__main__':
    unittest.main()
