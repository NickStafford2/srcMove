"""Hand-authored alternative XML interaction contracts.

Whole-loop replacements are legal coarse encodings, not assertions about default
srcDiff output. Common markup and regenerated source provide paired controls.
"""
from __future__ import annotations
from tests.support.execution import require_success, require_tool

from pathlib import Path
from tests.support.execution import artifact_directory, run_logged, execute_xml
import unittest
import xml.etree.ElementTree as ET

from benchmarking.tooling import find_srcdiff

from tests.support import behavior as fixture

R = fixture.expression('repeat_work')
TEXT = 'repeat_work(state);'
A, B, C, D = (fixture.expression(name) for name in
               ('unique_a', 'unique_b', 'unique_c', 'unique_d'))
PAD = fixture.expression('padding_work')


def loop(nodes: list[str], condition: str) -> str:
    return ('<while>while<condition>(<expr><name>' + condition +
            '</name></expr>)</condition><block>{<block_content>' +
            ''.join(nodes) + '</block_content>}</block></while>')


def document(body: str) -> str:
    function = ('<function><type><name>void</name></type><name>worker</name>'
                '<parameter_list>()</parameter_list><block>{<block_content>' +
                body + '</block_content>}</block></function>')
    return fixture.PREFIX.replace('before.cpp|after.cpp', 'same.cpp') + function + '</unit>'


