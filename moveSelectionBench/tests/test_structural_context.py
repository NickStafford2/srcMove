"""Strict-ancestor context contracts shared by all three evidence classes."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from benchmarking.tooling import find_srcmove

SRC = '{http://www.srcML.org/srcML/src}'
DIFF = '{http://www.srcML.org/srcDiff}'


class StructuralContextTests(unittest.TestCase):
    def test_strict_ancestors_across_evidence_classes(self):
        fixture = ET.parse(ROOT / 'moveSelectionBench/type3_cases/stationary_edit.xml')
        before = fixture.find('.//' + DIFF + 'delete/' + SRC + 'if_stmt')
        edited = fixture.find('.//' + DIFF + 'insert/' + SRC + 'if_stmt')
        binary = find_srcmove(ROOT, None)
        self.assertIsNotNone(binary)

        def wrap(payload, tag):
            if not tag:
                return payload
            condition = ('<control>(<init/>;<condition><expr><name>looping</name>'
                         '</expr></condition>;<incr/>)</control>' if tag == 'for' else
                         '<condition>(<expr><name>looping</name></expr>)</condition>')
            return (f'<{tag}>{tag} {condition}'
                    f'<block>{{<block_content>{payload}</block_content>}}</block></{tag}>')

        def function(name, payload):
            return (f'<function><type><name>void</name></type><name>{name}</name>'
                    f'<parameter_list>()</parameter_list><block>{{<block_content>{payload}'
                    '</block_content>}</block></function>')

        scenarios = [
            ('same', None, None, 'stationary', 'same_anchor_interval'),
            ('wrap', None, 'while', 'restructured', 'ancestor_wrapped'),
            ('unwrap', 'while', None, 'restructured', 'ancestor_unwrapped'),
            ('incompatible', 'while', 'for', 'ambiguous', 'incompatible_context'),
            ('crossing', None, 'while', 'relocated', 'crossed_stable_sibling'),
            ('container', None, 'while', 'relocated', 'different_semantic_container'),
            ('file', None, 'while', 'relocated', 'different_file'),
        ]
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            for kind in ('type1', 'type2c', 'type3'):
                after = deepcopy(edited if kind == 'type3' else before)
                if kind == 'type2c':
                    for node in after.iter(SRC + 'name'):
                        if node.text in ('ready', 'value'):
                            node.text = 'renamed_' + node.text
                for name, old_wrap, new_wrap, change, reason in scenarios:
                    with self.subTest(kind=kind, scenario=name):
                        old = wrap(ET.tostring(before, encoding='unicode'), old_wrap)
                        new = wrap(ET.tostring(after, encoding='unicode'), new_wrap)
                        old = '<diff:delete>' + old + '</diff:delete>'
                        new = '<diff:insert>' + new + '</diff:insert>'
                        anchor = ('<decl_stmt><decl><type><name>int</name></type>'
                                  '<name>stable_anchor</name><init>=<expr>'
                                  '<literal type="number">73</literal></expr></init></decl>;</decl_stmt>')
                        body = (function('source', old) + function('destination', new)
                                if name == 'container' else
                                function('update', old + (anchor if name == 'crossing' else '') + new))
                        filename = 'old.cpp|new.cpp' if name == 'file' else 'same.cpp'
                        xml = (f'<unit xmlns="{SRC[1:-1]}" xmlns:diff="{DIFF[1:-1]}" '
                               f'language="C++" filename="{filename}">{body}</unit>')
                        path = tmp / 'input.xml'
                        path.write_text(xml)
                        output = tmp / 'result.json'
                        subprocess.run([str(binary), str(path), '--results-only', '--diagnostics',
                                        '--results', str(output)], check=True, capture_output=True)
                        data = json.loads(output.read_text())
                        candidates = {c['candidate_id']: c for c in data['diagnostics']['candidates']}
                        records = [r for r in data['diagnostics']['correspondences']
                                   if r['correspondence_kind'] == kind
                                   and candidates[r['delete_candidate_id']]['construct'] == 'if_stmt']
                        self.assertEqual(len(records), 1)
                        record = records[0]
                        self.assertEqual((record['shadow_change'], record['classification_reason']),
                                         (change, reason))
                        for side, wrapper in [('before', old_wrap), ('after', new_wrap)]:
                            self.assertEqual(record[side + '_context']['meaningful_ancestors'],
                                             ['block'] + ([wrapper, 'block'] if wrapper else []))
                        self.assertFalse(record['carried_by_parent'])
                        # Content similarity establishes correspondence; all
                        # evidence classes still need positive relocation.
                        expected = 'move' if change == 'relocated' else 'not_move'
                        self.assertEqual(record['current_result'], expected)
