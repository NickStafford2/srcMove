"""Semantic contracts for additive, order-preserving move sequence reporting.

These are paired endpoint examples, not a claim about developer editing actions.
The five-declaration case reduces the retained OpenCV JacobiSVDImpl_ transfer to
its first unchanged declaration run, deliberately omitting its edited parent.
"""
from __future__ import annotations

import unittest

from tests.support.behavior import PREFIX, decl, expression, run, document, evaluate, assert_runs


class MoveSequenceTests(unittest.TestCase):
    def test_five_adjacent_declarations_preserve_five_atomic_moves(self):
        # Same ordering and sibling boundaries as the retained OpenCV example.
        names = ['vblas', 'Wbuf', 'W', 'iteration', 'rotation']
        nodes = [decl(name) for name in names]
        payload = evaluate(self, document(nodes, nodes))
        self.assertEqual(payload['move_group_count'], 5)
        self.assertEqual(payload['move_count'], 5)
        self.assertEqual(payload['move_pair_count'], 5)
        self.assertEqual(payload['annotated_region_count'], 10)
        assert_runs(self, payload, [[f'int {name} = 1;' for name in names]])
        self.assertEqual(payload['sequence_reporting_unit_count'], 1)
        self.assertEqual(payload['reported_move_count'], 1)
        self.assertEqual(len(payload['reported_moves'][0]['member_move_ids']), 5)

    def test_partial_source_run_reports_only_shared_middle(self):
        before = [decl(name) for name in 'abcdefg']
        after = [decl(name) for name in 'cdef']
        payload = evaluate(self, document(before, after))
        assert_runs(self, payload, [[f'int {name} = 1;' for name in 'cdef']])
        compound = [report for report in payload['reported_moves']
                    if report['report_kind'] == 'ordered_sequence']
        self.assertEqual(len(compound), 1)
        self.assertEqual(compound[0]['from_raw_texts'], [f'int {name} = 1;' for name in 'cdef'])

    def test_overlapping_runs_report_only_shared_suffix_prefix(self):
        payload = evaluate(self, document([decl(name) for name in 'abcdefg'],
                                         [decl(name) for name in 'efghij']))
        assert_runs(self, payload, [[f'int {name} = 1;' for name in 'efg']])

    def test_cyclic_reordering_keeps_ordered_pair_and_singleton(self):
        a, b, c = [decl(name) for name in ('a', 'b', 'c')]
        payload = evaluate(self, document([a, b, c], [c, a, b]))
        self.assertEqual(payload['move_group_count'], 3)
        assert_runs(self, payload, [['int a = 1;', 'int b = 1;']])
        self.assertEqual(payload['sequence_reporting_unit_count'], 2)

    def test_mixed_child_kinds_and_fragmented_diff_wrappers(self):
        nodes = [decl('state'), expression('consume')]
        payload = evaluate(self, document(nodes, nodes))
        self.assertEqual(payload['move_group_count'], 2)
        assert_runs(self, payload, [['int state = 1;', 'consume(state);']])

    def test_unchanged_child_gap_breaks_adjacency(self):
        a, b = decl('a'), decl('b')
        xml = PREFIX + run('delete', [a]) + '<diff:common>' + decl('anchor') + '</diff:common>'
        xml += run('delete', [b]) + run('insert', [a, b]) + '</unit>'
        payload = evaluate(self, xml)
        self.assertEqual(payload['move_group_count'], 2)
        assert_runs(self, payload, [])

    def test_unmatched_child_gap_breaks_adjacency(self):
        a, b = decl('a'), decl('b')
        payload = evaluate(self, document([a, expression('removed_only'), b], [a, b]))
        self.assertEqual(payload['move_group_count'], 2)
        assert_runs(self, payload, [])

    def test_different_structural_parents_do_not_join(self):
        a, b = decl('a'), decl('b')
        block = lambda node: '<block>{<block_content>' + node + '</block_content>}</block>'
        payload = evaluate(self, document([block(a), block(b)], [a, b]))
        self.assertEqual(payload['move_group_count'], 2)
        assert_runs(self, payload, [])

    def test_repeated_group_does_not_choose_ordered_partners(self):
        a, b = decl('repeat'), decl('unique')
        payload = evaluate(self, document([a, a, b], [a, a, b]))
        residual = next(move for move in payload['moves']
                        if move['selection_reason'] == 'unresolved_exact_residual')
        supported = next(move for move in payload['moves']
                         if move['selection_reason'] == 'exact_neighbor_correspondence')
        self.assertEqual(residual['from_raw_texts'], ['int repeat = 1;'])
        self.assertIn('/diff:delete[1]/', residual['from_xpaths'][0])
        self.assertIn('/diff:insert[1]/', residual['to_xpaths'][0])
        self.assertIn('/diff:delete[2]/', supported['from_xpaths'][0])
        self.assertIn('/diff:insert[2]/', supported['to_xpaths'][0])
        self.assertEqual(payload['group_kinds']['copy_or_repeat'], 1)
        self.assertTrue(all(residual['move_id'] not in sequence['member_move_ids']
                            for sequence in payload['move_sequences']))
        assert_runs(self, payload, [['int repeat = 1;', 'int unique = 1;']])

    def test_filtered_destination_child_gap_does_not_join(self):
        a, b = decl('a'), decl('b')
        short = '<return>return;</return>'
        payload = evaluate(self, document([a, b], [a, short, b]))
        self.assertEqual(payload['move_group_count'], 2)
        assert_runs(self, payload, [])

    def test_full_reversal_has_no_order_preserving_run(self):
        nodes = [decl(n) for n in ('a', 'b', 'c')]
        payload = evaluate(self, document(nodes, list(reversed(nodes))))
        self.assertEqual(payload['move_group_count'], 3)
        assert_runs(self, payload, [])

    def test_comments_and_whitespace_are_transparent(self):
        a, b = decl('a'), decl('b')
        comment = '<comment type="line">// retained explanation</comment>\n'
        before = run('delete', [a]) + comment + run('delete', [b])
        after = run('insert', [a]) + comment + run('insert', [b])
        payload = evaluate(self, PREFIX + before + after + '</unit>')
        self.assertEqual(payload['move_group_count'], 2)
        assert_runs(self, payload, [['int a = 1;', 'int b = 1;']])

    def test_preprocessor_directive_between_members_is_a_barrier(self):
        a, b = decl('a'), decl('b')
        directive = '<cpp:pragma>#pragma optimize("", off)</cpp:pragma>\n'
        before = run('delete', [a]) + directive + run('delete', [b])
        payload = evaluate(self, PREFIX + before + run('insert', [a, b]) + '</unit>')
        self.assertEqual(payload['move_group_count'], 2)
        assert_runs(self, payload, [])

    def test_preprocessor_directive_inside_member_is_a_barrier(self):
        a = decl('a')
        b = decl('b').replace('<name>b</name>',
            '\n<cpp:if>#if FLAG</cpp:if>\n<name>b</name>\n<cpp:endif>#endif</cpp:endif>\n')
        payload = evaluate(self, document([a, b], [a, b]))
        self.assertEqual(payload['move_group_count'], 2)
        assert_runs(self, payload, [])

    def test_nonwhitespace_direct_sibling_text_is_a_barrier(self):
        a, b = decl('a'), decl('b')
        before = run('delete', [a]) + 'unrepresented();\n' + run('delete', [b])
        payload = evaluate(self, PREFIX + before + run('insert', [a, b]) + '</unit>')
        self.assertEqual(payload['move_group_count'], 2)
        assert_runs(self, payload, [])

    def test_empty_opposite_revision_wrapper_inside_member_is_a_barrier(self):
        a, b = decl('a'), decl('b')
        before_b = b.replace('<name>b</name>', '<name>b</name><diff:insert/>')
        payload = evaluate(self, document([a, before_b], [a, b]))
        self.assertEqual(payload['move_group_count'], 2)
        assert_runs(self, payload, [])

    def test_separate_revision_files_do_not_join(self):
        # One source run fans out to distinct destination units.
        xml = PREFIX.replace(' filename="before.cpp|after.cpp"', '')
        xml += '<unit filename="before.cpp|first.cpp">' + run('delete', [decl('a'), decl('b')])
        xml += run('insert', [decl('a')]) + '</unit>'
        xml += '<unit filename="|second.cpp">' + run('insert', [decl('b')]) + '</unit></unit>'
        payload = evaluate(self, xml)
        self.assertEqual(payload['move_group_count'], 2)
        assert_runs(self, payload, [])


if __name__ == '__main__':
    unittest.main()
