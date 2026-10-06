"""Contracts for selection, duplicate rejection and truthful outcome reporting."""
from __future__ import annotations
import io
import unittest
from unittest.mock import patch
from tests import run


class RunnerTests(unittest.TestCase):
    def test_selection_union_has_no_duplicates(self):
        cases = [unittest.FunctionTestCase(lambda: None, description=name) for name in ('a', 'b')]
        with patch.object(cases[0], 'id', return_value='behavior.a'), patch.object(cases[1], 'id', return_value='behavior.b'):
            self.assertEqual(run.select(cases, ['behavior.*', '*a']), cases)

    def test_unknown_selector_is_an_error(self):
        with self.assertRaisesRegex(ValueError, 'matches no tests'):
            run.select([], ['nonexistent'])

    def test_duplicate_discovery_is_rejected(self):
        case = unittest.FunctionTestCase(lambda: None)
        with patch.object(unittest.TestLoader, 'discover', return_value=unittest.TestSuite([case, case])):
            with self.assertRaisesRegex(ValueError, 'duplicate test IDs'):
                run.inventory(['tooling'])

    def test_subtest_failures_remain_failures_and_errors_remain_errors(self):
        class Example(unittest.TestCase):
            def runTest(self):
                with self.subTest(case='assertion'):
                    self.assertEqual(1, 2)
                with self.subTest(case='execution'):
                    raise RuntimeError('tool failed')
        result = unittest.TextTestRunner(stream=io.StringIO(), resultclass=run.RecordedResult).run(Example())
        self.assertEqual(len(result.outcomes), 1)
        self.assertEqual(result.outcomes[0]['status'], 'error')
        self.assertEqual(len(result.outcomes[0]['details']), 2)
        self.assertIn('assertion', result.outcomes[0]['details'][0])

    def test_setup_failure_has_unexecuted_inventory_not_success(self):
        class Example(unittest.TestCase):
            @classmethod
            def setUpClass(cls):
                raise RuntimeError('dependency missing')
            def test_required(self):
                pass
        result = unittest.TextTestRunner(stream=io.StringIO(), resultclass=run.RecordedResult).run(unittest.defaultTestLoader.loadTestsFromTestCase(Example))
        self.assertEqual(result.testsRun, 0)
        self.assertEqual(result.outcomes[0]['status'], 'error')
        self.assertIn('dependency missing', result.outcomes[0]['details'][0])

    def test_skip_is_not_accepted_coverage(self):
        class Example(unittest.TestCase):
            def runTest(self):
                self.skipTest('required fixture unavailable')
        result = unittest.TextTestRunner(stream=io.StringIO(), resultclass=run.RecordedResult).run(Example())
        self.assertEqual(result.outcomes[0]['status'], 'skip')

    def test_component_build_remains_independent_of_selected_detector(self):
        import json
        import os
        from pathlib import Path
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            component_dir = root / 'components'
            component_dir.mkdir()
            binary = component_dir / 'canonical_forms_test'
            binary.write_text('#!/bin/sh\nexit 0\n')
            binary.chmod(0o755)
            with patch.dict(os.environ, {'SRCMOVE_BIN': '/alternate/detector', 'SRCMOVE_TEST_ARTIFACTS': str(root)}):
                component = run.ComponentTest('canonical_forms', component_dir)
                result = unittest.TextTestRunner(stream=io.StringIO()).run(component)
            self.assertTrue(result.wasSuccessful())
            command = json.loads((root / 'components.canonical_forms/command.json').read_text())
            self.assertEqual(command, [str(binary)])
            self.assertEqual(json.loads((root / 'components.canonical_forms/executable.json').read_text())['path'], str(binary))
