"""Unchanged expression statements provide movement location evidence."""
from __future__ import annotations

import unittest

from tests.support import behavior as fixture


CALL = ('<expr_stmt><expr><call><name>flush_results</name>'
        '<argument_list>()</argument_list></call></expr>;</expr_stmt>')
DECL = fixture.decl('payload').replace('>1</literal>', '>109</literal>')


class ExpressionAnchorTests(unittest.TestCase):
    def evaluate(self, body: str) -> dict:
        xml = fixture.PREFIX.replace('before.cpp|after.cpp', 'same.cpp')
        xml += ('<function><type><name>void</name></type> <name>process</name>'
                '<parameter_list>()</parameter_list><block>{<block_content>'
                + body + '</block_content>}</block></function></unit>')
        return fixture.evaluate(self, xml)

    def moved(self, payload: dict) -> list[dict]:
        return [move for move in payload['moves']
                if 'int payload = 109;' in move['from_raw_texts']]

    def test_crossing_unique_unchanged_call_reports_move(self):
        payload = self.evaluate(f'<diff:delete>{DECL}</diff:delete>{CALL}'
                                f'<diff:insert>{DECL}</diff:insert>')
        self.assertEqual(len(self.moved(payload)), 1)
        self.assertEqual(self.moved(payload)[0]['content_relationship'], 'type1')

    def test_same_side_of_call_remains_stationary(self):
        payload = self.evaluate(f'{CALL}<diff:delete>{DECL}</diff:delete>'
                                f'<diff:insert>{DECL}</diff:insert>')
        self.assertEqual(self.moved(payload), [])

    def test_repeated_calls_cannot_establish_crossing(self):
        payload = self.evaluate(f'{CALL}<diff:delete>{DECL}</diff:delete>{CALL}'
                                f'<diff:insert>{DECL}</diff:insert>')
        self.assertEqual(self.moved(payload), [])

    def test_edited_call_cannot_establish_crossing(self):
        mixed = CALL.replace('<name>flush_results</name>',
                             '<diff:delete><name>flush_results</name></diff:delete>'
                             '<diff:insert><name>flush_new</name></diff:insert>')
        payload = self.evaluate(f'<diff:delete>{DECL}</diff:delete>{mixed}'
                                f'<diff:insert>{DECL}</diff:insert>')
        self.assertEqual(self.moved(payload), [])


if __name__ == '__main__':
    unittest.main()
