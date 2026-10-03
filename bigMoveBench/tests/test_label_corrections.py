from __future__ import annotations

import copy
import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bigMoveBench.evaluate import _score_completed_case
from bigMoveBench.label_corrections import LabelCorrections
from bigMoveBench.suite import _pair_set_operational_pass
from bigMoveBench.tests import test_benchmark_cases, test_normalized_execution


class LabelCorrectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.before = 'void moved() { ; return; }'
        self.after = 'void moved() { return; }'
        self.entry = {
            'id': 'empty-statement-test', 'function_ids': [1, 2],
            'fragment_sha256': [hashlib.sha256(t.encode()).hexdigest() for t in (self.before, self.after)],
            'original_match_kind': 'type2', 'reviewed_match_kind': 'type3',
            'reason': 'Removed statement',
        }
        self.path = self.root / 'registry.json'
        self.path.write_text(json.dumps({'schema_version': 1, 'pair_policy': 'unordered_exact_utf8_sha256', 'corrections': [self.entry]}))
        self.registry = LabelCorrections(self.path)
        self.metadata = {
            'syntactic_type': 2,
            'fragment_one': {'text': self.before, 'sha256': self.entry['fragment_sha256'][0]},
            'fragment_two': {'text': self.after, 'sha256': self.entry['fragment_sha256'][1]},
            'expected': {'from_generated_text': self.before, 'to_generated_text': self.after,
                         'from_start_line': 3, 'from_end_line': 3,
                         'to_start_line': 7, 'to_end_line': 7},
        }
        self.xml = self.root / 'srcmove.xml'
        self.xml.write_text("<unit xmlns:mv='http://www.srcML.org/srcMove' xmlns:pos='http://www.srcML.org/srcML/position'><function mv:id='m1' mv:to='x' pos:start='3:1' pos:end='3:30'/><function mv:id='m1' mv:from='y' pos:start='7:1' pos:end='7:30'/></unit>")

    def score(self, kind='type3', partial=False, missing=False, invalid=False):
        moves = [] if missing else [{'move_id': 'm1', 'match_kind': kind, 'from_raw_texts': ['return;' if partial else self.before], 'to_raw_texts': [self.after]}]
        results = {'results_schema_version': 0 if invalid else 1, 'move_count': len(moves), 'moves': moves, 'match_kinds': {kind: len(moves)}}
        path = self.root / 'results.json'
        path.write_text(json.dumps(results))
        return _score_completed_case(metadata=self.metadata, results_path=path, srcmove_xml=self.xml, label_corrections=self.registry)

    def test_reviewed_match_preserves_raw_failure_and_rejects_old_label(self):
        outcome, failures, _, results = self.score()
        self.assertEqual(outcome, 'wrong_classification')
        self.assertTrue(failures)
        self.assertEqual(results['_oracle_reviewed_outcome'], 'oracle_pass')
        self.assertEqual(results['_oracle_label_correction'], self.entry)
        outcome, _, _, results = self.score('type2')
        self.assertEqual(outcome, 'oracle_pass')
        self.assertEqual(results['_oracle_reviewed_outcome'], 'wrong_classification')
        self.assertTrue(results['_oracle_reviewed_failures'])

    def test_correction_never_bypasses_detection_or_schema_or_position(self):
        for kwargs, expected in [({'partial': True}, 'srcmove_miss'), ({'missing': True}, 'srcmove_miss'), ({'invalid': True}, 'oracle_failure')]:
            with self.subTest(kwargs=kwargs):
                outcome, _, _, results = self.score(**kwargs)
                self.assertEqual(outcome, expected)
                self.assertEqual(results['_oracle_reviewed_outcome'], expected)
        self.xml.write_text('<unit/>')
        self.assertEqual(self.score()[3]['_oracle_reviewed_outcome'], 'srcmove_miss')

    def test_exact_unordered_content_identity_and_snapshot(self):
        self.assertEqual(self.registry.match(self.metadata), self.entry)
        reversed_metadata = copy.deepcopy(self.metadata)
        reversed_metadata['fragment_one'], reversed_metadata['fragment_two'] = reversed_metadata['fragment_two'], reversed_metadata['fragment_one']
        self.assertEqual(self.registry.match(reversed_metadata), self.entry)
        changed = copy.deepcopy(self.metadata)
        changed['fragment_one']['text'] += ' '
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            self.registry.match(changed)
        del changed['fragment_one']['sha256']
        self.assertIsNone(self.registry.match(changed))
        changed = {**self.metadata, 'syntactic_type': 1}
        self.assertIsNone(self.registry.match(changed))
        self.assertIsNone(self.registry.match({**self.metadata, 'case_kind': 'known_false_positive'}))
        self.path.write_text(self.path.read_text() + '\n')
        self.assertNotEqual(self.registry.identity, LabelCorrections(self.path).identity)
        self.assertEqual(self.registry.match(self.metadata), self.entry)

    def test_shipped_review_identity(self):
        registry = LabelCorrections()
        entry = next(
            entry for entry in registry.identity['snapshot']['corrections']
            if entry['id'] == 'bcb-69322-96077-empty-statement'
        )
        self.assertEqual(entry['function_ids'], [69322, 96077])
        self.assertEqual(entry['reviewed_match_kind'], 'type3')

    def test_journal_csv_summary_and_restart_provenance(self):
        helper = test_normalized_execution.NormalizedExecutionTests()
        fixture = test_benchmark_cases.NormalizedBenchmarkCasesTests()
        _, _, cases, _ = fixture.publish_two_case_fixture(self.root)
        run_dir = self.root / 'run'
        tools = test_normalized_execution.FakeToolAttempts()
        patches = helper._successful_patches(tools)
        scored = ('wrong_classification', ['original label differs'], {'from': 'strict', 'to': 'strict'}, {
            '_oracle_reviewed_outcome': 'oracle_pass', '_oracle_reviewed_failures': [],
            '_oracle_label_correction': self.entry,
        })
        with patches[0], patches[1], mock.patch('bigMoveBench.normalized_execution._score_completed_case', return_value=scored):
            runner = helper._runner(cases, run_dir)
            _, summary = runner.run()
        self.assertEqual(summary['counts']['wrong_classification'], 2)
        self.assertEqual(summary['counts']['oracle_pass'], 0)
        self.assertEqual(summary['reviewed_counts']['oracle_pass'], 2)
        self.assertEqual(summary['rates']['end_to_end_detection_and_classification'], 0)
        self.assertEqual(summary['reviewed_rates']['end_to_end_detection_and_classification'], 1)
        self.assertTrue(_pair_set_operational_pass('type2', summary['reviewed_counts']))
        self.assertFalse(_pair_set_operational_pass('type2', summary['counts']))
        with (run_dir / 'cases.csv').open() as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(rows[0]['outcome'], 'wrong_classification')
        self.assertEqual(rows[0]['reviewed_outcome'], 'oracle_pass')
        self.assertEqual(rows[0]['label_correction_id'], self.entry['id'])
        self.assertEqual(rows[0]['reviewed_expected_match_kind'], 'type3')
        runner = helper._runner(cases, run_dir)
        runner.provenance['label_corrections']['sha256'] = '0' * 64
        with self.assertRaises(ValueError):
            runner.run()
