"""Whitespace containers cannot conceal meaningful sequence boundaries."""
from __future__ import annotations

import unittest

from tests.support import behavior as fixture

PREFIX, decl, document, run = fixture.PREFIX, fixture.decl, fixture.document, fixture.run


class MoveSequenceBarrierTests(unittest.TestCase):
    def evaluate(self, xml: str) -> dict:
        return fixture.evaluate(self, xml)

    def with_source_gap(self, gap: str) -> dict:
        a, b = decl('a'), decl('b')
        return self.evaluate(PREFIX + run('delete', [a]) + gap +
                             run('delete', [b]) + run('insert', [a, b]) + '</unit>')

    def assert_atomic_pair(self, payload: dict) -> None:
        self.assertEqual(payload['move_group_count'], 2)
        self.assertEqual(payload['move_sequences'], [])

    def test_whitespace_only_container_is_transparent(self):
        payload = self.with_source_gap('<diff:ws> \n\t </diff:ws>')
        self.assertEqual(payload['sequence_cluster_count'], 1)

    def test_nonwhitespace_container_text_is_a_barrier(self):
        self.assert_atomic_pair(self.with_source_gap('<diff:ws>hidden();</diff:ws>'))

    def test_source_element_under_whitespace_container_is_a_barrier(self):
        self.assert_atomic_pair(self.with_source_gap('<diff:ws><name>hidden</name></diff:ws>'))

    def test_empty_source_element_under_whitespace_container_is_a_barrier(self):
        self.assert_atomic_pair(self.with_source_gap('<diff:ws><empty_stmt/></diff:ws>'))

    def test_comment_under_whitespace_container_remains_transparent(self):
        payload = self.with_source_gap('<diff:ws><comment>// ignored explanation</comment>\n</diff:ws>')
        self.assertEqual(payload['sequence_cluster_count'], 1)

    def test_substantive_container_inside_member_excludes_that_member(self):
        a = decl('a')
        b = decl('b').replace('<name>b</name>', '<name>b</name><diff:ws>hidden</diff:ws>')
        self.assert_atomic_pair(self.evaluate(document([a, b], [a, b])))

    def test_destination_only_substantive_container_is_a_barrier(self):
        a, b = decl('a'), decl('b')
        destination = run('insert', [a]) + '<diff:insert><diff:ws>hidden</diff:ws></diff:insert>' + run('insert', [b])
        self.assert_atomic_pair(self.evaluate(PREFIX + run('delete', [a, b]) + destination + '</unit>'))

    def test_nested_whitespace_container_marks_outer_structural_parent(self):
        self.assert_atomic_pair(self.with_source_gap('<diff:ws><diff:ws>hidden</diff:ws></diff:ws>'))

    def test_barrier_does_not_disable_later_ordered_run(self):
        a, b, c = [decl(name) for name in ('a', 'b', 'c')]
        source = run('delete', [a]) + '<diff:ws>hidden</diff:ws>' + run('delete', [b, c])
        payload = self.evaluate(PREFIX + source + run('insert', [a, b, c]) + '</unit>')
        self.assertEqual(payload['move_group_count'], 3)
        fixture.assert_runs(self, payload, [['int b = 1;', 'int c = 1;']])

    def test_unknown_diff_tag_between_members_is_a_barrier(self):
        self.assert_atomic_pair(self.with_source_gap('<diff:unknown/>'))

    def test_unknown_diff_tag_inside_member_excludes_that_member(self):
        a = decl('a')
        b = decl('b').replace('<name>b</name>', '<name>b</name><diff:unknown/>')
        self.assert_atomic_pair(self.evaluate(document([a, b], [a, b])))

    def test_unknown_diff_ancestor_excludes_members(self):
        nodes = [decl('a'), decl('b')]
        source = '<diff:unknown>' + run('delete', nodes) + '</diff:unknown>'
        self.assert_atomic_pair(self.evaluate(PREFIX + source + run('insert', nodes) + '</unit>'))

    def test_unknown_diff_tag_inside_comment_is_transparent(self):
        payload = self.with_source_gap('<comment>// <diff:unknown/> explanation</comment>')
        self.assertEqual(payload['sequence_cluster_count'], 1)


if __name__ == '__main__':
    unittest.main()
