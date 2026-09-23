from __future__ import annotations

import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from bigMoveBench.suite import (
    _pair_set_operational_pass,
    _print_report,
    parse_args,
    run_suite,
)
from bigMoveBench.tests import test_benchmark_cases as benchmark_case_fixtures


def write_executable(path: Path, source: str) -> Path:
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)
    return path


class BigCloneBenchSuiteTests(unittest.TestCase):
    def test_suite_cli_exposes_profiles_without_ignored_sampling_options(self) -> None:
        with mock.patch("sys.argv", ["suite.py"]):
            args = parse_args()
        self.assertEqual(args.profile, "small")
        self.assertFalse(args.cache)
        self.assertFalse(args.refresh_cache)
        self.assertIsNone(args.profile_runner)
        self.assertFalse(hasattr(args, "mode"))
        self.assertFalse(hasattr(args, "seed"))
        self.assertFalse(hasattr(args, "sample_size"))

        for option, value in (
            ("--mode", "census"),
            ("--seed", "7"),
            ("--sample-size", "10"),
        ):
            with self.subTest(option=option), mock.patch(
                "sys.argv", ["suite.py", option, value]
            ), redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                parse_args()

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

    def test_suite_uses_normalized_cases_and_preserves_combined_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bce, compiled = benchmark_case_fixtures.compile_fixture(root)
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
                cache_root=root / "data",
                results_root=root / "results",
                bce_dir=bce,
                verify_source=False,
                srcdiff=srcdiff,
                srcmove=srcmove,
                srcdiff_timeout=2.0,
                srcmove_timeout=2.0,
                pair_set=None,
            )

            progress_output = StringIO()
            with mock.patch(
                "bigMoveBench.suite.ensure_compiled_dataset",
                return_value=(compiled, True),
            ), redirect_stdout(StringIO()), redirect_stderr(progress_output):
                first_dir, first, first_passed = run_suite(args)

            with mock.patch(
                "bigMoveBench.suite.ensure_compiled_dataset",
                return_value=(compiled, True),
            ), redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                second_dir, second, second_passed = run_suite(args)

            self.assertFalse(first_passed)
            self.assertFalse(second_passed)
            self.assertTrue(first_dir.is_relative_to(args.results_root.resolve()))
            self.assertTrue(second_dir.is_relative_to(args.results_root.resolve()))
            self.assertTrue(
                all(
                    Path(item["run_directory"]).is_relative_to(
                        args.results_root.resolve()
                    )
                    for item in first["pair_sets"]
                )
            )
            self.assertTrue((args.cache_root / "benchmark-cases").is_dir())
            self.assertTrue((first_dir / "summary.json").is_file())
            self.assertTrue((second_dir / "summary.json").is_file())
            self.assertEqual(len(first["pair_sets"]), 4)
            self.assertEqual(
                {item["pair_set"] for item in first["pair_sets"]},
                {"type1", "type2", "type3", "known-false-positive"},
            )
            self.assertEqual(first["request"]["mode"], "census")
            self.assertNotIn("seed", first["request"])
            self.assertNotIn("sample_size", first["request"])
            self.assertTrue(
                all(
                    item["benchmark_cases_disposition"] == "reused"
                    for item in second["pair_sets"]
                )
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
            self.assertIn(
                "[normalized execution] complete: 1/1 100%",
                progress_report,
            )
            self.assertIn("srcmove_miss", progress_report)
            self.assertIn("oracle_pass", progress_report)
            output = StringIO()
            with redirect_stdout(output):
                _print_report(first_dir, first)
            report = output.getvalue()
            self.assertIn(
                "BigMoveBench suite: FAIL "
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
            self.assertNotIn("unsuitable for thesis", report)

            first["request"]["development_srcdiff_cache"] = {
                "enabled": True,
                "refresh": False,
                "policy": "unversioned_development_only",
                "suitable_for_thesis": False,
            }
            for item in first["pair_sets"]:
                item["development_srcdiff_cache"] = {"hits": 1, "misses": 0}
            cached_output = StringIO()
            with redirect_stdout(cached_output):
                _print_report(first_dir, first)
            self.assertIn(
                "WARNING: unversioned development srcDiff cache used; "
                "unsuitable for thesis results",
                cached_output.getvalue(),
            )
            self.assertIn("srcDiff cache: 4 hits, 0 misses", cached_output.getvalue())
            first["request"]["development_srcdiff_cache"]["enabled"] = False

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
                "bigMoveBench.suite.ensure_compiled_dataset",
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
            self.assertIn("BigMoveBench suite: COMPLETE", focused_output.getvalue())


if __name__ == "__main__":
    unittest.main()
