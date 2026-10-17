"""Saved oracle receipts carry metadata outside the strict producer contract."""
import copy
import unittest

from bigMoveBench.evaluate import diagnostic_stage
from srcmove_runtime.results_schema import benchmark_result_evidence, validate_results
from tests.tooling.results_fixtures import schema3_fixture


class BenchmarkResultReceiptsTests(unittest.TestCase):
    def test_known_metadata_extracts_without_mutating_receipt_or_weakening_raw_admission(self):
        evidence = schema3_fixture({'moves': [dict(move_id='m1', from_raw_texts=['a'], to_raw_texts=['b'])]})
        receipt = copy.deepcopy(evidence)
        receipt.update(_oracle_expected_category='type1', _oracle_complete_detection=False,
                       _oracle_diagnostic_stage='selection_or_granularity',
                       _oracle_reviewed_outcome='srcmove_miss', _oracle_reviewed_failures=['partial move'])
        original = copy.deepcopy(receipt)
        with self.assertRaises(ValueError):
            validate_results(receipt)
        self.assertEqual(benchmark_result_evidence(receipt), evidence)
        self.assertEqual(receipt, original)
        self.assertEqual(diagnostic_stage('srcmove_miss', receipt), 'selection_or_granularity')

    def test_csv_keeps_malformed_receipt_but_does_not_project_unvalidated_groups(self):
        import csv
        import json
        from pathlib import Path
        import sqlite3
        import tempfile
        from unittest.mock import patch
        from tests.tooling.bigmovebench import test_normalized_execution, test_benchmark_cases
        helper = test_normalized_execution.NormalizedExecutionTests()
        fixture = test_benchmark_cases.NormalizedBenchmarkCasesTests()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, _, cases, _ = fixture.publish_two_case_fixture(root)
            run_dir = root / 'run'
            tools = test_normalized_execution.FakeToolAttempts()
            patches = helper._successful_patches(tools)
            malformed = {'results_schema_version': 3, '_oracle_observed_content_relationship': 'type3'}
            scored = ('oracle_failure', ['invalid structure'], {'from': 'not_checked', 'to': 'not_checked'}, malformed)
            with patches[0], patches[1], patch('bigMoveBench.normalized_execution._score_completed_case', return_value=scored):
                helper._runner(cases, run_dir).run()
            with (run_dir / 'cases.csv').open() as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(rows[0]['observed_content_relationship'], '')
            with sqlite3.connect(run_dir / 'execution.sqlite') as connection:
                receipts = [json.loads(row[0]) for row in connection.execute('SELECT oracle_results_json FROM attempts')]
            self.assertEqual(receipts[0]['_oracle_observed_content_relationship'], 'type3')
            self.assertEqual(receipts[0]['results_schema_version'], 3)

    def test_unknown_metadata_and_old_wire_versions_are_rejected(self):
        for key in ('unexpected', '_oracle_unknown_future_field'):
            receipt = schema3_fixture({})
            receipt[key] = 'not trusted'
            with self.subTest(key=key), self.assertRaises(ValueError):
                benchmark_result_evidence(receipt)
        with self.assertRaises(ValueError):
            benchmark_result_evidence({'results_schema_version': 2, 'moves': []})
