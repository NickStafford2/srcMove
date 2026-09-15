from __future__ import annotations

import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from benchmarks.bigclonebench.suite import (
    _pair_set_operational_pass,
    _print_report,
    run_suite,
)
from tests.unit.test_bigclonebench_pipeline import write_executable
from tests.unit import test_bigclonebench_snapshot as snapshot_fixtures


class BigCloneBenchSuiteTests(unittest.TestCase):
    def test_evaluation_role_rejects_type_three_before_compile(self) -> None:
        for pair_set in (None, "type3"):
            args = SimpleNamespace(role="evaluation", pair_set=pair_set)
            with mock.patch(
                "benchmarks.bigclonebench.suite.ensure_compiled_dataset"
            ) as compile_dataset:
                with self.assertRaisesRegex(ValueError, "held-out partition"):
                    run_suite(args)
            compile_dataset.assert_not_called()

    def test_type_three_recall_is_observational_but_errors_fail(self) -> None:
        counts = {
            "selected": 2,
            "oracle_pass": 0,
            "upstream_failure": 0,
            "srcdiff_semantic_ineligible": 0,
            "srcmove_tool_failure": 0,
            "oracle_failure": 0,
        }
        self.assertTrue(_pair_set_operational_pass("type3", counts))
        self.assertFalse(_pair_set_operational_pass("type2", counts))
        counts["srcmove_tool_failure"] = 1
        self.assertFalse(_pair_set_operational_pass("type3", counts))

    def test_suite_threads_stage_ids_and_reuses_snapshots_and_corpora(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = snapshot_fixtures.BigCloneBenchSnapshotTests(
                methodName="test_materializes_type_one_directly_and_reuses_snapshot"
            )
            bce, compiled = fixture.compile_fixture(root)
            srcdiff = write_executable(
                root / "srcdiff",
                """#!/usr/bin/env python3
import sys
from pathlib import Path
output = Path(sys.argv[sys.argv.index('-o') + 1])
output.write_text("<unit xmlns='http://www.srcML.org/srcML/src' "
    "xmlns:diff='http://www.srcML.org/srcDiff/diff' "
    "xmlns:pos='http://www.srcML.org/srcML/position'>"
    "<unit language='Java' filename='input.java'>"
    "<diff:delete><name pos:start='1:1|1:1' pos:end='1000:1|1000:1'/></diff:delete>"
    "<diff:insert><name pos:start='1:1|1:1' pos:end='1000:1|1000:1'/></diff:insert>"
    "</unit>"
    "</unit>")
""",
            )
            srcmove = write_executable(
                root / "srcmove",
                """#!/usr/bin/env python3
import json
import shutil
import sys
from pathlib import Path
source, output = Path(sys.argv[1]), Path(sys.argv[2])
shutil.copy2(source, output)
Path(sys.argv[sys.argv.index('--results') + 1]).write_text(
    json.dumps({'move_count': 0, 'match_kinds': {}, 'moves': []}))
""",
            )
            args = SimpleNamespace(
                data_root=root / "data",
                bce_dir=bce,
                mode="census",
                role="tuning",
                seed=7,
                sample_size=10,
                verify_source=False,
                srcdiff=srcdiff,
                srcmove=srcmove,
                srcdiff_timeout=2.0,
                srcmove_timeout=2.0,
                pair_set=None,
            )

            progress_output = StringIO()
            with mock.patch(
                "benchmarks.bigclonebench.suite.ensure_compiled_dataset",
                return_value=(compiled, True),
            ), redirect_stdout(StringIO()), redirect_stderr(progress_output):
                first_dir, first, first_passed = run_suite(args)

            from benchmarks import corpus as corpus_module

            real_sha256_file = corpus_module.sha256_file

            def reject_cached_payload_hash(path: Path) -> str:
                if path.suffix in {".java", ".xml"}:
                    raise AssertionError(f"cached payload was rehashed: {path}")
                return real_sha256_file(path)

            with mock.patch(
                "benchmarks.bigclonebench.suite.ensure_compiled_dataset",
                return_value=(compiled, True),
            ), mock.patch(
                "benchmarks.bigclonebench.adapter.load_compiled_dataset",
                side_effect=AssertionError("compiled catalog reopened on snapshot reuse"),
            ), mock.patch(
                "benchmarks.bigclonebench.selection.sha256_file",
                side_effect=AssertionError("selection artifact was rehashed"),
            ), mock.patch(
                "benchmarks.corpus._input_identity",
                side_effect=AssertionError("snapshot inputs were traversed"),
            ), mock.patch(
                "benchmarks.corpus.sha256_file",
                side_effect=reject_cached_payload_hash,
            ), redirect_stdout(StringIO()):
                second_dir, second, second_passed = run_suite(args)

            self.assertFalse(first_passed)
            self.assertFalse(second_passed)
            self.assertTrue((first_dir / "summary.json").is_file())
            self.assertTrue((second_dir / "summary.json").is_file())
            self.assertEqual(len(first["pair_sets"]), 4)
            self.assertEqual(
                {item["pair_set"] for item in first["pair_sets"]},
                {"type1", "type2", "type3", "known-false-positive"},
            )
            self.assertTrue(
                all(item["snapshot_disposition"] == "reused" for item in second["pair_sets"])
            )
            self.assertTrue(
                all(item["corpus_disposition"] == "reused" for item in second["pair_sets"])
            )
            self.assertEqual(
                len({item["run_id"] for item in first["pair_sets"]}), 4
            )
            negative = next(
                item
                for item in first["pair_sets"]
                if item["pair_set"] == "known-false-positive"
            )
            self.assertEqual(negative["metrics"]["rejected"], 1)
            type3 = next(item for item in first["pair_sets"] if item["pair_set"] == "type3")
            self.assertEqual(type3["assessment"]["mode"], "observational")
            self.assertTrue(type3["assessment"]["operational_pass"])
            progress_report = progress_output.getvalue()
            self.assertIn("[srcMove execution] failed: 1/1 100%", progress_report)
            self.assertIn("passed 0/1 selected; missed 1", progress_report)
            self.assertIn("passed 1/1 selected; false acceptances 0", progress_report)
            output = StringIO()
            with redirect_stdout(output):
                _print_report(first_dir, first)
            report = output.getvalue()
            self.assertIn(
                "BigCloneBench suite: FAIL "
                "(2/4 pair sets operationally complete)",
                report,
            )
            self.assertIn("Type 1                 FAIL  passed 0/1 (0.0%)", report)
            self.assertIn("Type 2                 FAIL  passed 0/1 (0.0%)", report)
            self.assertIn(
                "Type 3                 OBS   observational census; 1 selected",
                report,
            )
            self.assertIn(
                "Known false positives  PASS  passed 1/1 (100.0%)", report
            )
            self.assertIn("whole-fragment detections 0/1", report)
            self.assertIn("expected class exact", report)
            self.assertIn("expected class type2", report)
            self.assertIn("expected class type3", report)
            self.assertIn("observational results (misses do not fail suite)", report)
            self.assertIn("wrong class 0", report)
            self.assertIn("misses 1", report)
            self.assertIn("rejected 1/1 whole pairs", report)
            self.assertIn("false acceptances 0", report)
            self.assertIn("Type 1", report)
            self.assertIn("Type 2", report)
            self.assertIn("Known false positives", report)
            self.assertIn("selected cases 4", report)

            type3["assessment"]["sample_interpretation"] = (
                "balanced_strength_sample"
            )
            type3["type3_strength_strata"] = {
                name: {
                    "selected": 1,
                    "strictly_classified": strict,
                    "detected": detected,
                }
                for name, strict, detected in (
                    ("very_strong", 1, 1),
                    ("strong", 0, 1),
                    ("moderate", 0, 0),
                    ("weak", 1, 1),
                )
            }
            balanced_output = StringIO()
            with redirect_stdout(balanced_output):
                _print_report(first_dir, first)
            balanced_report = balanced_output.getvalue()
            self.assertIn("balanced strength sample; 1 selected", balanced_report)
            self.assertIn("very strong  strict 1/1 (100.0%); detected 1/1", balanced_report)
            self.assertIn("strong       strict 0/1 (0.0%); detected 1/1", balanced_report)
            self.assertIn("moderate     strict 0/1 (0.0%); detected 0/1", balanced_report)
            self.assertIn("weak         strict 1/1 (100.0%); detected 1/1", balanced_report)
            self.assertNotIn("Type 3                 OBS   oracle", balanced_report)

            args.pair_set = "type3"
            with mock.patch(
                "benchmarks.bigclonebench.suite.ensure_compiled_dataset",
                return_value=(compiled, True),
            ), redirect_stdout(StringIO()):
                _, focused, focused_passed = run_suite(args)
            self.assertTrue(focused_passed)
            self.assertEqual(
                [item["pair_set"] for item in focused["pair_sets"]], ["type3"]
            )
            focused_output = StringIO()
            with redirect_stdout(focused_output):
                _print_report(first_dir, focused)
            self.assertIn("BigCloneBench suite: COMPLETE", focused_output.getvalue())


if __name__ == "__main__":
    unittest.main()
