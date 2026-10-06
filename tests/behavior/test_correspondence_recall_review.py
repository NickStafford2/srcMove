"""Independent capability checks for narrowing movement location evidence.

Each target has a source-level displacement: it crosses a continuing sibling,
changes function, or changes file. Continuation alone must not erase those
capabilities when restructuring false positives are suppressed.
"""
from __future__ import annotations

import unittest

from tests.support import behavior as fixture


TARGET = fixture.expression('transfer_payload')
TARGET_TEXT = 'transfer_payload(state);'


def function(body: str, name: str = 'process') -> str:
    return ('<function><type><name>void</name></type> <name>' + name +
            '</name><parameter_list>()</parameter_list><block>{<block_content>' +
            body + '</block_content>}</block></function>')


def same_file(body: str) -> str:
    return fixture.PREFIX.replace('before.cpp|after.cpp', 'same.cpp') + function(body) + '</unit>'


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
        conditional = ('<if_stmt><if>if <condition>(<expr><name>ready</name></expr>)'
                       '</condition><block>{<block_content>' + fixture.expression('flush_results') +
                       '</block_content>}</block></if></if_stmt>')
        body = fixture.run('delete', [TARGET]) + conditional + fixture.run('insert', [TARGET])
        self.assert_single_target(same_file(body))

    def test_reorder_past_unchanged_loop_remains_a_move(self):
        loop = ('<while>while <condition>(<expr><name>ready</name></expr>)</condition>'
                '<block>{<block_content>' + fixture.expression('flush_results') +
                '</block_content>}</block></while>')
        body = fixture.run('delete', [TARGET]) + loop + fixture.run('insert', [TARGET])
        self.assert_single_target(same_file(body))

    def test_equal_neighboring_context_does_not_hide_cross_function_transfer(self):
        # Identical surrounding calls in two mapped functions do not mean that
        # the transferred statement stayed in place.
        neighbor = fixture.expression('flush_results')
        xml = fixture.PREFIX.replace('before.cpp|after.cpp', 'same.cpp')
        xml += function(neighbor + fixture.run('delete', [TARGET]), 'origin')
        xml += function(neighbor + fixture.run('insert', [TARGET]), 'destination') + '</unit>'
        self.assert_single_target(xml)

    def test_repeated_cross_file_copy_equivalence_remains_available(self):
        payload = fixture.evaluate(self, fixture.document([TARGET], [TARGET, TARGET]))
        moves = self.moved_targets(payload)
        self.assertEqual(len(moves), 1)
        self.assertEqual(len(moves[0]['from_xpaths']), 1)
        self.assertEqual(len(moves[0]['to_xpaths']), 2)

    def test_crossed_leaf_inside_added_wrapper_remains_a_move(self):
        wrapper = '<block>{<block_content>' + TARGET + '</block_content>}</block>'
        body = (fixture.run('delete', [TARGET]) + fixture.expression('flush_results') +
                fixture.run('insert', [wrapper]))
        self.assert_single_target(same_file(body))

    def test_stationary_continuation_leaves_real_cross_function_copies(self):
        unique = fixture.expression('unique_origin_context')
        xml = fixture.PREFIX.replace('before.cpp|after.cpp', 'same.cpp')
        xml += function(fixture.run('delete', [TARGET, unique]) + fixture.run('insert', [TARGET, unique]) +
                        fixture.expression('flush_results'), 'origin')
        xml += function(fixture.run('insert', [TARGET]), 'copy_one')
        xml += function(fixture.run('insert', [TARGET]), 'copy_two') + '</unit>'
        payload = fixture.evaluate(self, xml)
        moves = self.moved_targets(payload)
        self.assertEqual(len(moves), 1)
        self.assertEqual(len(moves[0]['from_xpaths']), 1)
        self.assertEqual(len(moves[0]['to_xpaths']), 2)
        self.assertTrue(all("src:name='copy_" in path for path in moves[0]['to_xpaths']))
        self.assertEqual(moves[0]['selection_reason'], 'continuing_source_copy')

    def test_one_residual_copy_does_not_become_an_ordinary_one_to_one_move(self):
        unique = fixture.expression('unique_origin_context')
        xml = fixture.PREFIX.replace('before.cpp|after.cpp', 'same.cpp')
        xml += function(fixture.run('delete', [TARGET, unique]) + fixture.run('insert', [TARGET, unique]) +
                        fixture.expression('flush_results'), 'origin')
        xml += function(fixture.run('insert', [TARGET]), 'copy_one') + '</unit>'
        payload = fixture.evaluate(self, xml)
        moves = self.moved_targets(payload)
        self.assertEqual(len(moves), 1)
        self.assertEqual(len(moves[0]['from_xpaths']), 1)
        self.assertEqual(len(moves[0]['to_xpaths']), 1)
        self.assertIn("src:name='copy_one'", moves[0]['to_xpaths'][0])
        self.assertEqual(moves[0]['selection_reason'], 'continuing_source_copy')
        self.assertEqual(payload['group_kinds']['copy_or_repeat'], 1)

    def test_learned_child_order_does_not_hide_whole_loop_relocation(self):
        a, b = fixture.expression('unique_a'), fixture.expression('unique_b')
        loop = ('<while>while <condition>(<expr><name>ready</name></expr>)</condition>'
                '<block>{<block_content>' + a + TARGET + b + '</block_content>}</block></while>')
        # Another target occurrence activates repeated-child correspondence.
        other = ('<block>{<block_content>' + fixture.run('delete', [TARGET]) +
                 fixture.run('insert', [TARGET]) + '</block_content>}</block>')
        body = (fixture.run('delete', [loop]) + fixture.expression('flush_results') +
                fixture.run('insert', [loop]) + other)
        payload = fixture.evaluate(self, same_file(body))
        self.assertTrue(any(
            any(text.startswith('while') and TARGET_TEXT in text
                for text in move['from_raw_texts']) or
            (TARGET_TEXT in move['from_raw_texts'] and
             any('/src:while[' in path for path in move['from_xpaths']))
            for move in payload['moves']))

    def test_learned_same_kind_block_map_does_not_hide_real_transfer(self):
        a, b = fixture.expression('unique_a'), fixture.expression('unique_b')
        c, d = fixture.expression('unique_c'), fixture.expression('unique_d')
        block = lambda body: '<block>{<block_content>' + body + '</block_content>}</block>'
        origin = block(fixture.run('delete', [a, TARGET, b]))
        destination = block(fixture.run('insert', [a, TARGET, b]))
        stationary = block(fixture.run('delete', [c, TARGET, d]) +
                           fixture.run('insert', [c, TARGET, d]))
        # Both block shells continue, so no wholly changed enclosing construct
        # can mask a lost child report. The transfer crosses the common flush.
        body = origin + fixture.expression('flush_results') + destination + stationary
        payload = fixture.evaluate(self, same_file(body))
        moves = self.moved_targets(payload)
        self.assertEqual(len(moves), 1)
        self.assertEqual(moves[0]['from_raw_texts'], [TARGET_TEXT])
        self.assertEqual(moves[0]['to_raw_texts'], [TARGET_TEXT])

    def test_reorder_past_continuing_conditional_with_edited_body_is_retained(self):
        edited_body = (fixture.expression('flush_results') +
                       fixture.run('insert', [fixture.expression('new_body_work')]))
        conditional = ('<if_stmt><if>if <condition>(<expr><name>ready</name></expr>)'
                       '</condition><block>{<block_content>' + edited_body +
                       '</block_content>}</block></if></if_stmt>')
        body = fixture.run('delete', [TARGET]) + conditional + fixture.run('insert', [TARGET])
        self.assert_single_target(same_file(body))

    def test_unresolved_deleted_origin_prevents_residual_copy_provenance_claim(self):
        unique = fixture.expression('unique_origin_context')
        xml = fixture.PREFIX.replace('before.cpp|after.cpp', 'same.cpp')
        xml += function(fixture.run('delete', [TARGET, unique]) +
                        fixture.run('insert', [TARGET, unique]) +
                        fixture.expression('flush_results'), 'continuing_origin')
        xml += function(fixture.run('delete', [TARGET]), 'other_origin')
        xml += function(fixture.run('insert', [TARGET]), 'unknown_destination') + '</unit>'
        payload = fixture.evaluate(self, xml)
        self.assertFalse(any(move['selection_reason'] == 'continuing_source_copy'
                             for move in self.moved_targets(payload)))


if __name__ == '__main__':
    unittest.main()
