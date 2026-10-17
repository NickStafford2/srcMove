"""Producer namespace admission preserves native locators and XML-only use."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import unittest
import xml.etree.ElementTree as ET
from xml.sax.saxutils import quoteattr

from tests.support.results_v3 import REPO_ROOT, validate_native_xml

SRC = 'http://www.srcML.org/srcML/src'
DIFF = 'http://www.srcML.org/srcDiff'
MV = 'http://www.srcML.org/srcMove'
TEXT = 'transfer_value(state);'
STATEMENT = ('<expr_stmt><expr><call><name>transfer_value</name><argument_list>('
             '<argument><expr><name>state</name></expr></argument>)'
             '</argument_list></call></expr>;</expr_stmt>')


def archive(original_scope='<x:scope xmlns:x="urn:scope">',
            modified_scope='<x:scope xmlns:x="urn:scope">', *, common='',
            original_file='origin.cpp', modified_file='destination.cpp'):
    def unit(filename, side, opening):
        closing = '</' + opening[1:].split()[0].rstrip('>') + '>'
        # Restore the srcML namespace for the selected statement when a scope
        # changes the default namespace. Its ancestor remains deliberately foreign.
        statement = STATEMENT.replace('<expr_stmt>', f'<expr_stmt xmlns="{SRC}">', 1)
        return (f'<unit filename={quoteattr(filename)}>{opening}'
                f'<diff:{side}>{statement}</diff:{side}>{closing}{common}</unit>')
    return (f'<unit xmlns="{SRC}" xmlns:diff="{DIFF}" url="old|new">'
            + unit(original_file, 'delete', original_scope)
            + unit(modified_file, 'insert', modified_scope) + '</unit>')


class ResultsSchemaV3NamespaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from srcmove_runtime.results_schema import validate_results
        cls.validate_results = staticmethod(validate_results)
        cls.binary = Path(os.environ.get('SRCMOVE_BIN', REPO_ROOT / 'build/srcMove')).resolve()
        if not cls.binary.is_file():
            raise RuntimeError('Current srcMove binary is required')

    def execute(self, xml, mode, *, diagnostics=False, only=False, json_results=True):
        root = Path(os.environ.get('SRCMOVE_TEST_ARTIFACTS', REPO_ROOT / 'build/schema3-phase3/namespace-tests'))
        output = root / self._testMethodName / mode
        output.mkdir(parents=True, exist_ok=True)
        source, annotated, result = output / 'input.xml', output / 'annotated.xml', output / 'results.json'
        source.write_text(xml)
        # Unique output directory per mode; a rerun must not mistake an earlier
        # successful artifact for output from an admission failure.
        for stale in (annotated, result):
            if stale.exists():
                stale.unlink()
        argv = [str(self.binary), str(source)]
        if not only:
            argv.append(str(annotated))
        if json_results:
            argv += ['--results', str(result)]
        argv += ['--min-granularity', 'statement']
        if diagnostics:
            argv.append('--diagnostics')
        if only:
            argv.append('--results-only')
        completed = subprocess.run(argv, capture_output=True, text=True, timeout=30, check=False)
        (output / 'execution.json').write_text(json.dumps({
            'purpose': 'Namespace admission correctness fixture, not a research result.',
            'argv': argv, 'returncode': completed.returncode,
            'stdout': completed.stdout, 'stderr': completed.stderr,
        }, indent=2) + '\n')
        return completed, source, annotated, result

    def assert_success_modes(self, xml):
        payloads = {}
        for mode, diagnostics, only in [('ordinary', False, False), ('diagnostic', True, False),
                                        ('results_only', False, True), ('diagnostic_results_only', True, True)]:
            with self.subTest(mode=mode):
                completed, source, annotated, result = self.execute(xml, mode, diagnostics=diagnostics, only=only)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                payload = json.loads(result.read_text())
                self.validate_results(payload)
                groups = payload['atomic_move_groups']
                self.assertTrue(groups, 'Namespace fixture must exercise real selected evidence')
                self.assertTrue(any(group['content_relationship'] == 'type1'
                                    and any(endpoint['raw_text'] == TEXT for endpoint in group['original'])
                                    and any(endpoint['raw_text'] == TEXT for endpoint in group['modified'])
                                    for group in groups), 'The expected whole statement must be selected')
                if not only:
                    validate_native_xml(source, annotated, payload)
                payloads[mode] = payload
        self.assertEqual(payloads['ordinary'], payloads['results_only'])
        self.assertEqual(payloads['diagnostic'], payloads['diagnostic_results_only'])
        ordinary = dict(payloads['diagnostic'])
        ordinary.pop('diagnostics')
        self.assertEqual(ordinary, payloads['ordinary'])
        return payloads['ordinary']

    def assert_json_rejected_xml_preserved(self, xml):
        for mode, diagnostics, only in [('ordinary', False, False), ('diagnostic', True, False),
                                        ('results_only', False, True)]:
            with self.subTest(mode=mode):
                completed, _, annotated, result = self.execute(xml, mode, diagnostics=diagnostics, only=only)
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn('unsupported_namespace_context', completed.stderr)
                self.assertFalse(annotated.exists(), 'JSON admission must fail before annotation')
                self.assertFalse(result.exists(), 'JSON admission must not publish partial results')
        completed, _, annotated, _ = self.execute(xml, 'xml_only', json_results=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        nodes = [node for node in ET.parse(annotated).getroot().iter() if f'{{{MV}}}id' in node.attrib]
        self.assertGreaterEqual(len(nodes), 2, 'XML-only must still annotate a real source/destination pair')
        self.assertTrue(any(''.join(node.itertext()) == TEXT for node in nodes))

    def test_same_extension_namespace_with_lexical_aliases(self):
        payload = self.assert_success_modes(archive(modified_scope='<y:scope xmlns:y="urn:scope">'))
        self.assertEqual(payload['xpath_context']['namespaces']['x'], 'urn:scope')
        self.assertEqual(payload['xpath_context']['namespaces']['y'], 'urn:scope')
        paths = [endpoint['xpath'] for group in payload['atomic_move_groups']
                 for side in ('original', 'modified') for endpoint in group[side]]
        self.assertTrue(any('/x:scope[' in path for path in paths))
        self.assertTrue(any('/y:scope[' in path for path in paths))

    def test_conflicting_published_extension_bindings_reject_only_json(self):
        self.assert_json_rejected_xml_preserved(archive(modified_scope='<x:scope xmlns:x="urn:other">'))

    def test_unrelated_common_rebinding_does_not_poison_published_paths(self):
        # Keep the unrelated binding in another file unit. The existing XML
        # writer hoists namespaces within a file unit and cannot preserve two
        # lexical bindings there; that independent writer defect is outside
        # results serialization. No candidate path enters this third unit.
        xml = archive()[:-len('</unit>')]
        xml += ('<unit filename="unrelated.cpp"><x:marker xmlns:x="urn:unrelated"/>'
                '</unit></unit>')
        payload = self.assert_success_modes(xml)
        self.assertEqual(payload['xpath_context']['namespaces']['x'], 'urn:scope')

    def test_reserved_canonical_prefix_collision_rejects_only_json(self):
        self.assert_json_rejected_xml_preserved(archive(
            original_scope='<src:scope xmlns:src="urn:extension">',
            modified_scope='<src:scope xmlns:src="urn:extension">'))

    def test_foreign_default_namespace_ancestor_rejects_only_json(self):
        self.assert_json_rejected_xml_preserved(archive(
            original_scope='<scope xmlns="urn:extension">', modified_scope='<scope xmlns="urn:extension">'))

    def test_genuinely_unnamespaced_ancestor_resolves(self):
        payload = self.assert_success_modes(archive(original_scope='<scope xmlns="">', modified_scope='<scope xmlns="">'))
        paths = [endpoint['xpath'] for group in payload['atomic_move_groups']
                 for side in ('original', 'modified') for endpoint in group[side]]
        self.assertTrue(any('/scope[' in path for path in paths))

    def test_unicode_published_prefix_is_explicitly_unsupported(self):
        self.assert_json_rejected_xml_preserved(archive(
            original_scope='<é:scope xmlns:é="urn:unicode">', modified_scope='<é:scope xmlns:é="urn:unicode">'))

    def test_unused_unicode_prefix_is_not_published(self):
        payload = self.assert_success_modes(archive(common='<é:marker xmlns:é="urn:unicode"/>'))
        self.assertNotIn('é', payload['xpath_context']['namespaces'])

    def test_filename_quotes_slashes_and_colons_preserve_locators(self):
        self.assert_success_modes(archive(original_file='old/dir:a\'b"c.cpp', modified_file='new/dir:d\'e"f.cpp'))

    def test_nested_extension_ancestors_after_closed_siblings(self):
        # Lookup starts at the last preceding extension span, which can be a
        # closed sibling below an ancestor that still contains the candidate.
        xml = archive()
        xml = xml.replace('<x:scope xmlns:x="urn:scope">',
                          '<outer:scope xmlns:outer="urn:outer">'
                          '<x:scope xmlns:x="urn:scope">'
                          '<closed:marker xmlns:closed="urn:closed">'
                          '<deep:marker xmlns:deep="urn:deep"/></closed:marker>')
        xml = xml.replace('</x:scope>', '</x:scope></outer:scope>')
        payload = self.assert_success_modes(xml)
        namespaces = payload['xpath_context']['namespaces']
        self.assertEqual(namespaces['outer'], 'urn:outer')
        self.assertEqual(namespaces['x'], 'urn:scope')
        self.assertNotIn('closed', namespaces)
        self.assertNotIn('deep', namespaces)

    def test_closed_extension_sibling_does_not_bind_following_candidate(self):
        xml = archive(original_scope='<scope xmlns="">', modified_scope='<scope xmlns="">')
        xml = xml.replace('><diff:',
                          '><closed:marker xmlns:closed="urn:closed">'
                          '<deep:marker xmlns:deep="urn:deep"/></closed:marker><diff:')
        payload = self.assert_success_modes(xml)
        self.assertNotIn('closed', payload['xpath_context']['namespaces'])
        self.assertNotIn('deep', payload['xpath_context']['namespaces'])
