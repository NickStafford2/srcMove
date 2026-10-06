"""Small XML builders and output invariants shared by detector behavior tests.

Semantic expectations remain in each test. These checks only establish output
mode agreement, conservation, report membership, and annotation consistency.
"""
from __future__ import annotations
from tests.support.execution import require_success, require_tool

import xml.etree.ElementTree as ET

from tests.support.annotations import validate_annotations
from tests.support.execution import REPO_ROOT, execute_xml

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



def evaluate(self, xml: str, *, fragment: bool = False) -> dict:
    observation = execute_xml(xml, case_id=self.id(),
                              min_granularity="fragment" if fragment else None)
    payloads, annotations = [], []
    for mode in observation.modes:
        require_success(mode.completed)
        payloads.append(mode.payload())
        if mode.output_xml is not None:
            annotations.append(mode.output_xml.read_bytes())
    return assert_output_invariants(self, payloads, annotations)


def assert_output_invariants(self, payloads: list[dict], annotations: list[bytes]) -> dict:
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
    validate_annotations(annotations[0], payload['moves'])
    return payload


def assert_runs(self, payload: dict, expected: list[list[str]]) -> None:
    moves = {m['move_id']: m for m in payload['moves']}
    observed = [[moves[mid]['from_raw_texts'][0] for mid in seq['member_move_ids']]
                for seq in payload['move_sequences']]
    self.assertEqual(observed, expected)

