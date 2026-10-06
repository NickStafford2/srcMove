"""Move identity needs evidence from independent continuing statement shells.

The exact flush call establishes displacement independently of the edited use.
These fixtures deliberately distinguish identity evidence from location evidence,
and exercise all three reporting modes through the shared integration harness.
"""
from __future__ import annotations

import unittest
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET

from tests.unit import test_move_sequences as fixture
from benchmarking.tooling import find_srcdiff


OLD, NEW = 'old_count', 'new_count'
ANCHOR = ('<expr_stmt><expr><call><name>flush_results</name>'
          '<argument_list>()</argument_list></call></expr>;</expr_stmt>')


def mixed_name(old: str, new: str) -> str:
    return (f'<diff:delete><name>{old}</name></diff:delete>'
            f'<diff:insert><name>{new}</name></diff:insert>')


def use(name: str, call: str = 'consume', *, replacement: str | None = None) -> str:
    argument = mixed_name(name, replacement) if replacement is not None else f'<name>{name}</name>'
    return (f'<expr_stmt><expr><call><name>{call}</name><argument_list>('
            f'<argument><expr>{argument}</expr></argument>)</argument_list>'
            '</call></expr>;</expr_stmt>')


def function(body: str, name: str = 'process') -> str:
    return ('<function><type><name>void</name></type> '
            f'<name>{name}</name><parameter_list>()</parameter_list>'
            '<block>{<block_content>' + body + '</block_content>}</block></function>')


def member_use(name: str, *, receiver: str = 'foo', replacement: str | None = None) -> str:
    field = mixed_name(name, replacement) if replacement is not None else f'<name>{name}</name>'
    member = f'<name><name>{receiver}</name><operator>.</operator>{field}</name>'
    return use(name).replace(f'<name>{name}</name>', member)


def member_guard(name: str, receiver: str = 'foo') -> str:
    return ('<if_stmt><if>if <condition>(<expr><name><name>' + receiver +
            '</name><operator>.</operator><name>' + name +
            '</name></name></expr>)</condition><block>{<block_content>' +
            member_use(name, receiver=receiver) +
            '</block_content>}</block></if></if_stmt>')


