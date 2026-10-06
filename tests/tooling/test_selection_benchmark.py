"""Comparison contracts: shared inventory, visible misses, and invalid execution."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from moveSelectionBench.benchmark import run_benchmark, summarize


def report(status):
    return {'inventory': ['fixtures.xml.one'], 'outcomes': [{'id': 'fixtures.xml.one', 'status': status}]}


class SelectionBenchmarkTests(unittest.TestCase):
    def test_summary_reports_baseline_transitions(self):
        summary = summarize({'base': report('failure'), 'new': report('pass')}, 'base')
        self.assertEqual(summary['transitions_from_baseline']['new'], {'failure_to_pass': 1})
        self.assertEqual(summary['hard_failures'], 0)
        self.assertEqual(summary['semantic_failures'], 1)

    def test_inventory_drift_invalidates_comparison(self):
        changed = report('pass')
        changed['inventory'] = ['other']
        with self.assertRaisesRegex(ValueError, 'inventories differ'):
            summarize({'base': report('pass'), 'new': changed}, 'base')

    def test_setup_errors_and_unexecuted_tests_remain_invalid(self):
        missing = report('pass')
        missing['outcomes'] = [{'id': 'setUpClass', 'status': 'error'}]
        summary = summarize({'base': missing}, 'base')
        self.assertEqual(summary['variants']['base'], {'not_executed': 1, 'error': 1})
        self.assertEqual(summary['hard_failures'], 2)

    def test_comparison_consumes_correctness_runner_and_preserves_miss(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / 'srcMove'
            binary.write_text('fixture executable')
            commands = []
            def runner(command, **kwargs):
                commands.append(command)
                output = Path(command[command.index('--report') + 1])
                output.write_text(json.dumps(report('failure')))
                return subprocess.CompletedProcess(command, 1, b'visible output', b'assertion detail')
            with patch('moveSelectionBench.benchmark.subprocess.run', side_effect=runner):
                run_dir, summary = run_benchmark(variants={'base': binary}, output_root=root/'results', baseline='base', run_id='run', test_patterns=['fixtures.xml.*'])
            self.assertEqual(summary['hard_failures'], 0)
            self.assertEqual(summary['variants']['base'], {'failure': 1})
            self.assertIn('tests/run.py', commands[0][1])
            self.assertEqual(commands[0][commands[0].index('--suite') + 1], 'behavior')
            self.assertEqual(commands[0][commands[0].index('--test') + 1], 'fixtures.xml.*')
            self.assertEqual((run_dir/'base/stderr.log').read_bytes(), b'assertion detail')

    def test_runner_failure_without_report_cannot_be_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root/'srcMove'
            binary.touch()
            with patch('moveSelectionBench.benchmark.subprocess.run', return_value=subprocess.CompletedProcess([], 2, b'', b'missing tool')):
                with self.assertRaisesRegex(RuntimeError, 'did not complete'):
                    run_benchmark(variants={'base': binary}, output_root=root/'results', baseline='base', run_id='run')
            self.assertEqual(json.loads((root/'results/run/manifest.json').read_text())['status'], 'invalid_run')

    def test_teardown_error_cannot_be_hidden_by_passing_method(self):
        completed = report('pass')
        completed['outcomes'].append({'id': 'tearDownClass', 'status': 'error'})
        summary = summarize({'base': completed}, 'base')
        self.assertEqual(summary['variants']['base'], {'pass': 1, 'error': 1})
        self.assertEqual(summary['hard_failures'], 1)
