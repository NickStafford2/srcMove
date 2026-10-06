"""Unresolved exact groups need positive displacement evidence, not pair identity."""
from __future__ import annotations

import unittest

from tests.unit import test_move_sequences as fixture

REPEAT = fixture.expression('repeat_work')
SAME_FILE = fixture.PREFIX.replace('before.cpp|after.cpp', 'same.cpp')


def function(name: str, body: str) -> str:
    return ('<function><type><name>void</name></type> <name>' + name + '</name>'
            '<parameter_list>()</parameter_list><block>{<block_content>' + body +
            '</block_content>}</block></function>')


class RepeatedGroupLocationTests(unittest.TestCase):
    def evaluate(self, xml: str) -> dict:
        # Includes ordinary/diagnostic/results-only parity and annotation checks.
        return fixture.MoveSequenceTests().evaluate(xml)

    def repeated_moves(self, payload: dict) -> list[dict]:
        return [move for move in payload['moves']
                if move['from_raw_texts'] and
                all(text == 'repeat_work(state);' for text in move['from_raw_texts'])]

    def assert_group(self, payload: dict, deletes=2, inserts=2):
        moves = self.repeated_moves(payload)
        self.assertEqual(len(moves), 1)
        self.assertEqual(len(moves[0]['from_xpaths']), deletes)
        self.assertEqual(len(moves[0]['to_xpaths']), inserts)
        # Location supports only the equivalence group, never ordered partners.
        self.assertEqual(payload['move_sequences'], [])
        self.assertEqual(moves[0]['selection_reason'], 'greedy_utility')

    def test_same_file_unmapped_repeated_endpoints_are_withheld(self):
        xml = fixture.document([REPEAT, REPEAT], [REPEAT, REPEAT])
        payload = self.evaluate(xml.replace('before.cpp|after.cpp', 'same.cpp'))
        self.assertEqual(self.repeated_moves(payload), [])
        self.assertEqual(payload['move_group_count'], 0)

    def test_same_mapped_container_interval_repeated_endpoints_are_withheld(self):
        body = fixture.run('delete', [REPEAT, REPEAT]) + fixture.run('insert', [REPEAT, REPEAT])
        payload = self.evaluate(SAME_FILE + function('worker', body) + '</unit>')
        self.assertEqual(self.repeated_moves(payload), [])
        self.assertEqual(payload['move_group_count'], 0)

    def test_cross_file_one_to_many_copy_is_retained(self):
        self.assert_group(self.evaluate(fixture.document([REPEAT], [REPEAT, REPEAT])), 1, 2)

    def test_cross_file_many_to_one_repeat_is_retained(self):
        self.assert_group(self.evaluate(fixture.document([REPEAT, REPEAT], [REPEAT])), 2, 1)

    def test_different_mapped_containers_support_unresolved_group(self):
        xml = SAME_FILE + function('origin', fixture.run('delete', [REPEAT, REPEAT]))
        xml += function('destination', fixture.run('insert', [REPEAT, REPEAT])) + '</unit>'
        self.assert_group(self.evaluate(xml))

    def test_varied_source_containers_retain_possible_displacement(self):
        # One source could be stationary; another source is in a different
        # mapped function. Preserve the possible transfer without choosing it.
        origin = fixture.run('delete', [REPEAT]) + fixture.run('insert', [REPEAT])
        xml = SAME_FILE + function('origin', origin)
        xml += function('other', fixture.run('delete', [REPEAT])) + '</unit>'
        self.assert_group(self.evaluate(xml), 2, 1)

    def test_crossed_common_anchor_supports_unresolved_group(self):
        body = fixture.run('delete', [REPEAT, REPEAT]) + fixture.decl('stable_anchor')
        body += fixture.run('insert', [REPEAT, REPEAT])
        self.assert_group(self.evaluate(SAME_FILE + function('worker', body) + '</unit>'))

    def test_unknown_file_cannot_use_container_displacement(self):
        # A present srcML filename keeps this a source unit; old|new with both
        # sides empty deliberately supplies no revision-specific path evidence.
        prefix = SAME_FILE.replace('filename="same.cpp"', 'filename="|"')
        xml = prefix + function('origin', fixture.run('delete', [REPEAT, REPEAT]))
        xml += function('destination', fixture.run('insert', [REPEAT, REPEAT])) + '</unit>'
        payload = self.evaluate(xml)
        self.assertEqual(self.repeated_moves(payload), [])
        self.assertEqual(payload['move_group_count'], 0)


if __name__ == '__main__':
    unittest.main()
