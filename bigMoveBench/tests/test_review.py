from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from bigMoveBench.review import _case_diagnosis, _fence, write_type3_review
from bigMoveBench.tests import test_benchmark_cases


class Type3ReviewTests(unittest.TestCase):
    def test_diagnoses_expected_pair_verification_failure(self) -> None:
        results = {
            "move_count": 0,
            "moves": [],
            "candidates_total": 2,
            "diagnostics": {
                "candidates": [
                    {
                        "candidate_id": 4,
                        "side": "delete",
                        "construct": "function",
                        "raw_text": "void before() {}",
                        "type3_eligible": True,
                        "line_units": 4,
                        "token_units": 10,
                    },
                    {
                        "candidate_id": 7,
                        "side": "insert",
                        "construct": "function",
                        "raw_text": "void after() {}",
                        "type3_eligible": True,
                        "line_units": 4,
                        "token_units": 10,
                    },
                ],
                "type3_pairs": [
                    {
                        "delete_candidate_id": 4,
                        "insert_candidate_id": 7,
                        "outcome": "below_threshold",
                        "common_lines": 2,
                        "maximum_lines": 4,
                        "common_tokens": 6,
                        "maximum_tokens": 10,
                    }
                ],
            },
        }
        diagnosis = _case_diagnosis(
            "srcmove_miss", results, "void before() {}", "void after() {}"
        )
        self.assertEqual(diagnosis["stage"], "verification")
        self.assertEqual(diagnosis["reason"], "below_threshold")
        self.assertEqual(diagnosis["token_similarity"], 0.6)

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
            results = {
                "move_count": 1,
                "moves": [
                    {
                        "move_id": "m1",
                        "match_kind": "type1",
                        "from_raw_texts": ["incidental source"],
                        "to_raw_texts": ["incidental destination"],
                    }
                ],
                "diagnostics": {"schema_version": 1, "candidates": [], "type3_pairs": []},
            }
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
            self.assertEqual(records[0]["results"]["diagnostics"], results["diagnostics"])
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


if __name__ == "__main__":
    unittest.main()
