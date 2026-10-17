from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from bigMoveBench.review import _case_diagnosis, _fence, _markdown, write_type3_review
from tests.tooling.bigmovebench import test_benchmark_cases
from tests.tooling.results_fixtures import schema3_fixture
from srcmove_runtime.results_schema import validate_results


class Type3ReviewTests(unittest.TestCase):
    def test_diagnoses_expected_pair_verification_failure(self) -> None:
        results = diagnostic_results()
        validate_results(results)
        diagnosis = _case_diagnosis(
            "srcmove_miss", results, "void before() {}", "void after() {}"
        )
        self.assertEqual(diagnosis["stage"], "verification")
        self.assertEqual(diagnosis["reason"], "below_threshold")
        self.assertEqual(diagnosis["token_similarity"], 0.6)

    def test_unevaluated_similarity_remains_absent(self):
        results = diagnostic_results(unevaluated=True)
        validate_results(results)
        diagnosis = _case_diagnosis('srcmove_miss', results, 'void before() {}', 'void after() {}')
        self.assertEqual(diagnosis['stage'], 'ambiguity')
        self.assertIsNone(diagnosis['line_similarity'])
        self.assertIsNone(diagnosis['token_similarity'])
        self.assertIsNone(diagnosis['best_expected_pair']['common_lines'])

    def test_diagnosis_accepts_known_receipt_metadata_but_rejects_unknown_fields(self):
        results = diagnostic_results()
        results['_oracle_complete_detection'] = False
        before = json.dumps(results, sort_keys=True)
        diagnosis = _case_diagnosis('srcmove_miss', results, 'void before() {}', 'void after() {}')
        self.assertEqual(diagnosis['stage'], 'verification')
        self.assertEqual(json.dumps(results, sort_keys=True), before)
        results['_oracle_unrecognized'] = 'unknown'
        self.assertEqual(_case_diagnosis('srcmove_miss', results, 'void before() {}', 'void after() {}')['reason'], 'invalid_results')

    def test_invalid_summary_stays_forensic_without_invented_zero_count(self):
        malformed = {'results_schema_version': 3, 'summary': 'invalid'}
        diagnosis = _case_diagnosis('oracle_failure', malformed, 'before', 'after')
        self.assertEqual(diagnosis, {'stage': 'results_admission', 'reason': 'invalid_results'})
        markdown = _markdown([{'ordinal': 1, 'outcome': 'oracle_failure', 'strength_stratum': 'unknown',
                               'case_id': 'bad-result', 'type3_both_similarity': None, 'diagnosis': diagnosis,
                               'expected': {'from_text': 'before', 'to_text': 'after'}, 'results': malformed}])
        self.assertIn('Atomic groups: `unavailable`', markdown)
        self.assertIn('No admitted results are available.', markdown)

    def test_markdown_fence_expands_around_embedded_backticks(self) -> None:
        rendered = _fence("// ``` embedded")
        self.assertTrue(rendered.startswith("````java\n"))
        self.assertTrue(rendered.endswith("\n````"))

    def test_writes_deterministic_complete_review_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = test_benchmark_cases.NormalizedBenchmarkCasesTests()
            _, _, benchmark_cases, _ = fixture.publish_fixture(root)
            with sqlite3.connect(
                benchmark_cases.directory / "benchmark_cases.sqlite"
            ) as connection:
                case_id = connection.execute("SELECT case_id FROM cases").fetchone()[0]

            journal = root / "execution.sqlite"
            run_dir = root / "run"
            srcdiff_attempt = run_dir / "tool-attempts" / "srcdiff" / "attempt-1"
            srcmove_attempt = run_dir / "tool-attempts" / "srcmove" / "attempt-1"
            srcdiff_attempt.mkdir(parents=True)
            srcmove_attempt.mkdir(parents=True)
            (srcdiff_attempt / "srcdiff.xml").write_text("<unit/>", encoding="utf-8")
            (srcmove_attempt / "srcmove.xml").write_text("<unit/>", encoding="utf-8")
            results = schema3_fixture({'moves': [
                {'move_id': 'm1', 'content_relationship': 'type1',
                 'from_raw_texts': ['incidental source'], 'to_raw_texts': ['incidental destination']}]})
            results.update(_oracle_expected_category='type3', _oracle_complete_detection=False,
                           _oracle_diagnostic_stage='selection_or_granularity')
            with sqlite3.connect(journal) as connection:
                connection.execute(
                    "CREATE TABLE attempts (case_id TEXT, status TEXT, "
                    "attempt_ordinal INTEGER, outcome TEXT, oracle_results_json TEXT, "
                    "oracle_failures_json TEXT, text_validation_json TEXT, "
                    "srcdiff_attempt_path TEXT, srcmove_attempt_path TEXT)"
                )
                connection.execute(
                    "INSERT INTO attempts VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        case_id,
                        "terminal",
                        1,
                        "srcmove_miss",
                        json.dumps(results),
                        json.dumps(["expected pair missing"]),
                        json.dumps({"from": "failed", "to": "failed"}),
                        str(srcdiff_attempt.relative_to(run_dir)),
                        str(srcmove_attempt.relative_to(run_dir)),
                    ),
                )

            first = write_type3_review(
                run_dir, journal_path=journal, benchmark_cases=benchmark_cases
            )
            second = write_type3_review(
                run_dir, journal_path=journal, benchmark_cases=benchmark_cases
            )
            self.assertEqual(first, second)
            self.assertEqual(first["case_count"], 1)
            records = [
                json.loads(line)
                for line in (run_dir / "type3-review.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["results"], results)
            case_dir = run_dir / 'type3-review/cases/0001'
            bundle_results = json.loads((case_dir / 'results.json').read_text())
            validate_results(bundle_results)
            self.assertNotIn('_oracle_expected_category', bundle_results)
            self.assertEqual(json.loads((case_dir / 'review.json').read_text())['results'], results)
            manifest = json.loads((run_dir / 'type3-review/manifest.json').read_text())
            self.assertEqual(manifest['cases'][0]['result_evidence']['status'], 'admitted')
            self.assertTrue(records[0]["expected"]["from_text"])
            markdown = (run_dir / "type3-review.md").read_text(encoding="utf-8")
            self.assertIn("incidental source", markdown)
            self.assertIn("AI agrees?:", markdown)
            self.assertIn("Human verdict:", markdown)
            self.assertTrue((run_dir / "type3-review.zip").is_file())
            self.assertTrue(
                (
                    run_dir
                    / "type3-review"
                    / "cases"
                    / "0001"
                    / "srcmove.xml"
                ).is_file()
            )


def diagnostic_results(unevaluated=False):
    result = schema3_fixture({})
    result['pipeline_statistics']['grouped_candidate_entry_count'] = 2
    result['diagnostics'] = {
        'schema_version': 5, 'candidate_counts': {'registered': 8, 'active': 2},
        'candidates': [
            {'candidate_id': number, 'revision': side, 'role': 'structural_child',
             'selected_group_id': None, 'type3_eligible': True, 'line_units': 4, 'token_units': 10,
             'endpoint': {'candidate_id': number, 'revision_file': None, 'construct': 'function',
                          'xpath': f'/src:unit[1]/diff:{kind}[1]/src:function[1]', 'raw_text': text}}
            for number, side, kind, text in [(4, 'original', 'delete', 'void before() {}'),
                                              (7, 'modified', 'insert', 'void after() {}')]],
        'correspondences': [], 'type2b_groups': [],
        'type3_comparisons': [{'id': 'comparison:4:7', 'original_candidate_id': 4, 'modified_candidate_id': 7,
                               'verification': {'status': 'not_evaluated' if unevaluated else 'below_threshold',
                                                'reason': 'ambiguous_type2c' if unevaluated else None,
                                                'lines': {'common': None if unevaluated else 2, 'maximum': 4},
                                                'tokens': {'common': None if unevaluated else 6, 'maximum': 10}},
                               'selection': {'status': 'not_applicable', 'selected_group_id': None, 'reason': None}}]}
    return result


if __name__ == "__main__":
    unittest.main()