class ContinuingIdentityTests(unittest.TestCase):
    def evaluate(self, evidence: str = '', *, foreign: str = '',
                 deleted: str | None = None, inserted: str | None = None) -> dict:
        body = (fixture.run('delete', [deleted or fixture.decl(OLD)]) + ANCHOR +
                fixture.run('insert', [inserted or fixture.decl(NEW)]) + evidence)
        xml = fixture.PREFIX.replace('before.cpp|after.cpp', 'same.cpp')
        xml += function(body) + foreign + '</unit>'
        return fixture.MoveSequenceTests().evaluate(xml)

    def declaration_moves(self, payload: dict) -> list[dict]:
        return [move for move in payload['moves']
                if f'int {OLD} = 1;' in move['from_raw_texts']]

    def assert_rejected(self, payload: dict) -> None:
        # Includes Type-3: lowering the identity tier must not bypass the gate.
        self.assertEqual(self.declaration_moves(payload), [])

    def test_independent_continuing_use_corroborates_small_renamed_move(self):
        moves = self.declaration_moves(self.evaluate(use(OLD, replacement=NEW)))
        self.assertEqual(len(moves), 1)
        self.assertEqual(moves[0]['content_relationship'], 'type2c')
        self.assertEqual(moves[0]['to_raw_texts'], [f'int {NEW} = 1;'])

    def test_crossed_anchor_alone_does_not_establish_renamed_identity(self):
        self.assert_rejected(self.evaluate())

    def test_unchanged_uses_contradict_unrelated_same_shape_declarations(self):
        self.assert_rejected(self.evaluate(use(OLD) + use(NEW, 'publish')))

    def test_continuing_replacement_to_different_partner_rejects_move(self):
        self.assert_rejected(self.evaluate(use(OLD, replacement='actual_count')))

    def test_conflicting_replacements_cannot_corroborate_weak_declaration(self):
        self.assert_rejected(self.evaluate(use(OLD, replacement=NEW) +
                                          use(OLD, 'publish', replacement='other_count')))

    def test_many_to_one_replacement_evidence_is_not_independent_identity(self):
        self.assert_rejected(self.evaluate(use(OLD, replacement=NEW) +
                                          use('other_count', 'publish', replacement=NEW)))

    def test_evidence_from_other_function_cannot_corroborate_move(self):
        self.assert_rejected(self.evaluate(foreign=function(
            use(OLD, replacement=NEW), 'other')))

    def test_shadow_scope_evidence_cannot_override_local_correspondence(self):
        nested = ('<block>{<block_content>' + fixture.decl(OLD) + use(OLD) +
                  '</block_content>}</block>')
        moves = self.declaration_moves(self.evaluate(use(OLD, replacement=NEW) + nested))
        self.assertEqual(len(moves), 1)
        self.assertEqual(moves[0]['content_relationship'], 'type2c')

    def test_separate_deleted_inserted_uses_do_not_supply_continuing_evidence(self):
        evidence = fixture.run('delete', [use(OLD)]) + fixture.run('insert', [use(NEW)])
        self.assert_rejected(self.evaluate(evidence))

    def test_changed_literal_use_is_not_reliable_rename_evidence(self):
        changed = use(OLD, replacement=NEW).replace(
            '</argument>)',
            '</argument>, <argument><expr><diff:delete><literal type="number">1</literal>'
            '</diff:delete><diff:insert><literal type="number">2</literal>'
            '</diff:insert></expr></argument>)')
        self.assert_rejected(self.evaluate(changed))

    def test_contradiction_gate_also_rejects_larger_normalized_statement(self):
        def guard(name: str) -> str:
            return ('<if_stmt><if>if <condition>(<expr><name>' + name +
                    '</name></expr>)</condition><block>{<block_content>' +
                    use(name) + '</block_content>}</block></if></if_stmt>')
        payload = self.evaluate(use(OLD, replacement='actual_count'),
                                deleted=guard(OLD), inserted=guard(NEW))
        self.assertEqual(payload['moves'], [])

    def test_qualified_member_contradiction_crosses_sibling_blocks(self):
        evidence = ('<block>{<block_content>' +
                    member_use(OLD, replacement='actual_count') +
                    '</block_content>}</block>')
        payload = self.evaluate(evidence, deleted=member_guard(OLD), inserted=member_guard(NEW))
        self.assertEqual(payload['moves'], [])

    def test_different_receiver_evidence_cannot_reject_member_move(self):
        evidence = ('<block>{<block_content>' +
                    member_use(OLD, receiver='bar', replacement='actual_count') +
                    '</block_content>}</block>')
        payload = self.evaluate(evidence, deleted=member_guard(OLD), inserted=member_guard(NEW))
        self.assertEqual(len(payload['moves']), 1)
        self.assertEqual(payload['moves'][0]['content_relationship'], 'type2c')

    def test_local_identifier_evidence_cannot_reject_qualified_member_move(self):
        payload = self.evaluate(use(OLD, replacement='actual_count'),
                                deleted=member_guard(OLD), inserted=member_guard(NEW))
        self.assertEqual(len(payload['moves']), 1)
        self.assertEqual(payload['moves'][0]['content_relationship'], 'type2c')

    def test_member_evidence_cannot_corroborate_same_spelled_local_declaration(self):
        self.assert_rejected(self.evaluate(member_use(OLD, replacement=NEW)))

    def test_qualified_member_contradiction_inside_for_rejects_outer_match(self):
        evidence = ('<for>for <control>(;;)</control><block>{<block_content>' +
                    member_use(OLD, replacement='actual_count') +
                    '</block_content>}</block></for>')
        payload = self.evaluate(evidence, deleted=member_guard(OLD), inserted=member_guard(NEW))
        self.assertEqual(payload['moves'], [])

    def test_fragmented_identifier_does_not_corroborate_unrelated_full_names(self):
        fragmented = use(OLD).replace(
            f'<name>{OLD}</name>',
            f'<name>A<diff:delete>{OLD}</diff:delete>'
            f'<diff:insert>{NEW}</diff:insert></name>')
        # Actual continuing identifiers are Aold_count and Anew_count, not the
        # standalone names used by the two declarations under consideration.
        self.assert_rejected(self.evaluate(fragmented))


