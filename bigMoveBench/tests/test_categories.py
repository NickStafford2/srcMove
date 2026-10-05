from __future__ import annotations

import csv
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bigMoveBench.categories import (
    CATEGORY_RULES_VERSION, benchmark_category, category_metrics, category_sql,
)
from bigMoveBench.benchmark_cases import publish_benchmark_cases, SerialBenchmarkCaseRunner
from bigMoveBench.catalog import compile_exports
from bigMoveBench.evaluate import _score_completed_case, validate_results_output
from bigMoveBench.frozen_profiles import _rows
from bigMoveBench.tests import test_catalog
from bigMoveBench.tests.test_catalog import pair_row, write_export


class CategoryTests(unittest.TestCase):
    def test_upstream_boundaries_python_and_sql_agree(self):
        db = sqlite3.connect(":memory:")
        db.execute("CREATE TABLE p(syntactic_type, similarity_line, similarity_token)")
        for kind, line, token, expected in (
            (1, .5, .5, "type1"), (2, .5, .5, "type2c"),
            (3, 1., 1., "type2b"), (3, 1., .999999, "type3"),
            (3, .999999, 1., "type3"), (3, .9, .9, "type3"),
            (3, .7, .7, "type3"), (3, .5, .5, "type3"), (3, .49, .49, "type3"),
        ):
            with self.subTest(kind=kind, line=line, token=token):
                row = dict(syntactic_type=kind, similarity_line=line, similarity_token=token)
                self.assertEqual(benchmark_category(row), expected)
                db.execute("DELETE FROM p")
                db.execute("INSERT INTO p VALUES(?,?,?)", (kind, line, token))
                self.assertEqual(db.execute("SELECT " + category_sql() + " FROM p").fetchone()[0], expected)
        self.assertEqual(benchmark_category(dict(pair_kind="known_false_positive", syntactic_type=3)), "known_false_positive")
        db.close()

    def test_selection_generation_preserves_raw_fields_and_exclusive_membership(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bce = test_catalog.BigCloneBenchCompiledDatasetTests().create_bce(root)
            exports = root / "exports"
            exports.mkdir()
            rows = []
            for kind, line, token in ((2, .8, .8), (3, 1., 1.), (3, .99, 1.), (3, 1., .99)):
                row = pair_row()
                row.update(syntactic_type=kind, similarity_line=line, similarity_token=token)
                rows.append(row)
            write_export(exports / "positive.csv", rows)
            write_export(exports / "false.csv", [])
            compiled = compile_exports(bce_dir=bce, data_root=root / "data",
                exports={"positive": exports / "positive.csv", "known_false_positive": exports / "false.csv"},
                compile_scope={"fixture": "categories"})
            from bigMoveBench.selection import create_selection
            for category, raw_type, count in (("type2c", 2, 1), ("type2b", 3, 1), ("type3", 3, 2)):
                selection, manifest, _ = create_selection(compiled, data_root=root / "data", pair_set=category, mode="census")
                self.assertEqual(manifest["counts"]["selected_catalog_rows"], count)
                frames = [json.loads(line) for line in (selection / "frames.jsonl").read_text().splitlines()]
                for row in frames[0]["rows"]:
                    self.assertEqual(row["benchmark_category"], category)
                    self.assertEqual(row["syntactic_type"], raw_type)
                    self.assertIn("similarity", row)
                cases, _ = publish_benchmark_cases(data_root=root / "data", selection=selection)
                with SerialBenchmarkCaseRunner(cases) as runner:
                    case = next(runner.cases())
                    self.assertEqual(case.metadata["benchmark_category"], category)
                    self.assertEqual(case.metadata["category_rules_version"], CATEGORY_RULES_VERSION)
                    self.assertEqual(case.metadata["syntactic_type"], raw_type)
                    if category == "type2b":
                        self.assertIsNone(case.metadata["type3_strength_stratum"])
                if category == "type2b":
                    from bigMoveBench.tests import test_normalized_execution
                    execution = test_normalized_execution.NormalizedExecutionTests()
                    tools = test_normalized_execution.FakeToolAttempts()
                    patches = execution._successful_patches(tools)
                    outcome, failures, validation, evidence = self.score("type2b", "type3")
                    with patches[0], patches[1], mock.patch(
                        "bigMoveBench.normalized_execution._score_completed_case",
                        return_value=(outcome, failures, validation, evidence)):
                        _, summary = execution._runner(cases, root / "blind-run").run()
                    report = summary["category_reports"]["type2b"]
                    self.assertEqual(report["complete_detections"], 1)
                    self.assertEqual(report["original_category_agreements"], 0)
                    self.assertEqual(report["reported_categories_among_complete_detections"],
                                     {"type3": {"count": 1, "rate": 1.}})


    def score(self, category, reported, *, partial=False, legacy=False, negative=False):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata = dict(syntactic_type=2 if category == "type2c" else 3,
                expected=dict(from_generated_text="void before() {}", to_generated_text="void after() {}",
                    from_start_line=3, from_end_line=3, to_start_line=7, to_end_line=7))
            if negative:
                metadata["case_kind"] = "known_false_positive"
            if not legacy:
                metadata.update(category_rules_version=CATEGORY_RULES_VERSION, benchmark_category=category)
            results = dict(results_schema_version=2, move_count=1, content_relationships={reported: 1}, moves=[
                dict(move_id="m1", content_relationship=reported, from_raw_texts=["{}" if partial else "void before() {}"],
                     to_raw_texts=["{}" if partial else "void after() {}"], from_xpaths=["/src:function"], to_xpaths=["/src:function"])])
            path = root / "results.json"
            path.write_text(json.dumps(results))
            self.assertEqual(validate_results_output(path)["status"], "valid")
            xml = root / "srcmove.xml"
            xml.write_text("<unit xmlns:mv='http://www.srcML.org/srcMove' xmlns:pos='urn:pos'>"
                "<delete mv:id='m1' mv:to='to' pos:start='3:1' pos:end='3:20'/>"
                "<insert mv:id='m1' mv:from='from' pos:start='7:1' pos:end='7:20'/></unit>")
            return _score_completed_case(metadata=metadata, results_path=path, srcmove_xml=xml)

    def test_consistent_output(self):
        self.assertEqual(self.score("type2c", "type2c")[0], "oracle_pass")
        self.assertEqual(self.score("type2b", "type2c")[0], "wrong_classification")

    def test_negative_oracle_keeps_whole_pair_rejection(self):
        for reported in ("type2c", "type3"):
            with self.subTest(reported=reported):
                self.assertEqual(self.score("type2c", reported, negative=True)[0], "srcmove_false_positive")
                self.assertEqual(self.score("type2c", reported, negative=True, partial=True)[0], "oracle_pass")

    def test_complete_blind_detection_with_mismatch_and_partial_miss(self):
        outcome, _, _, evidence = self.score("type2b", "type3")
        self.assertEqual(outcome, "wrong_classification")
        self.assertTrue(evidence["_oracle_complete_detection"])
        self.assertEqual(evidence["_oracle_observed_content_relationship"], "type3")
        outcome, _, _, evidence = self.score("type2b", "type3", partial=True)
        self.assertEqual(outcome, "srcmove_miss")
        self.assertFalse(evidence["_oracle_complete_detection"])

    def test_category_report_journal_csv_and_summary(self):
        from bigMoveBench.tests import test_benchmark_cases, test_normalized_execution
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = test_benchmark_cases.NormalizedBenchmarkCasesTests()
            _, _, cases, _ = fixture.publish_fixture(root, "type2c")
            execution = test_normalized_execution.NormalizedExecutionTests()
            tools = test_normalized_execution.FakeToolAttempts()
            patches = execution._successful_patches(tools)
            run_dir = root / "run"
            evidence = {"move_count": 1, "_oracle_complete_detection": True,
                "_oracle_observed_content_relationship": "type2c", "_oracle_category_rules_version": 1,
                "_oracle_reviewed_outcome": "oracle_pass"}
            with patches[0], patches[1], mock.patch(
                "bigMoveBench.normalized_execution._score_completed_case",
                return_value=("oracle_pass", [], {"from": "strict", "to": "strict"}, evidence)):
                _, summary = execution._runner(cases, run_dir).run()
            report = summary["category_reports"]["type2c"]
            self.assertEqual(report["denominators"], dict(selected=1, completed=1, srcdiff_eligible=1, complete_detections=1))
            self.assertEqual(report["reported_categories_among_complete_detections"], {"type2c": {"count": 1, "rate": 1.}})
            self.assertEqual(summary["category_membership"], "derived")
            with (run_dir / "cases.csv").open() as stream:
                row = next(csv.DictReader(stream))
            self.assertEqual(row["observed_content_relationship"], "type2c")
            self.assertEqual(row["benchmark_category"], "type2c")
            self.assertEqual(row["syntactic_type"], "2")
            self.assertEqual(row["category_rules_version"], "1")

    def test_denominators_and_distribution(self):
        metrics = category_metrics(selected=10, completed=9, eligible=8, detected=4,
            agreed=1, reviewed_agreed=2, reported={"type2c": 1, "type3": 3})
        self.assertEqual(metrics["rates"]["complete_detection_over_selected"], .4)
        self.assertEqual(metrics["rates"]["complete_detection_over_eligible"], .5)
        self.assertEqual(metrics["rates"]["original_agreement_over_complete_detections"], .25)
        self.assertEqual(metrics["reported_categories_among_complete_detections"]["type3"], {"count": 3, "rate": .75})
        self.assertIsNone(category_metrics(selected=0, completed=0, eligible=0, detected=0,
            agreed=0, reviewed_agreed=0, reported={})["rates"]["complete_detection_over_selected"])

    def test_frozen_profiles_are_not_reinterpreted(self):
        for category in ("type2b", "type2c", "type3"):
            with self.assertRaisesRegex(ValueError, "legacy category membership"):
                _rows("small", category)
        self.assertEqual(len(_rows("small", "type2")[1]), 20)
