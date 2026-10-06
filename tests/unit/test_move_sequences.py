"""Semantic contracts for additive, order-preserving move sequence reporting.

These are paired endpoint examples, not a claim about developer editing actions.
The five-declaration case reduces the retained OpenCV JacobiSVDImpl_ transfer to
its first unchanged declaration run, deliberately omitting its edited parent.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from benchmarking.tooling import find_srcmove

PREFIX = '<unit xmlns="http://www.srcML.org/srcML/src" xmlns:diff="http://www.srcML.org/srcDiff" xmlns:cpp="http://www.srcML.org/srcML/cpp" language="C++" filename="before.cpp|after.cpp">'


def decl(name: str) -> str:
    return f'<decl_stmt><decl><type><name>int</name></type> <name>{name}</name> <init>= <expr><literal type="number">1</literal></expr></init></decl>;</decl_stmt>'


def expression(name: str) -> str:
    return f'<expr_stmt><expr><call><name>{name}</name><argument_list>(<argument><expr><name>state</name></expr></argument>)</argument_list></call></expr>;</expr_stmt>'


def run(side: str, nodes: list[str], *, fragmented: bool = True) -> str:
    if fragmented:
        return ''.join(f'<diff:{side}>{node}</diff:{side}>\n' for node in nodes)
    return f'<diff:{side}>' + '\n'.join(nodes) + f'</diff:{side}>'


def document(before: list[str], after: list[str]) -> str:
    return PREFIX + run('delete', before) + run('insert', after) + '</unit>'


class MoveSequenceTests(unittest.TestCase):
    def evaluate(self, xml: str, *, fragment: bool = False) -> dict:
        binary = find_srcmove(REPO_ROOT, None)
        self.assertIsNotNone(binary)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = root / 'input.xml'
            fixture.write_text(xml)
            payloads, annotations = [], []
            for mode in ('ordinary', 'diagnostic', 'results_only'):
                result_path, output = root / f'{mode}.json', root / f'{mode}.xml'
                command = [str(binary), str(fixture)]
                if mode != 'results_only':
                    command.append(str(output))
                command += ['--results', str(result_path)]
                if mode != 'ordinary':
                    command.append('--diagnostics')
                if mode == 'results_only':
                    command.append('--results-only')
                if fragment:
                    command += ['--min-granularity', 'fragment']
                completed = subprocess.run(command, capture_output=True, text=True)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                payloads.append(json.loads(result_path.read_text()))
                if mode != 'results_only':
                    annotations.append(output.read_bytes())
            self.assertEqual(annotations[0], annotations[1])
            self.assertEqual(payloads[1], payloads[2])
            ordinary = dict(payloads[1])
            ordinary.pop('diagnostics')
            self.assertEqual(ordinary, payloads[0])
            payload = payloads[0]
            self.assertEqual(payload['move_group_count'], len(payload['moves']))
            self.assertEqual(payload['sequence_cluster_count'], len(payload['move_sequences']))
            saved = sum(len(s['member_move_ids']) - 1 for s in payload['move_sequences'])
            self.assertEqual(payload['sequence_reporting_unit_count'], len(payload['moves']) - saved)
            reports = payload['reported_moves']
            self.assertEqual(payload['reported_move_count'], len(reports))
            self.assertEqual(len(reports), payload['sequence_reporting_unit_count'])
            atomic_by_id = {move['move_id']: move for move in payload['moves']}
            reported_members = [mid for report in reports for mid in report['member_move_ids']]
            self.assertCountEqual(reported_members, atomic_by_id)
            self.assertEqual(len(reported_members), len(set(reported_members)))
            for report in reports:
                members = [atomic_by_id[mid] for mid in report['member_move_ids']]
                self.assertEqual(report['report_kind'],
                                 'ordered_sequence' if len(members) > 1 else 'atomic')
                for field in ('from_xpaths', 'to_xpaths', 'from_raw_texts', 'to_raw_texts'):
                    self.assertEqual(report[field], [item for member in members for item in member[field]])
                self.assertTrue(all(member['content_relationship'] == report['content_relationship']
                                    for member in members))
                if len(members) > 1:
                    self.assertEqual(report['content_relationship'], 'type1')
                    self.assertEqual(len(report['from_xpaths']), len(members))
                    self.assertEqual(len(report['to_xpaths']), len(members))
                    self.assertTrue(report['move_id'].startswith('sequence:'))
                else:
                    self.assertEqual(report['move_id'], members[0]['move_id'])
            self.assertEqual(payload['reported_content_relationships'], {
                kind: sum(report['content_relationship'] == kind for report in reports)
                for kind in ('type1', 'type2c', 'type3')
            })
            atomic_ids = {m['move_id'] for m in payload['moves']}
            used = []
            for sequence in payload['move_sequences']:
                self.assertGreaterEqual(len(sequence['member_move_ids']), 2)
                self.assertEqual(sequence['content_relationship'], 'type1')
                self.assertEqual(sequence['policy'], 'ordered_adjacent_v1')
                used.extend(sequence['member_move_ids'])
                for side in ('from', 'to'):
                    endpoint = sequence[side]
                    self.assertEqual(endpoint['last_child_ordinal'] - endpoint['first_child_ordinal'] + 1,
                                     len(sequence['member_move_ids']))
                    self.assertEqual(len(endpoint['member_xpaths']), len(sequence['member_move_ids']))
                    expected_paths = [next(m for m in payload['moves'] if m['move_id'] == mid)[side + '_xpaths'][0]
                                      for mid in sequence['member_move_ids']]
                    self.assertEqual(endpoint['member_xpaths'], expected_paths)
                    self.assertTrue(endpoint['revision_file'])
                    self.assertTrue(endpoint['parent_id'])
            self.assertEqual(len(used), len(set(used)))
            self.assertTrue(set(used) <= atomic_ids)
            # Every original endpoint remains annotated with its atomic ID.
            tree = ET.fromstring(annotations[0])
            mv = '{http://www.srcML.org/srcMove}id'
            annotated = {node.attrib[mv] for node in tree.iter() if mv in node.attrib}
            self.assertEqual(annotated, atomic_ids)
            self.assertFalse(any(value.startswith('sequence:') for value in annotated))
            return payload

    def assert_runs(self, payload: dict, expected: list[list[str]]) -> None:
        moves = {m['move_id']: m for m in payload['moves']}
        observed = [[moves[mid]['from_raw_texts'][0] for mid in seq['member_move_ids']]
                    for seq in payload['move_sequences']]
        self.assertEqual(observed, expected)

    def test_five_adjacent_declarations_preserve_five_atomic_moves(self):
        # Same ordering and sibling boundaries as the retained OpenCV example.
        names = ['vblas', 'Wbuf', 'W', 'iteration', 'rotation']
        nodes = [decl(name) for name in names]
        payload = self.evaluate(document(nodes, nodes))
        self.assertEqual(payload['move_group_count'], 5)
        self.assertEqual(payload['move_count'], 5)
        self.assertEqual(payload['move_pair_count'], 5)
        self.assertEqual(payload['annotated_region_count'], 10)
        self.assert_runs(payload, [[f'int {name} = 1;' for name in names]])
        self.assertEqual(payload['sequence_reporting_unit_count'], 1)
        self.assertEqual(payload['reported_move_count'], 1)
        self.assertEqual(len(payload['reported_moves'][0]['member_move_ids']), 5)

    def test_partial_source_run_reports_only_shared_middle(self):
        before = [decl(name) for name in 'abcdefg']
        after = [decl(name) for name in 'cdef']
        payload = self.evaluate(document(before, after))
        self.assert_runs(payload, [[f'int {name} = 1;' for name in 'cdef']])
        compound = [report for report in payload['reported_moves']
                    if report['report_kind'] == 'ordered_sequence']
        self.assertEqual(len(compound), 1)
        self.assertEqual(compound[0]['from_raw_texts'], [f'int {name} = 1;' for name in 'cdef'])

    def test_overlapping_runs_report_only_shared_suffix_prefix(self):
        payload = self.evaluate(document([decl(name) for name in 'abcdefg'],
                                         [decl(name) for name in 'efghij']))
        self.assert_runs(payload, [[f'int {name} = 1;' for name in 'efg']])

    def test_cyclic_reordering_keeps_ordered_pair_and_singleton(self):
        a, b, c = [decl(name) for name in ('a', 'b', 'c')]
        payload = self.evaluate(document([a, b, c], [c, a, b]))
        self.assertEqual(payload['move_group_count'], 3)
        self.assert_runs(payload, [['int a = 1;', 'int b = 1;']])
        self.assertEqual(payload['sequence_reporting_unit_count'], 2)

    def test_mixed_child_kinds_and_fragmented_diff_wrappers(self):
        nodes = [decl('state'), expression('consume')]
        payload = self.evaluate(document(nodes, nodes))
        self.assertEqual(payload['move_group_count'], 2)
        self.assert_runs(payload, [['int state = 1;', 'consume(state);']])

    def test_unchanged_child_gap_breaks_adjacency(self):
        a, b = decl('a'), decl('b')
        xml = PREFIX + run('delete', [a]) + '<diff:common>' + decl('anchor') + '</diff:common>'
        xml += run('delete', [b]) + run('insert', [a, b]) + '</unit>'
        payload = self.evaluate(xml)
        self.assertEqual(payload['move_group_count'], 2)
        self.assert_runs(payload, [])

    def test_unmatched_child_gap_breaks_adjacency(self):
        a, b = decl('a'), decl('b')
        payload = self.evaluate(document([a, expression('removed_only'), b], [a, b]))
        self.assertEqual(payload['move_group_count'], 2)
        self.assert_runs(payload, [])

    def test_different_structural_parents_do_not_join(self):
        a, b = decl('a'), decl('b')
        block = lambda node: '<block>{<block_content>' + node + '</block_content>}</block>'
        payload = self.evaluate(document([block(a), block(b)], [a, b]))
        self.assertEqual(payload['move_group_count'], 2)
        self.assert_runs(payload, [])

    def test_repeated_group_does_not_choose_ordered_partners(self):
        a, b = decl('repeat'), decl('unique')
        payload = self.evaluate(document([a, a, b], [a, a, b]))
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
        self.assert_runs(payload, [['int repeat = 1;', 'int unique = 1;']])

    def test_filtered_destination_child_gap_does_not_join(self):
        a, b = decl('a'), decl('b')
        short = '<return>return;</return>'
        payload = self.evaluate(document([a, b], [a, short, b]))
        self.assertEqual(payload['move_group_count'], 2)
        self.assert_runs(payload, [])

    def test_full_reversal_has_no_order_preserving_run(self):
        nodes = [decl(n) for n in ('a', 'b', 'c')]
        payload = self.evaluate(document(nodes, list(reversed(nodes))))
        self.assertEqual(payload['move_group_count'], 3)
        self.assert_runs(payload, [])

    def test_comments_and_whitespace_are_transparent(self):
        a, b = decl('a'), decl('b')
        comment = '<comment type="line">// retained explanation</comment>\n'
        before = run('delete', [a]) + comment + run('delete', [b])
        after = run('insert', [a]) + comment + run('insert', [b])
        payload = self.evaluate(PREFIX + before + after + '</unit>')
        self.assertEqual(payload['move_group_count'], 2)
        self.assert_runs(payload, [['int a = 1;', 'int b = 1;']])

    def test_preprocessor_directive_between_members_is_a_barrier(self):
        a, b = decl('a'), decl('b')
        directive = '<cpp:pragma>#pragma optimize("", off)</cpp:pragma>\n'
        before = run('delete', [a]) + directive + run('delete', [b])
        payload = self.evaluate(PREFIX + before + run('insert', [a, b]) + '</unit>')
        self.assertEqual(payload['move_group_count'], 2)
        self.assert_runs(payload, [])

    def test_preprocessor_directive_inside_member_is_a_barrier(self):
        a = decl('a')
        b = decl('b').replace('<name>b</name>',
            '\n<cpp:if>#if FLAG</cpp:if>\n<name>b</name>\n<cpp:endif>#endif</cpp:endif>\n')
        payload = self.evaluate(document([a, b], [a, b]))
        self.assertEqual(payload['move_group_count'], 2)
        self.assert_runs(payload, [])

    def test_nonwhitespace_direct_sibling_text_is_a_barrier(self):
        a, b = decl('a'), decl('b')
        before = run('delete', [a]) + 'unrepresented();\n' + run('delete', [b])
        payload = self.evaluate(PREFIX + before + run('insert', [a, b]) + '</unit>')
        self.assertEqual(payload['move_group_count'], 2)
        self.assert_runs(payload, [])

    def test_empty_opposite_revision_wrapper_inside_member_is_a_barrier(self):
        a, b = decl('a'), decl('b')
        before_b = b.replace('<name>b</name>', '<name>b</name><diff:insert/>')
        payload = self.evaluate(document([a, before_b], [a, b]))
        self.assertEqual(payload['move_group_count'], 2)
        self.assert_runs(payload, [])

    def test_separate_revision_files_do_not_join(self):
        # One source run fans out to distinct destination units.
        xml = PREFIX.replace(' filename="before.cpp|after.cpp"', '')
        xml += '<unit filename="before.cpp|first.cpp">' + run('delete', [decl('a'), decl('b')])
        xml += run('insert', [decl('a')]) + '</unit>'
        xml += '<unit filename="|second.cpp">' + run('insert', [decl('b')]) + '</unit></unit>'
        payload = self.evaluate(xml)
        self.assertEqual(payload['move_group_count'], 2)
        self.assert_runs(payload, [])


if __name__ == '__main__':
    unittest.main()
