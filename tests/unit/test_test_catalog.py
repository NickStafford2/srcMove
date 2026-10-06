"""The readable index preserves inventory membership and independent oracle links."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.support.catalog import build_catalog, describe_test, render_html
from tests.support import catalog as catalog_support
from tests.support.cases import XmlCaseSpec
from tests.support import fixture_tests


def example_case(documented=True):
    class ExampleCase(unittest.TestCase):
        def runTest(self):
            raise AssertionError('Catalog generation must never execute this test')
    if documented:
        ExampleCase.runTest.__doc__ = 'A documented purpose with <source> and quotation marks.'
    return ExampleCase()


class TestCatalogTests(unittest.TestCase):
    def test_complete_inventory_is_described_without_execution(self):
        """Every runner test appears exactly once, without running any detector."""
        from tests.run import inventory
        tests = inventory()
        with patch('tests.support.execution.execute_xml', side_effect=AssertionError('No execution')):
            catalog = build_catalog(tests)
        self.assertEqual([entry['id'] for entry in catalog['entries']], [test.id() for test in tests])
        self.assertEqual(sum(catalog['counts'].values()), len(tests))
        for entry in catalog['entries']:
            with self.subTest(case=entry['id']):
                self.assertTrue(Path(entry['test']['path']).is_file())
                self.assertGreater(entry['test']['line'], 0)
                self.assertTrue(entry['expectations'])
                self.assertTrue(all(Path(item['path']).is_file() for item in entry['expectations']))
        indexed = {entry['id']: entry for entry in catalog['entries']}
        policy = indexed['fixtures.policy.direct_c_function']
        self.assertEqual(policy['purpose'], 'A complete function is a real move.')
        self.assertTrue(any(item['path'].endswith('/before/source.c') for item in policy['inputs']))
        self.assertTrue(any(item['path'].endswith('/after/destination.c') for item in policy['inputs']))
        self.assertTrue(any(item['path'].endswith('/expected-from.c') for item in policy['expectations']))
        scenario = indexed['tests.behavior.test_readable_scenarios.ReadableScenarioTests.test_two_existing_calls_produce_two_new_copies']
        self.assertTrue(any(item['path'].endswith('/before.cpp') for item in scenario['inputs']))
        self.assertTrue(any(item['path'].endswith('/after.cpp') for item in scenario['inputs']))
        self.assertTrue(any(item['label'] == 'Expected behavior' and item['line'] != scenario['test']['line']
                            for item in scenario['expectations']))

    def test_description_is_explicit_and_missing_purpose_is_visible(self):
        """Names are not converted into invented explanations."""
        described = describe_test(example_case())
        missing = describe_test(example_case(False))
        self.assertEqual(described['purpose'], 'A documented purpose with <source> and quotation marks.')
        self.assertEqual(missing['purpose'], 'needs explanation')
        self.assertEqual(described['inputs'][0]['path'], described['test']['path'])

    def test_xml_fixture_links_input_and_both_independent_oracles(self):
        """Fixture entries expose expected JSON and XML rather than detector results."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = [root / name for name in ('input.xml', 'expected.json', 'expected.xml')]
            for path in files:
                path.write_text('fixture')
            case = XmlCaseSpec('readable_case', root, *files)
            entry = describe_test(fixture_tests.AcceptedFixtureTest(case))
            self.assertEqual(entry['id'], 'fixtures.xml.readable_case')
            self.assertEqual(entry['inputs'][0]['path'], str(files[0]))
            self.assertEqual([item['path'] for item in entry['expectations'][:2]],
                             [str(path) for path in files[1:]])
            (root / 'case.json').write_text('{"purpose": "Retain the independently reviewed output.", "input": "input.xml"}')
            described = describe_test(fixture_tests.AcceptedFixtureTest(case))
            self.assertEqual(described['purpose'], 'Retain the independently reviewed output.')
            self.assertTrue(any(item['path'] == str(root / 'case.json') for item in described['inputs']))
            self.assertEqual(described['expectations'], entry['expectations'])

    def test_rendering_escapes_descriptions_and_attributes(self):
        """Source and author text cannot become executable HTML."""
        catalog = build_catalog([example_case()])
        entry = catalog['entries'][0]
        entry['id'] = '<script>alert(1)</script>'
        entry['topic'] = '\" onmouseover=\"alert(1)'
        entry['inputs'][0]['label'] = '<img src=x onerror=alert(1)>'
        html = render_html(catalog)
        self.assertNotIn('<script>alert(1)</script>', html)
        self.assertNotIn('<img src=x', html)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', html)
        self.assertIn('&quot; onmouseover=&quot;alert(1)', html)

    def test_duplicate_inventory_membership_is_rejected(self):
        """The index cannot silently collapse duplicate runner IDs."""
        with self.assertRaisesRegex(ValueError, 'Duplicate inventory IDs'):
            build_catalog([example_case(), example_case()])

    def test_fixture_previews_are_escaped_bounded_and_confined_to_fixtures(self):
        """Readable previews exclude outside files and visibly truncate long examples."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixtures = root / 'tests/fixtures'
            fixtures.mkdir(parents=True)
            source = fixtures / 'before.cpp'
            source.write_text('<script>fixture</script>\n' + '\n'.join(f'line{n};' for n in range(1, 106)))
            expected = fixtures / 'case.json'
            expected.write_text('{"move_count": 1, "internal_note": "not an expectation"}')
            outside = root / 'outside.cpp'
            outside.write_text('outside_fixture_marker')
            catalog = build_catalog([example_case()])
            catalog['entries'][0]['inputs'] = [catalog_support.link(path, path.name) for path in (source, outside)]
            catalog['entries'][0]['expectations'] = [catalog_support.link(expected, 'Expected count')]
            with patch.object(catalog_support, 'ROOT', root):
                html = render_html(catalog)
            self.assertIn('&lt;script&gt;fixture&lt;/script&gt;', html)
            self.assertIn('Preview truncated: showing 100 of 106 lines', html)
            self.assertNotIn('line105;', html)
            self.assertNotIn('outside_fixture_marker', html)
            self.assertIn('&quot;move_count&quot;: 1', html)
            self.assertNotIn('not an expectation', html)
