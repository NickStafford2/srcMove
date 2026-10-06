"""Displacement needs a shared mapped sibling, rather than function-wide order."""
from __future__ import annotations
from tests.support.execution import require_success, require_tool

import json
from pathlib import Path
import sys
from tests.support.execution import artifact_directory, run_logged
import unittest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from benchmarking.tooling import find_srcmove

PREFIX = '<unit xmlns="http://www.srcML.org/srcML/src" xmlns:diff="http://www.srcML.org/srcDiff" language="C++" filename="same.cpp">'
TARGET_TEXT = 'int target = source + 17;'
TARGET = '<decl_stmt><decl><type><name>int</name></type> <name>target</name> <init>= <expr><name>source</name> <operator>+</operator> <literal type="number">17</literal></expr></init></decl>;</decl_stmt>'


def side(kind: str, text: str) -> str:
    return f'<diff:{kind}>{text}</diff:{kind}>'


def call(name: str) -> str:
    return f'<expr_stmt><expr><call><name>{name}</name><argument_list>()</argument_list></call></expr>;</expr_stmt>'


def block(body: str) -> str:
    return '<block>{<block_content>' + body + '</block_content>}</block>'


def conditional(body: str, name: str = 'ready') -> str:
    return '<if_stmt><if>if <condition>(<expr><name>' + name + '</name></expr>)</condition>' + block(body) + '</if></if_stmt>'


def loop(body: str) -> str:
    return '<while>while <condition>(<expr><name>running</name></expr>)</condition>' + block(body) + '</while>'


def document(body: str) -> str:
    return PREFIX + '<function><type><name>void</name></type> <name>work</name><parameter_list>()</parameter_list>' + block(body) + '</function></unit>'


class AnchorCrossingTests(unittest.TestCase):
    def evaluate(self, body: str) -> dict:
        binary = find_srcmove(REPO_ROOT, None)
        require_tool(binary)
        with artifact_directory(case_id=self.id()) as directory:
            root = Path(directory)
            fixture = root / 'input.xml'
            fixture.write_text(document(body))
            result = root / 'results.json'
            completed = run_logged(
                [str(binary), str(fixture), '--results-only', '--results',
                 str(result), '--diagnostics'], capture_output=True, text=True)
            require_success(completed)
            return json.loads(result.read_text())

    def target_moves(self, body: str) -> list[dict]:
        return [move for move in self.evaluate(body)['moves']
                if TARGET_TEXT in move['from_raw_texts']]

    def test_call_is_a_shared_crossed_sibling(self):
        self.assertEqual(len(self.target_moves(side('delete', TARGET) +
                         call('checkpoint') + side('insert', TARGET))), 1)

    def test_crossing_several_siblings_does_not_require_equal_neighbors(self):
        self.assertEqual(len(self.target_moves(side('delete', TARGET) +
                         call('first') + call('second') + call('third') +
                         side('insert', TARGET))), 1)

    def test_nested_wholly_common_conditional_is_a_sibling_boundary(self):
        anchor = conditional(conditional(call('checkpoint'), 'inner'), 'outer')
        self.assertEqual(len(self.target_moves(side('delete', TARGET) + anchor +
                         side('insert', TARGET))), 1)

    def test_common_loop_retains_its_own_crossing_evidence(self):
        self.assertEqual(len(self.target_moves(loop(side('delete', TARGET) +
                         call('checkpoint') + side('insert', TARGET)))), 1)

    def test_whole_loop_crosses_a_common_control_with_an_edited_body(self):
        body = (side('delete', loop(TARGET)) +
                conditional(call('unrelated_checkpoint') + side('insert', call('added'))) +
                side('insert', loop(TARGET)))
        result = self.evaluate(body)
        self.assertTrue(any('while (running)' in text
                            for move in result['moves']
                            for text in move['from_raw_texts']))

    def test_unchanged_control_header_anchors_an_edited_body(self):
        mixed = conditional(call('checkpoint') + side('insert', call('added')))
        self.assertEqual(len(self.target_moves(side('delete', TARGET) + mixed +
                         side('insert', TARGET))), 1)

    def test_changed_control_header_does_not_borrow_body_anchors(self):
        changed = ('<if_stmt><if>if <condition>(<expr>' +
                   side('delete', '<name>old_ready</name>') +
                   side('insert', '<name>new_ready</name>') +
                   '</expr>)</condition>' + block(call('checkpoint')) +
                   '</if></if_stmt>')
        self.assertEqual(self.target_moves(side('delete', TARGET) + changed +
                         side('insert', TARGET)), [])

    def test_different_common_blocks_provide_real_displacement(self):
        body = (conditional(side('delete', TARGET), 'left') +
                conditional(side('insert', TARGET), 'right'))
        self.assertEqual(len(self.target_moves(body)), 1)

    def test_added_exclusive_wrapper_is_restructuring(self):
        body = side('delete', TARGET) + side('insert', conditional(TARGET))
        self.assertEqual(self.target_moves(body), [])

    def test_removed_else_wrapper_around_a_common_control_is_unwrapping(self):
        body = ('<if_stmt><if>if <condition>(<expr><name>ready</name>' +
                '</expr>)</condition>' + block(call('checkpoint')) + '</if>' +
                side('delete', '<else>else' + block(TARGET) + '</else>') +
                '</if_stmt>' + side('insert', TARGET))
        result = self.evaluate(body)
        candidates = {item['candidate_id']: item
                      for item in result['diagnostics']['candidates']}
        correspondence = next(
            item for item in result['diagnostics']['correspondences']
            if candidates[item['delete_candidate_id']]['raw_text'] == TARGET_TEXT)
        self.assertEqual(correspondence['shadow_change'], 'restructured')
        self.assertEqual(correspondence['classification_reason'], 'ancestor_unwrapped')
        self.assertEqual(self.target_moves(body), [])

    def test_repeated_common_calls_do_not_supply_unique_crossing(self):
        body = (side('delete', TARGET) + call('checkpoint') + call('checkpoint') +
                side('insert', TARGET))
        self.assertEqual(self.target_moves(body), [])


if __name__ == '__main__':
    unittest.main()
