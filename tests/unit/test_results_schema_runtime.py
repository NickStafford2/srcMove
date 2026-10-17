"""Independent pinned-JSON-Schema shape parity and oracle boundary regressions."""
from copy import deepcopy
import json
import importlib.util
from pathlib import Path
import tempfile
import unittest

from srcmove_runtime.results_schema import _shape, contract_schema, validate_results
from tests.support.validation import compare_xml_files_exact

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(importlib.util.find_spec("jsonschema"), "Pinned development-only jsonschema required for shape parity")
class RuntimeShapeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The focused schema test target supplies the pinned development-only
        # dependency. Production admission remains dependency-free.
        from jsonschema import Draft202012Validator
        cls.schema = contract_schema()
        Draft202012Validator.check_schema(cls.schema)
        cls.independent = Draft202012Validator(cls.schema)

    def assert_parity(self, document):
        expected = self.independent.is_valid(document)
        try:
            _shape(document, self.schema)
            actual = True
        except ValueError:
            actual = False
        self.assertEqual(actual, expected, repr(document)[:1200])

    def test_examples_and_independent_nested_shape_mutations(self):
        examples = ROOT / 'doc/plans/results_schema_v3/examples'
        count = 0
        for path in sorted(examples.glob('*.json')):
            document = json.loads(path.read_text())
            if 'results_schema_version' not in document:
                continue
            with self.subTest(example=path.name):
                self.assert_parity(document)
                validate_results(document)
            def visit(value, trail=()):
                nonlocal count
                mutations = []
                if isinstance(value, dict):
                    mutations.append(dict(value, unexpected_contract_property=True))
                    mutations.extend({key: item for key, item in value.items() if key != removed}
                                     for removed in value)
                elif isinstance(value, list):
                    mutations.extend([{}, None])
                    if value:
                        mutations.append(value + [deepcopy(value[0])])
                else:
                    mutations.extend([None, True, -1, 1.5, '', 'unsupported', [], {}])
                for replacement in mutations:
                    mutated = deepcopy(document)
                    if trail:
                        parent = mutated
                        for key in trail[:-1]:
                            parent = parent[key]
                        parent[trail[-1]] = replacement
                    else:
                        mutated = replacement
                    with self.subTest(example=path.name, trail=trail, replacement=repr(replacement)[:80]):
                        self.assert_parity(mutated)
                    count += 1
                children = value.items() if isinstance(value, dict) else enumerate(value) if isinstance(value, list) else ()
                for key, child in children:
                    visit(child, trail + (key,))
            visit(document)
        self.assertGreater(count, 1000)

    def test_live_admission_rejects_schema2(self):
        with self.assertRaises(ValueError):
            validate_results({'results_schema_version': 2, 'moves': []})


class RuntimeNamespaceAdmissionTests(unittest.TestCase):
    def test_unsupported_unicode_prefix_cannot_evade_admission(self):
        original = json.loads((ROOT / 'doc/plans/results_schema_v3/examples/selected-pair.json').read_text())
        for prefix in ('é', 'e\u0301'):
            payload = deepcopy(original)
            payload['atomic_move_groups'][0]['original'][0]['xpath'] += f'/{prefix}:scope[1]'
            with self.subTest(prefix=prefix), self.assertRaisesRegex(ValueError, 'unsupported namespace prefix'):
                validate_results(payload)


class FrozenXmlOracleBoundaryTests(unittest.TestCase):
    def compare(self, before, after):
        with tempfile.TemporaryDirectory() as directory:
            expected, actual = Path(directory) / 'expected.xml', Path(directory) / 'actual.xml'
            expected.write_text(before)
            actual.write_text(after)
            return compare_xml_files_exact(expected, actual)

    def test_added_name_and_filename_qualifiers_only_in_move_links(self):
        old = '<x mv:to="/src:unit[@filename=\'a.cpp\']/src:function[src:name=\'work\']/src:block[1]">text</x>'
        new = old.replace("'a.cpp']", "'a.cpp'][1]").replace("'work']", "'work'][2]")
        self.assertEqual(self.compare(old, new), [])
        entities = old.replace("'a.cpp'", '&quot;a.cpp&quot;').replace("'work'", '&apos;work&apos;')
        qualified = entities.replace('&quot;]', '&quot;][1]').replace('&apos;]', '&apos;][2]')
        self.assertEqual(self.compare(entities, qualified), [])

    def test_non_locator_and_other_position_changes_still_fail(self):
        path = "/src:unit[@filename='a.cpp']/src:function[src:name='work']/src:block[1]"
        old = f'<x mv:to="{path}" other="{path}">{path}</x>'
        for changed in (old.replace('src:block[1]', 'src:block[2]'),
                        old.replace('other="' + path, 'other="' + path.replace("'a.cpp']", "'a.cpp'][1]")),
                        old.replace('>' + path, '>' + path.replace("'work']", "'work'][1]")),
                        old.replace('mv:to="/', 'mv:to="/src:unit[1]/')):
            with self.subTest(changed=changed):
                self.assertTrue(self.compare(old, changed))
