from __future__ import annotations

import csv
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "benchmark" / "bigclonebench_cases.json"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.bigclonebench.adapter import BigCloneBenchAdapter
from benchmarks.bigclonebench.evaluate import _score_completed_case, write_evaluation
from benchmarks.bigclonebench.pipeline import _report_benchmark_result, parse_args
from benchmarks.corpus import create_input_snapshot, generate_corpus, run_corpus
from benchmarks.provenance import sha256_file


def write_executable(path: Path, source: str) -> Path:
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)
    return path


class BigCloneBenchPipelineTests(unittest.TestCase):
    def test_combined_result_report_separates_oracle_and_tool_outcomes(self) -> None:
        summary = {
            "counts": {
                "selected": 200,
                "oracle_pass": 199,
                "upstream_failure": 0,
                "srcdiff_semantic_ineligible": 0,
                "srcmove_tool_failure": 0,
                "srcmove_miss": 1,
                "wrong_classification": 0,
                "oracle_failure": 0,
            },
            "declared_slice": {
                "clone_type": "type1",
                "dedupe": "raw-text-pair",
                "text_change": "any",
                "min_tokens": 50,
                "row_count_before_deduplication": 35_802,
                "distinct_raw_text_pair_count": 200,
                "functionality_group_count": 3,
                "selection": {"role": "tuning"},
            },
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            run_dir = Path(temporary_directory)
            with (run_dir / "cases.csv").open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(
                    stream, fieldnames=("case_id", "outcome", "diagnostic_class")
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "case_id": "bcb_t1_000012",
                        "outcome": "srcmove_miss",
                        "diagnostic_class": "no_move_raw_different",
                    }
                )
            output = io.StringIO()
            with redirect_stdout(output):
                passed = _report_benchmark_result(run_dir, summary)

        report = output.getvalue()
        self.assertFalse(passed)
        self.assertIn("BigCloneBench result: FAIL", report)
        self.assertIn("199/200 passed (99.5%)", report)
        self.assertIn("1 srcMove miss", report)
        self.assertIn("no move; raw text differs", report)
        self.assertIn("200 cases from 35,802 eligible candidates", report)
        self.assertIn("200 distinct raw-text pairs across 3 functionality groups", report)
        self.assertIn("summary.json, cases.csv", report)

    def test_combined_benchmark_cli_needs_no_intermediate_identifier(self) -> None:
        arguments = [
            "pipeline.py",
            "benchmark",
            "--clone-type",
            "type1",
            "--srcdiff",
            "/tmp/srcdiff",
            "--srcmove",
            "/tmp/srcMove",
        ]
        with mock.patch.object(sys, "argv", arguments):
            args = parse_args()
        self.assertEqual(args.stage, "benchmark")
        self.assertFalse(hasattr(args, "input_snapshot"))
        self.assertFalse(hasattr(args, "corpus"))

    def test_type_two_scoring_requires_type2_match_kind(self) -> None:
        metadata = {
            "syntactic_type": 2,
            "expected": {
                "from_raw_text": "void moved() {}\n",
                "to_raw_text": "void moved() {}\n",
                "from_generated_text": "void moved() {}\n",
                "to_generated_text": "void moved() {}\n",
                "from_start_line": 3,
                "from_end_line": 3,
                "to_start_line": 5,
                "to_end_line": 5,
            },
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            srcmove_xml = root / "srcmove.xml"
            srcmove_xml.write_text(
                "<unit xmlns='http://www.srcML.org/srcML/src' "
                "xmlns:diff='http://www.srcML.org/srcDiff/diff' "
                "xmlns:mv='http://www.srcML.org/srcMove' "
                "xmlns:pos='http://www.srcML.org/srcML/position'>"
                "<diff:delete mv:id='m1' mv:to='target' "
                "pos:start='3:1|3:1' pos:end='3:10|3:10'/>"
                "<diff:insert mv:id='m1' mv:from='source' "
                "pos:start='5:1|5:1' pos:end='5:10|5:10'/>"
                "</unit>"
            )
            results_path = root / "results.json"
            for match_kind, expected_outcome in (
                ("exact", "wrong_classification"),
                ("type2", "oracle_pass"),
            ):
                results_path.write_text(
                    json.dumps(
                        {
                            "move_count": 1,
                            "match_kinds": {match_kind: 1},
                            "moves": [
                                {
                                    "match_kind": match_kind,
                                    "from_raw_texts": ["void moved() {}\n"],
                                    "to_raw_texts": ["void moved() {}\n"],
                                }
                            ],
                        }
                    )
                )
                with self.subTest(match_kind=match_kind):
                    outcome, _, _, _ = _score_completed_case(
                        metadata=metadata,
                        results_path=results_path,
                        srcmove_xml=srcmove_xml,
                    )
                    self.assertEqual(outcome, expected_outcome)

    def test_fixture_corpus_replays_across_builds_and_reconciles_outcomes(self) -> None:
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            cases_dir = root / "cases"
            cases_dir.mkdir()
            manifest = {
                "schema_version": 2,
                "dataset": "BigCloneBench",
                "dataset_identity": {"database_sha256": "fixture"},
                "syntactic_type": 1,
                "clone_type": "type1",
                "dedupe": "raw-text-pair",
                "text_change": "any",
                "min_tokens": 1,
                "row_count_before_deduplication": len(fixture["cases"]),
                "distinct_raw_text_pair_count": len(fixture["cases"]),
                "functionality_group_count": 1,
                "selected_count": len(fixture["cases"]),
                "cases": fixture["cases"],
                "selected_source_files": [],
                "selection": {
                    "role": "tuning",
                    "method": "fixture_census",
                    "population_claim": "fixture_only",
                    "eligibility_query": "fixture",
                    "query_parameters": {},
                    "pair_direction": "fragment_one_deleted_fragment_two_inserted",
                    "ordered_selected_row_ids": [
                        [index, index + 100]
                        for index, _ in enumerate(fixture["cases"], start=1)
                    ],
                },
                "versions": {
                    "generator_sha256": "fixture-generator",
                    "position_text_oracle_sha256": "fixture-position-oracle",
                    "semantic_oracle_sha256": "fixture-semantic-oracle",
                },
            }
            (cases_dir / "bcb_t1_manifest.json").write_text(json.dumps(manifest))
            for index, case_id in enumerate(fixture["cases"], start=1):
                case_dir = cases_dir / case_id
                case_dir.mkdir()
                (case_dir / "original.java").write_text(f"// {case_id}\nclass Old {{}}\n")
                (case_dir / "modified.java").write_text(f"// {case_id}\nclass New {{}}\n")
                metadata = {
                    "source": "BigCloneBench fixture",
                    "syntactic_type": fixture["syntactic_type"],
                    "function_id_one": index,
                    "function_id_two": index + 100,
                    "fragment_relation": {
                        "raw_text_identical": True,
                        "trimmed_text_identical": True,
                    },
                    "expected": fixture["expected"],
                }
                (case_dir / "metadata.json").write_text(json.dumps(metadata))

            srcdiff = write_executable(
                root / "srcdiff-fixture",
                """#!/usr/bin/env python3
import sys
from pathlib import Path
case_id = Path(sys.argv[-3]).parents[1].name
output = Path(sys.argv[sys.argv.index('-o') + 1])
if case_id == 'upstream-failure':
    raise SystemExit(23)
if case_id == 'semantic-ineligible':
    body = '<name>aligned</name>'
else:
    body = ("<diff:delete><function pos:start='3:1|3:1' pos:end='4:1|4:1'>"
            "void moved() {}</function></diff:delete>"
            "<diff:insert><function pos:start='5:1|5:1' pos:end='6:1|6:1'>"
            "void moved() {}</function></diff:insert>")
output.write_text("<unit xmlns='http://www.srcML.org/srcML/src' "
                  "xmlns:diff='http://www.srcML.org/srcDiff/diff' "
                  "xmlns:pos='http://www.srcML.org/srcML/position' "
                  f"case='{case_id}'>{body}</unit>")
""",
            )
            srcmove_source = """#!/usr/bin/env python3
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
input_xml, output_xml = Path(sys.argv[1]), Path(sys.argv[2])
case_id = ET.parse(input_xml).getroot().attrib['case']
if case_id == 'srcmove-tool-failure':
    raise SystemExit(31)
kind = 'type2' if case_id == 'wrong-classification' else 'exact'
moves = [] if case_id == 'srcmove-miss' else [{
    'match_kind': kind,
    'from_raw_texts': ['void moved() {\\n}\\n'],
    'to_raw_texts': ['void moved() {\\n}\\n'],
    'from_xpaths': ['/src:unit/diff:delete[1]'],
    'to_xpaths': ['/src:unit/diff:insert[1]'],
}]
results = {'move_count': len(moves), 'match_kinds': {kind: len(moves)}, 'moves': moves}
Path(sys.argv[sys.argv.index('--results') + 1]).write_text(json.dumps(results))
output_xml.write_text("<unit xmlns='http://www.srcML.org/srcML/src' "
    "xmlns:diff='http://www.srcML.org/srcDiff/diff' "
    "xmlns:mv='http://www.srcML.org/srcMove' "
    "xmlns:pos='http://www.srcML.org/srcML/position'>"
    "<diff:delete mv:id='m1' mv:to='target' pos:start='3:1|3:1' pos:end='4:1|4:1'/>"
    "<diff:insert mv:id='m1' mv:from='source' pos:start='5:1|5:1' pos:end='6:1|6:1'/>"
    "</unit>")
"""
            srcmove_a = write_executable(root / "srcmove-build-a", srcmove_source)
            srcmove_b = write_executable(
                root / "srcmove-build-b", srcmove_source + "\n# second build\n"
            )

            data_root = root / "benchmark-data"
            adapter = BigCloneBenchAdapter(cases_dir, 1)
            _, input_snapshot = create_input_snapshot(
                data_root=data_root, adapter=adapter, source=adapter.source_manifest()
            )
            corpus_dir, corpus = generate_corpus(
                data_root=data_root,
                input_snapshot=input_snapshot["input_snapshot_id"],
                srcdiff=srcdiff,
                timeout_seconds=2.0,
                use_position=True,
                use_archive=False,
                semantic_validator=BigCloneBenchAdapter.validate_semantics,
                semantic_oracle={"name": "fixture", "version": 1},
            )
            corpus_manifest_checksum = sha256_file(corpus_dir / "manifest.json")

            summaries = []
            runs = []
            for executable in (srcmove_a, srcmove_b):
                run_dir, run = run_corpus(
                    data_root=data_root,
                    corpus=corpus_dir,
                    srcmove=executable,
                    timeout_seconds=2.0,
                    require_semantic_eligible=True,
                )
                runs.append(run)
                summaries.append(
                    write_evaluation(
                        run_dir=run_dir,
                        run_manifest=run,
                        corpus_dir=corpus_dir,
                        corpus_manifest=corpus,
                    )
                )

            self.assertEqual(sha256_file(corpus_dir / "manifest.json"), corpus_manifest_checksum)
            self.assertNotEqual(summaries[0]["run_id"], summaries[1]["run_id"])
            self.assertNotEqual(
                runs[0]["observation"]["executables"]["srcMove"]["artifact"]["sha256"],
                runs[1]["observation"]["executables"]["srcMove"]["artifact"]["sha256"],
            )
            expected_counts = {
                "selected": 6,
                "eligible": 4,
                "executed": 4,
                "upstream_failure": 1,
                "srcdiff_semantic_ineligible": 1,
                "srcmove_tool_failure": 1,
                "srcmove_miss": 1,
                "wrong_classification": 1,
                "oracle_failure": 0,
                "oracle_pass": 1,
                "strict_passes": 1,
                "encoding_tolerant_passes": 0,
            }
            for summary in summaries:
                self.assertEqual(summary["counts"], expected_counts)
                rows_path = data_root / "runs" / summary["run_id"] / "cases.csv"
                with rows_path.open(encoding="utf-8") as stream:
                    rows = list(csv.DictReader(stream))
                wrong = next(row for row in rows if row["case_id"] == "wrong-classification")
                self.assertEqual(wrong["outcome"], "wrong_classification")
                self.assertEqual(wrong["expected_match_kind"], "exact")
                self.assertEqual(wrong["observed_match_kind"], "type2")
                self.assertNotEqual(wrong["outcome"], "oracle_pass")

    def test_adapter_rejects_mismatched_selection_and_case_types(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            cases_dir = Path(temporary_directory)
            manifest = {
                "schema_version": 2,
                "dataset": "BigCloneBench",
                "dataset_identity": {},
                "syntactic_type": 2,
                "clone_type": "type2",
                "dedupe": "raw-text-pair",
                "text_change": "any",
                "min_tokens": 50,
                "row_count_before_deduplication": 1,
                "distinct_raw_text_pair_count": 1,
                "functionality_group_count": 1,
                "selected_count": 1,
                "cases": ["case-one"],
                "selected_source_files": [],
                "selection": {
                    "role": "tuning",
                    "method": "fixture",
                    "population_claim": "none",
                    "eligibility_query": "fixture",
                    "query_parameters": {},
                    "pair_direction": "fragment_one_deleted_fragment_two_inserted",
                    "ordered_selected_row_ids": [[1, 2]],
                },
                "versions": {
                    "generator_sha256": "generator",
                    "position_text_oracle_sha256": "position",
                    "semantic_oracle_sha256": "semantic",
                },
            }
            (cases_dir / "bcb_t1_manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "invalid generated selection"):
                BigCloneBenchAdapter(cases_dir, 1)

            (cases_dir / "bcb_t2_manifest.json").write_text(json.dumps(manifest))
            case_dir = cases_dir / "case-one"
            case_dir.mkdir()
            (case_dir / "original.java").write_text("class Old {}\n")
            (case_dir / "modified.java").write_text("class New {}\n")
            (case_dir / "metadata.json").write_text(
                json.dumps(
                    {
                        "syntactic_type": 1,
                        "function_id_one": 1,
                        "function_id_two": 2,
                    }
                )
            )
            with self.assertRaisesRegex(ValueError, "syntactic_type"):
                BigCloneBenchAdapter(cases_dir, 2).input_pairs()

            (case_dir / "metadata.json").write_text(
                json.dumps(
                    {
                        "syntactic_type": 2,
                        "function_id_one": 9,
                        "function_id_two": 10,
                    }
                )
            )
            with self.assertRaisesRegex(ValueError, "row identity"):
                BigCloneBenchAdapter(cases_dir, 2).input_pairs()


if __name__ == "__main__":
    unittest.main()