class CorrespondenceInteractionTests(unittest.TestCase):
    def evaluate_xml(self, xml):
        observation = execute_xml(xml, case_id=self.id())
        payloads = [mode.payload() for mode in observation.modes]
        annotations = [mode.output_xml.read_bytes() for mode in observation.modes
                       if mode.output_xml is not None]
        self.annotated_root = ET.fromstring(annotations[0])
        return fixture.assert_output_invariants(self, payloads, annotations)

    def evaluate(self, before, after):
        return self.evaluate_xml(document(
            fixture.run('delete', before) + fixture.run('insert', after)))

    def assert_annotation_locations(self, moves):
        # Resolve independently specified JSON paths to the actual XML nodes.
        # Text/link multiplicity alone cannot distinguish identical occurrences.
        namespaces = {'src': 'http://www.srcML.org/srcML/src',
                      'diff': 'http://www.srcML.org/srcDiff'}
        mv_id = '{http://www.srcML.org/srcMove}id'
        expected_nodes = set()
        for move, origins, destinations in moves:
            self.assertCountEqual(move['from_xpaths'], origins)
            self.assertCountEqual(move['to_xpaths'], destinations)
            for path in origins + destinations:
                self.assertTrue(path.startswith('/src:unit[1]/'))
                nodes = self.annotated_root.findall(
                    '.' + path.removeprefix('/src:unit[1]'), namespaces)
                self.assertEqual(len(nodes), 1, path)
                self.assertEqual(nodes[0].get(mv_id), move['move_id'], path)
                expected_nodes.add(nodes[0])
        actual_nodes = {node for node in self.annotated_root.iter() if mv_id in node.attrib}
        self.assertEqual(actual_nodes, expected_nodes,
                         'Only the independently selected occurrences may be annotated')

    def targets(self, payload):
        return [m for m in payload['moves'] if m['from_raw_texts'] == [TEXT] or
                (m['from_raw_texts'] and all(t == TEXT for t in m['from_raw_texts']))]

    def test_two_continuing_origins_preserve_only_added_copy_destination(self):
        payload = self.evaluate([loop([A, B, R], 'first'), loop([C, D, R], 'second')],
                                [loop([A, B, R], 'first'), loop([C, D, R], 'second'),
                                 loop([R], 'new_copy')])
        copies = self.targets(payload)
        self.assertEqual(len(copies), 1)
        copy = copies[0]
        self.assertEqual(copy['selection_reason'], 'continuing_source_copy')
        self.assertEqual(copy['from_raw_texts'], [TEXT, TEXT])
        self.assertEqual(copy['to_raw_texts'], [TEXT])
        self.assertEqual(len(set(copy['from_xpaths'])), 2)
        self.assertEqual({index for index in (1, 2)
                          if any(f'diff:delete[{index}]' in path
                                 for path in copy['from_xpaths'])}, {1, 2})
        self.assertEqual(len(copy['to_xpaths']), 1)
        self.assertIn('diff:insert[3]', copy['to_xpaths'][0])
        self.assertEqual(payload['move_sequences'], [])

    def test_two_continuing_origins_preserve_two_added_copy_destinations(self):
        # Two independent seed pairs establish the continuing origins; the two
        # extra loops supply new destinations, not an arbitrary 2x2 pairing.
        before = [loop([A, B, R], 'first'), loop([C, D, R], 'second')]
        payload = self.evaluate(before, before + [loop([R], 'extra_a'), loop([R], 'extra_b')])
        self.assertEqual(payload['move_group_count'], 1)
        self.assertEqual(payload['group_kinds']['copy_or_repeat'], 1)
        copy = payload['moves'][0]
        self.assertEqual(copy['content_relationship'], 'type1')
        self.assertEqual(copy['selection_reason'], 'continuing_source_copy')
        self.assertEqual(copy['from_raw_texts'], [TEXT, TEXT])
        self.assertEqual(copy['to_raw_texts'], [TEXT, TEXT])
        self.assertEqual(payload['move_sequences'], [])
        base = "/src:unit[1]/src:function[src:name='worker']/src:block[1]/src:block_content[1]/"
        child = '/src:while[1]/src:block[1]/src:block_content[1]/src:expr_stmt'
        origins = [base + f'diff:delete[{index}]' + child + '[3]' for index in (1, 2)]
        destinations = [base + f'diff:insert[{index}]' + child + '[1]' for index in (3, 4)]
        self.assert_annotation_locations([(copy, origins, destinations)])

    def test_adjacent_distinct_copies_keep_separate_provenance_and_no_sequence(self):
        other = fixture.expression('other_repeat')
        before = [loop([A, B, R, other], 'first')]
        payload = self.evaluate(before, before + [loop([R, other], 'extra')])
        self.assertEqual(payload['move_group_count'], 2)
        self.assertEqual(payload['group_kinds']['copy_or_repeat'], 2)
        self.assertEqual(payload['move_sequences'], [])
        self.assertEqual(payload['reported_move_count'], 2)
        self.assertTrue(all(report['report_kind'] == 'atomic' for report in payload['reported_moves']))
        copies = {move['from_raw_texts'][0]: move for move in payload['moves']}
        self.assertEqual(set(copies), {TEXT, 'other_repeat(state);'})
        base = "/src:unit[1]/src:function[src:name='worker']/src:block[1]/src:block_content[1]/"
        child = '/src:while[1]/src:block[1]/src:block_content[1]/src:expr_stmt'
        locations = []
        for text, origin_ordinal, destination_ordinal in ((TEXT, 3, 1), ('other_repeat(state);', 4, 2)):
            copy = copies[text]
            self.assertEqual(copy['content_relationship'], 'type1')
            self.assertEqual(copy['selection_reason'], 'continuing_source_copy')
            self.assertEqual(copy['from_raw_texts'], [text])
            self.assertEqual(copy['to_raw_texts'], [text])
            locations.append((copy,
                [base + 'diff:delete[1]' + child + f'[{origin_ordinal}]'],
                [base + 'diff:insert[2]' + child + f'[{destination_ordinal}]']))
        self.assert_annotation_locations(locations)

    def test_padded_reorder_inside_paired_replaced_loop_remains_a_move(self):
        # Only R crosses A and B. Padding prevents immediate-neighbor seeds
        # from conflating identity with unchanged sibling order.
        before = loop([R, PAD, A, PAD, B, PAD], 'first')
        after = loop([PAD, A, PAD, B, PAD, R], 'first')
        payload = self.evaluate([before, loop([C, D, R], 'second')],
                                [after, loop([C, D, R], 'second')])
        moves = self.targets(payload)
        self.assertEqual(len(moves), 1, 'R crosses two continuing calls in the first loop')
        self.assertEqual(moves[0]['from_raw_texts'], [TEXT])
        self.assertEqual(moves[0]['to_raw_texts'], [TEXT])
        self.assertIn('diff:delete[1]', moves[0]['from_xpaths'][0])
        self.assertIn('diff:insert[1]', moves[0]['to_xpaths'][0])

    def test_padded_stationary_replaced_loops_do_not_claim_moves_or_copies(self):
        loops = [loop([R, PAD, A, PAD, B, PAD], 'first'), loop([C, D, R], 'second')]
        self.assertEqual(self.targets(self.evaluate(loops, loops)), [])

    def test_same_reorder_with_common_loop_structure_has_endpoint_evidence(self):
        first = loop([fixture.run('delete', [R]), PAD, A, PAD, B, PAD,
                      fixture.run('insert', [R])], 'first')
        second = loop([C, D, R], 'second')
        payload = self.evaluate_xml(document(first + second))
        moves = self.targets(payload)
        self.assertEqual(len(moves), 1)
        self.assertEqual(moves[0]['from_raw_texts'], [TEXT])
        self.assertEqual(moves[0]['to_raw_texts'], [TEXT])
        self.assertIn('src:while[1]', moves[0]['from_xpaths'][0])
        self.assertIn('src:while[1]', moves[0]['to_xpaths'][0])
        base = ("/src:unit[1]/src:function[src:name='worker']/src:block[1]/"
                'src:block_content[1]/src:while[1]/src:block[1]/src:block_content[1]/')
        self.assert_annotation_locations([(moves[0],
            [base + 'diff:delete[1]/src:expr_stmt[1]'],
            [base + 'diff:insert[1]/src:expr_stmt[1]'])])

    def test_default_srcdiff_pipeline_preserves_padded_loop_reorder(self):
        before = ('void worker() {\nwhile(first) { repeat_work(state); '
                  'padding_work(state); unique_a(state); padding_work(state); '
                  'unique_b(state); padding_work(state); }\n'
                  'while(second) { unique_c(state); unique_d(state); repeat_work(state); }\n}\n')
        after = ('void worker() {\nwhile(first) { padding_work(state); '
                 'unique_a(state); padding_work(state); unique_b(state); '
                 'padding_work(state); repeat_work(state); }\n'
                 'while(second) { unique_c(state); unique_d(state); repeat_work(state); }\n}\n')
        srcdiff = find_srcdiff(fixture.REPO_ROOT)
        require_tool(srcdiff)
        with artifact_directory(case_id=self.id()) as directory:
            root = Path(directory)
            for side, source in [('before', before), ('after', after)]:
                (root / side).mkdir()
                (root / side / 'source.cpp').write_text(source)
            output = root / 'srcdiff.xml'
            result = run_logged([str(srcdiff), str(root / 'before'), str(root / 'after'),
                                     '-o', str(output)], capture_output=True, text=True)
            require_success(result)
            xml = output.read_text()
        tree = ET.fromstring(xml)
        src, diff = '{http://www.srcML.org/srcML/src}', '{http://www.srcML.org/srcDiff}'
        for side in ('delete', 'insert'):
            targets = [node for wrapper in tree.iter(diff + side)
                       for node in wrapper.iter(src + 'expr_stmt')
                       if ''.join(node.itertext()) == TEXT]
            self.assertEqual(len(targets), 1, 'Upstream must retain the whole reordered statement')
        moves = self.targets(fixture.evaluate(self, xml))
        self.assertEqual(len(moves), 1)
        self.assertEqual(moves[0]['from_raw_texts'], [TEXT])
        self.assertEqual(moves[0]['to_raw_texts'], [TEXT])
        self.assertIn('src:while[1]', moves[0]['from_xpaths'][0])
        self.assertIn('src:while[1]', moves[0]['to_xpaths'][0])

    def assert_no_invented_partial_partner(self, before, after):
        payload = self.evaluate(before, after)
        for move in self.targets(payload):
            self.assertNotEqual(move['selection_reason'], 'continuing_source_copy')
            self.assertNotEqual(move['selection_reason'], 'exact_neighbor_correspondence')
        target_ids = {move['move_id'] for move in self.targets(payload)}
        self.assertTrue(all(target_ids.isdisjoint(sequence['member_move_ids'])
                            for sequence in payload['move_sequences']))

    def test_split_unique_seeds_cannot_establish_one_parent_partner(self):
        self.assert_no_invented_partial_partner(
            [loop([A, PAD, R, PAD, B], 'original'), loop([R], 'other')],
            [loop([A, PAD, R], 'left'), loop([PAD, B, R], 'right')])

    def test_merged_unique_seeds_cannot_establish_two_parent_partners(self):
        self.assert_no_invented_partial_partner(
            [loop([A, PAD, R], 'left'), loop([PAD, B, R], 'right')],
            [loop([A, PAD, R, PAD, B], 'merged'), loop([R], 'other')])

    def test_crossed_unique_seed_order_is_not_stationary_identity_evidence(self):
        self.assert_no_invented_partial_partner(
            [loop([A, PAD, R, PAD, B], 'first'), loop([C, PAD, R, PAD, D], 'second')],
            [loop([B, PAD, R, PAD, A], 'first'), loop([D, PAD, R, PAD, C], 'second')])


if __name__ == '__main__':
    unittest.main()
