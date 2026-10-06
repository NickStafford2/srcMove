"""Readable source scenarios with independent named occurrence expectations.

The small XML scenarios retain reviewed diff encodings. Their source files are
checked against both XML revisions, so the readable example is the actual input.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from benchmarking.tooling import find_srcdiff
from tests.support import behavior
from tests.support.annotations import revision_text
from tests.support.execution import artifact_directory, execute_xml, require_success, require_tool, run_logged
from tests.support.validation import xpaths_to_files

ROOT = Path(__file__).resolve().parents[1] / 'fixtures' / 'scenarios'
SRC = '{http://www.srcML.org/srcML/src}'
DIFF = '{http://www.srcML.org/srcDiff}'
MV = '{http://www.srcML.org/srcMove}'
NAMESPACES = {'src': SRC[1:-1], 'diff': DIFF[1:-1]}


def _tokens(source):
    # Keep identifiers and literals intact while ignoring layout differences.
    return re.findall(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|[A-Za-z_]\w*|\d+|[^\s]', source)


def validate_source_views(directory, xml):
    """Reject readable source examples that disagree with the retained XML."""
    root = ET.fromstring(xml)
    # The original tiny XML builder omitted the separator between void and
    # worker. Supply it for source rendering, without changing detector input.
    for function in root.iter(SRC + 'function'):
        type_node = function.find(SRC + 'type')
        if type_node is not None and not type_node.tail:
            type_node.tail = ' '
    for side, revision in (('before', 'delete'), ('after', 'insert')):
        source = (directory / (side + '.cpp')).read_text()
        projected = revision_text(root, revision)
        if _tokens(source) != _tokens(projected):
            raise ValueError(f'{directory.name}: {side}.cpp disagrees with input.srcdiff.xml')


def _input_locations(xml):
    """Index input nodes by structural paths, independent of detector output."""
    root = ET.fromstring(xml)
    locations = []

    def visit(node, path, revision='common', condition=None):
        if node.tag in (DIFF + 'delete', DIFF + 'insert', DIFF + 'common'):
            revision = node.tag[len(DIFF):]
        if node.tag == SRC + 'while':
            condition = ''.join(node.find(SRC + 'condition').itertext()).strip('()')
        if node.tag == SRC + 'expr_stmt':
            locations.append((revision, condition, ''.join(node.itertext()), path))
        ordinals = Counter()
        for child in node:
            ordinals[child.tag] += 1
            prefix = 'src' if child.tag.startswith(SRC) else 'diff'
            local = child.tag.split('}', 1)[1]
            if child.tag == SRC + 'function':
                name = child.find(SRC + 'name').text
                selector = f"[src:name='{name}']"
            else:
                selector = f'[{ordinals[child.tag]}]'
            visit(child, path + '/' + prefix + ':' + local + selector, revision, condition)

    visit(root, '/src:unit[1]')
    return locations


class Scenario:
    def __init__(self, testcase, observation, xml):
        self.testcase = testcase
        self.observation = observation
        self.payloads = [mode.payload() for mode in observation.modes]
        self.payload = next((payload for mode, payload in zip(observation.modes, self.payloads)
                             if mode.name == 'diagnostic'), self.payloads[0])
        self.locations = _input_locations(xml)
        self.expected_annotations = []
        self.expected_copy_count = 0

    def _occurrences(self, names, revision):
        occurrences = []
        self.testcase.assertEqual(len(names), len(set(names)), 'Expected occurrence names must be distinct')
        for name in names:
            condition, call = name.split('.', 1)
            text = call + '(state);'
            matches = [(path, text) for side, loop, actual, path in self.locations
                       if side == revision and loop == condition and actual == text]
            self.testcase.assertEqual(len(matches), 1,
                                      f'{revision} occurrence {name!r} must identify exactly one input statement')
            occurrences.extend(matches)
        return occurrences

    def _expect_group(self, origins, destinations, *, relationship, reason=None):
        expected_from = self._occurrences(origins, 'delete')
        expected_to = self._occurrences(destinations, 'insert')
        matches = [move for move in self.payload['moves']
                   if Counter(move['from_xpaths']) == Counter(path for path, _ in expected_from)
                   and Counter(move['to_xpaths']) == Counter(path for path, _ in expected_to)]
        test = self.testcase
        test.assertEqual(len(matches), 1, f'Expected one group from {origins} to {destinations}')
        move = matches[0]
        test.assertNotIn(move['move_id'], [move_id for move_id, _ in self.expected_annotations],
                         'Each expected group must be distinct')
        test.assertEqual(move['content_relationship'], relationship)
        test.assertCountEqual(move['from_raw_texts'], [text for _, text in expected_from])
        test.assertCountEqual(move['to_raw_texts'], [text for _, text in expected_to])
        if reason is not None:
            test.assertEqual(move['selection_reason'], reason)
        self.expected_annotations.append((move['move_id'], [path for path, _ in expected_from + expected_to]))
        return move

    def expect_copy_group(self, *, origins, destinations, relationship, reason):
        self._expect_group(origins, destinations, relationship=relationship, reason=reason)
        self.expected_copy_count += 1

    def expect_move(self, *, origin, destination, relationship):
        self._expect_group([origin], [destination], relationship=relationship)

    def expect_group_count(self, count):
        self.testcase.assertEqual(self.payload['move_group_count'], count)
        if self.expected_copy_count:
            self.testcase.assertEqual(self.payload['group_kinds']['copy_or_repeat'], self.expected_copy_count)

    def expect_no_sequences(self):
        self.testcase.assertEqual(self.payload['move_sequences'], [])

    def expect_atomic_reports(self, count):
        self.testcase.assertEqual(self.payload['reported_move_count'], count)
        self.testcase.assertTrue(all(report['report_kind'] == 'atomic'
                                     for report in self.payload['reported_moves']))

    def expect_relocated_declaration(self, filename, text):
        test, payload = self.testcase, self.payload
        candidates = {item['candidate_id']: item for item in payload['diagnostics']['candidates']}
        pairs = [pair for pair in payload['diagnostics']['correspondences']
                 if pair['correspondence_kind'] == 'type1'
                 and candidates[pair['delete_candidate_id']]['construct'] == 'decl_stmt'
                 and candidates[pair['insert_candidate_id']]['construct'] == 'decl_stmt'
                 and candidates[pair['delete_candidate_id']]['raw_text'] == text
                 and candidates[pair['insert_candidate_id']]['raw_text'] == text]
        test.assertEqual(len(pairs), 1, 'srcDiff must expose one exact declaration pair')
        test.assertEqual(pairs[0]['before_context']['revision_file'], filename)
        test.assertEqual(pairs[0]['after_context']['revision_file'], filename)
        test.assertEqual(pairs[0]['shadow_change'], 'relocated')
        moves = [move for move in payload['moves'] if move['from_raw_texts'] == [text]]
        test.assertEqual(len(moves), 1)
        move = moves[0]
        test.assertEqual(move['content_relationship'], 'type1')
        test.assertEqual(move['to_raw_texts'], [text])
        test.assertEqual(xpaths_to_files(move['from_xpaths']), [filename])
        test.assertEqual(xpaths_to_files(move['to_xpaths']), [filename])

    def assert_annotation_locations(self, xml):
        """Check actual annotated nodes, including exclusion of same-text copies."""
        root = ET.fromstring(xml)
        expected_nodes = set()
        for move_id, paths in self.expected_annotations:
            for path in paths:
                nodes = root.findall('.' + path.removeprefix('/src:unit[1]'), NAMESPACES)
                self.testcase.assertEqual(len(nodes), 1, path)
                self.testcase.assertEqual(nodes[0].get(MV + 'id'), move_id, path)
                expected_nodes.add(nodes[0])
        actual_nodes = {node for node in root.iter() if MV + 'id' in node.attrib}
        self.testcase.assertEqual(actual_nodes, expected_nodes,
                                  'Only independently expected occurrences may be annotated')

    def assert_output_contracts(self):
        self.testcase.assertEqual(tuple(mode.name for mode in self.observation.modes),
                                  ('ordinary', 'diagnostic', 'results_only'))
        annotations = [mode.output_xml.read_bytes() for mode in self.observation.modes
                       if mode.output_xml is not None]
        behavior.assert_output_invariants(self.testcase, self.payloads, annotations)
        if self.expected_annotations:
            self.assert_annotation_locations(annotations[0])


def load_scenario(testcase, name, *, modes=('diagnostic',)):
    directory = ROOT / name
    xml_path = directory / 'input.srcdiff.xml'
    if xml_path.is_file():
        xml = xml_path.read_bytes()
        validate_source_views(directory, xml)
    else:
        srcdiff = find_srcdiff(behavior.REPO_ROOT)
        require_tool(srcdiff)
        with artifact_directory(case_id=testcase.id()) as artifacts:
            xml_path = artifacts / 'srcdiff.xml'
            completed = run_logged([str(srcdiff), str(directory / 'before'),
                                    str(directory / 'after'), '-o', str(xml_path)],
                                   cwd=behavior.REPO_ROOT, capture_output=True, text=True)
            require_success(completed)
            xml = xml_path.read_bytes()
            ET.fromstring(xml)
    observation = execute_xml(xml, case_id=testcase.id(), modes=modes)
    return Scenario(testcase, observation, xml)