class ContinuingIdentitySourceTests(unittest.TestCase):
    """Regenerate structured differences, preserving source-reviewed endpoint roles."""

    def evaluate_sources(self, before: str, after: str, *, mixed_use: bool) -> dict:
        srcdiff = find_srcdiff(fixture.REPO_ROOT)
        self.assertIsNotNone(srcdiff, 'These integration tests require the workspace srcDiff binary')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for side, source in [('before', before), ('after', after)]:
                (root / side).mkdir()
                (root / side / 'source.cpp').write_text(source)
            output = root / 'srcdiff.xml'
            result = subprocess.run([str(srcdiff), str(root / 'before'), str(root / 'after'),
                                     '-o', str(output)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            xml = output.read_text()
        src = '{http://www.srcML.org/srcML/src}'
        diff = '{http://www.srcML.org/srcDiff}'
        tree = ET.fromstring(xml)
        # A passing no-move assertion alone could hide upstream endpoint loss.
        # Check that both whole declarations really reach the matching stage.
        for side, name in [('delete', OLD), ('insert', NEW)]:
            candidates = [node for wrapper in tree.iter(diff + side)
                          for node in wrapper.iter(src + 'decl_stmt')]
            self.assertEqual(len(candidates), 1)
            self.assertIn(name, ''.join(candidates[0].itertext()))
        uses = [node for node in tree.iter(src + 'expr_stmt')
                if ''.join(node.itertext()).startswith('consume(')]
        self.assertEqual(len(uses), 1)
        self.assertEqual(any(node.tag == diff + 'delete' for node in uses[0].iter()), mixed_use)
        self.assertEqual(any(node.tag == diff + 'insert' for node in uses[0].iter()), mixed_use)
        return fixture.MoveSequenceTests().evaluate(xml)

    def test_srcdiff_moved_renamed_declaration_has_continuing_use_support(self):
        before = ('void process() {\n  int old_count = 1;\n  flush_results();\n'
                  '  consume(old_count);\n  publish_result();\n}\n')
        after = ('void process() {\n  flush_results();\n  int new_count = 1;\n'
                 '  consume(new_count);\n  publish_result();\n}\n')
        payload = self.evaluate_sources(before, after, mixed_use=True)
        moves = ContinuingIdentityTests().declaration_moves(payload)
        self.assertEqual(len(moves), 1)
        self.assertEqual(moves[0]['content_relationship'], 'type2c')
        self.assertEqual(moves[0]['to_raw_texts'], ['int new_count = 1;'])

    def test_srcdiff_same_shape_declarations_with_continuing_distinct_names_rejected(self):
        # The removed local shadows old_count; the added local shadows new_count.
        # Both revisions are valid C++ and the statements keep their spelling.
        prefix = 'void process(int old_count, int new_count) {\n  {\n'
        suffix = '    consume(old_count);\n    publish(new_count);\n  }\n}\n'
        before = prefix + '    int old_count = 1;\n    flush_results();\n' + suffix
        after = prefix + '    flush_results();\n    int new_count = 1;\n' + suffix
        payload = self.evaluate_sources(before, after, mixed_use=False)
        ContinuingIdentityTests().assert_rejected(payload)


if __name__ == '__main__':
    unittest.main()
