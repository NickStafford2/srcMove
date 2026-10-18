"""XML oracles for sequence context, independent of detector-produced results."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from tests.support.results_v3 import CONTRACT, load_module, validate_native_xml
from tests.support.sequence_xml import validate_sequences

SRC = "http://www.srcML.org/srcML/src"
DIFF = "http://www.srcML.org/srcDiff"
OPEN = f'<unit xmlns="{SRC}" xmlns:diff="{DIFF}" filename="old.cpp|new.cpp">'
STATEMENTS = '<expr_stmt>a();</expr_stmt><expr_stmt>b();</expr_stmt>'
BODY = f'<diff:delete>{STATEMENTS}</diff:delete><diff:insert>{STATEMENTS}</diff:insert>'


def results(nested=False):
    parent = "element:1" if nested else "unit:0"
    prefix = "/src:unit[1]" + ("/src:block_content[1]" if nested else "")
    groups = [{"id": str(index), "content_relationship": "type1",
               "correspondence": {"status": "selected_pair"},
               "original": [{"xpath": f"{prefix}/diff:delete[1]/src:expr_stmt[{index}]"}],
               "modified": [{"xpath": f"{prefix}/diff:insert[1]/src:expr_stmt[{index}]"}]}
              for index in (1, 2)]
    sequence = {side: {"revision_file": filename,
                      "parent_id": f"old.cpp|new.cpp:{side}:{parent}",
                      "first_child_ordinal": 1, "last_child_ordinal": 2}
                for side, filename in (("original", "old.cpp"), ("modified", "new.cpp"))}
    return {"atomic_move_groups": groups,
            "output_items": [{"id": "sequence:1", "kind": "sequence_move_group",
                              "member_group_ids": ["1", "2"], "sequence": sequence}],
            "xpath_context": {"namespaces": {"src": SRC, "diff": DIFF}}}


class ResultsSchemaV3SequenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="sequence-xml-")
        self.addCleanup(self.directory.cleanup)
        self.source = Path(self.directory.name) / "input.xml"
        self.locator = load_module("sequence_test_locators", CONTRACT / "check_locators.py")

    def validate(self, xml, payload):
        from lxml import etree
        self.source.write_text(xml)
        tree = etree.parse(str(self.source), etree.XMLParser(resolve_entities=False, no_network=True))
        validate_sequences(self.source, tree, payload, self.locator.resolve)

    def test_unit_parent_and_revision_projection(self):
        # Inserted statements do not consume original-side positions, and vice versa.
        self.validate(OPEN + BODY + '</unit>', results())

    def test_nested_parent(self):
        self.validate(OPEN + '<block_content>' + BODY + '</block_content></unit>', results(True))

    def test_literal_block_brace_consumes_a_position(self):
        # Minimal form of pair 732: the brace is source text, not an element.
        payload = results(True)
        for group in payload['atomic_move_groups']:
            for side in ('original', 'modified'):
                group[side][0]['xpath'] = group[side][0]['xpath'].replace(
                    'src:block_content', 'src:block')
        for span in payload['output_items'][0]['sequence'].values():
            span.update(first_child_ordinal=2, last_child_ordinal=3)
        self.validate(OPEN + '<block>{\n' + BODY + '}</block></unit>', payload)

    def test_each_nonwhitespace_text_run_consumes_a_position(self):
        for prefix in ('alpha beta\t', '<!-- ignored -->alpha beta\t',
                       '<comment>// ignored</comment>alpha beta\t',
                       '<diff:insert/>alpha beta\t'):
            with self.subTest(prefix=prefix):
                payload = results()
                for span in payload['output_items'][0]['sequence'].values():
                    span.update(first_child_ordinal=3, last_child_ordinal=4)
                if prefix.startswith('<diff:insert/>'):
                    for group in payload['atomic_move_groups']:
                        group['modified'][0]['xpath'] = group['modified'][0]['xpath'].replace(
                            'diff:insert[1]', 'diff:insert[2]')
                self.validate(OPEN + prefix + BODY + '</unit>', payload)

    def test_wrapper_text_counts_only_in_its_revision(self):
        for wrapper, sides in (('delete', ('original',)),
                               ('insert', ('modified',)),
                               ('common', ('original', 'modified'))):
            with self.subTest(wrapper=wrapper):
                payload = results()
                for side in sides:
                    payload['output_items'][0]['sequence'][side].update(
                        first_child_ordinal=2, last_child_ordinal=3)
                # This text is a wrapper's .text; its tail is common whitespace.
                prefix = f'<diff:{wrapper}>hidden();</diff:{wrapper}>\n'
                for group in payload['atomic_move_groups']:
                    if wrapper in ('delete', 'insert'):
                        side = sides[0]
                        group[side][0]['xpath'] = group[side][0]['xpath'].replace(
                            f'diff:{wrapper}[1]', f'diff:{wrapper}[2]')
                self.validate(OPEN + prefix + BODY + '</unit>', payload)

    def test_substantive_tails_break_adjacency_in_either_revision(self):
        for wrapper in ('delete', 'insert'):
            for gap in ('hidden();', '<!-- ignored -->hidden();',
                        '<comment>// ignored</comment>hidden();',
                        '<diff:common/>hidden();'):
                with self.subTest(wrapper=wrapper, gap=gap):
                    body = BODY.replace(
                        f'<diff:{wrapper}>{STATEMENTS}',
                        f'<diff:{wrapper}>' + STATEMENTS.replace(
                            '</expr_stmt><expr_stmt>',
                            '</expr_stmt>' + gap + '<expr_stmt>'))
                    with self.assertRaisesRegex(AssertionError, 'child positions or member order'):
                        self.validate(OPEN + body + '</unit>', results())

    def test_text_in_absent_source_parent_does_not_escape_to_siblings(self):
        payload = results()
        for group in payload['atomic_move_groups']:
            group['original'][0]['xpath'] = group['original'][0]['xpath'].replace(
                'diff:delete[1]', 'diff:delete[2]')
        payload['output_items'][0]['sequence']['original'].update(
            first_child_ordinal=2, last_child_ordinal=3)
        prefix = '<diff:delete><block>{<diff:common>hidden();</diff:common>}</block></diff:delete>'
        self.validate(OPEN + prefix + BODY + '</unit>', payload)

    def test_archive_unit_parent(self):
        payload = results()
        for group in payload['atomic_move_groups']:
            for side in ('original', 'modified'):
                group[side][0]['xpath'] = group[side][0]['xpath'].replace(
                    '/src:unit[1]', "/src:unit[@filename='old.cpp|new.cpp']", 1)
        for span in payload['output_items'][0]['sequence'].values():
            span['parent_id'] = span['parent_id'].replace('unit:0', 'unit:1')
        self.validate(f'<unit xmlns="{SRC}" url="archive">' + OPEN + BODY + '</unit></unit>', payload)

    def test_xml_comments_and_source_comments_do_not_consume_positions(self):
        body = BODY.replace('<expr_stmt>b();', '<!-- XML comment --><comment>// comment</comment><expr_stmt>b();')
        self.validate(OPEN + body + '</unit>', results())

    def test_nested_parent_stream_position_includes_text_and_xml_comments(self):
        # root start=0, whitespace=1, XML comment=2, whitespace=3, block start=4.
        payload = results(True)
        for span in payload['output_items'][0]['sequence'].values():
            span['parent_id'] = span['parent_id'].replace('element:1', 'element:4')
        self.validate(OPEN + ' <!-- comment -->\n<block_content>' + BODY + '</block_content></unit>', payload)

    def test_parent_stream_position_counts_each_indentation_character(self):
        payload = results(True)
        for span in payload['output_items'][0]['sequence'].values():
            span['parent_id'] = span['parent_id'].replace('element:1', 'element:4')
        self.validate(OPEN + '\n  <block_content>' + BODY + '</block_content></unit>', payload)

    def test_parent_stream_position_includes_processing_instruction_and_cdata(self):
        payload = results(True)
        for span in payload['output_items'][0]['sequence'].values():
            span['parent_id'] = span['parent_id'].replace('element:1', 'element:3')
        self.validate(OPEN + '<?hint value?><![CDATA[  ]]><block_content>' + BODY + '</block_content></unit>', payload)

    def test_source_comment_inside_diff_ws_does_not_consume_position(self):
        body = BODY.replace('<expr_stmt>b();',
                            '<diff:ws><comment>// ignored</comment>\n</diff:ws><expr_stmt>b();')
        self.validate(OPEN + body + '</unit>', results())

    def test_nonexistent_or_wrong_parent_is_rejected(self):
        for side in ('original', 'modified'):
            for parent in ('missing', f'old.cpp|new.cpp:{side}:unit:0'):
                with self.subTest(side=side, parent=parent):
                    payload = results(True)
                    payload['output_items'][0]['sequence'][side]['parent_id'] = parent
                    with self.assertRaisesRegex(AssertionError, 'parent ID differs'):
                        self.validate(OPEN + '<block_content>' + BODY + '</block_content></unit>', payload)

    def test_shifted_child_positions_are_rejected(self):
        for side in ('original', 'modified'):
            with self.subTest(side=side):
                payload = results()
                span = payload['output_items'][0]['sequence'][side]
                span['first_child_ordinal'] += 10000
                span['last_child_ordinal'] += 10000
                with self.assertRaisesRegex(AssertionError, 'child positions or member order'):
                    self.validate(OPEN + BODY + '</unit>', payload)

    def test_reversed_member_order_is_rejected(self):
        payload = results()
        payload['output_items'][0]['member_group_ids'].reverse()
        with self.assertRaisesRegex(AssertionError, 'child positions or member order'):
            self.validate(OPEN + BODY + '</unit>', payload)

    def test_unselected_common_child_breaks_adjacency(self):
        payload = results()
        payload['atomic_move_groups'][1]['original'][0]['xpath'] = (
            '/src:unit[1]/diff:delete[2]/src:expr_stmt[1]')
        body = ('<diff:delete><expr_stmt>a();</expr_stmt></diff:delete>'
                '<empty_stmt>;</empty_stmt>'
                '<diff:delete><expr_stmt>b();</expr_stmt></diff:delete>'
                f'<diff:insert>{STATEMENTS}</diff:insert>')
        with self.assertRaisesRegex(AssertionError, 'child positions or member order'):
            self.validate(OPEN + body + '</unit>', payload)

    def test_different_parent_for_second_member_is_rejected(self):
        payload = results()
        payload['atomic_move_groups'][1]['original'][0]['xpath'] = (
            '/src:unit[1]/src:block_content[1]/diff:delete[1]/src:expr_stmt[1]')
        body = BODY.replace('<expr_stmt>b();</expr_stmt>', '', 1)
        body += '<block_content><diff:delete><expr_stmt>b();</expr_stmt></diff:delete></block_content>'
        with self.assertRaisesRegex(AssertionError, 'parent ID differs'):
            self.validate(OPEN + body + '</unit>', payload)

    def test_wrong_revision_file_is_rejected(self):
        payload = results()
        payload['output_items'][0]['sequence']['modified']['revision_file'] = 'old.cpp'
        with self.assertRaisesRegex(AssertionError, 'revision file differs'):
            self.validate(OPEN + BODY + '</unit>', payload)

    def test_repeated_sequence_nodes_are_rejected(self):
        payload = results()
        duplicate = deepcopy(payload['output_items'][0])
        duplicate['id'] = 'sequence:duplicate'
        payload['output_items'].append(duplicate)
        with self.assertRaisesRegex(AssertionError, 'spans overlap'):
            self.validate(OPEN + BODY + '</unit>', payload)

    def test_native_validator_rejects_corrupted_sequence_metadata(self):
        from lxml import etree
        payload = results()
        self.source.write_text(OPEN + BODY + '</unit>')
        annotated = etree.parse(str(self.source))
        for group, text in zip(payload['atomic_move_groups'], ('a();', 'b();')):
            for side, other, attribute, filename in (
                    ('original', 'modified', 'to', 'old.cpp'),
                    ('modified', 'original', 'from', 'new.cpp')):
                endpoint = group[side][0]
                endpoint.update(raw_text=text, revision_file=filename, construct='expr_stmt')
                node = self.locator.resolve(annotated, endpoint['xpath'],
                                            payload['xpath_context']['namespaces'])
                node.set('{' + self.locator.MV + '}id', group['id'])
                node.set('{' + self.locator.MV + '}' + attribute, group[other][0]['xpath'])
        output = Path(self.directory.name) / 'annotated.xml'
        annotated.write(str(output))
        validate_native_xml(self.source, output, payload)
        for field, value, message in (
                ('parent_id', 'nonexistent-parent', 'parent ID differs'),
                ('first_child_ordinal', 10001, 'child positions or member order')):
            with self.subTest(field=field):
                broken = deepcopy(payload)
                span = broken['output_items'][0]['sequence']['original']
                span[field] = value
                if field == 'first_child_ordinal':
                    span['last_child_ordinal'] = value + 1
                with self.assertRaisesRegex(AssertionError, message):
                    validate_native_xml(self.source, output, broken)
