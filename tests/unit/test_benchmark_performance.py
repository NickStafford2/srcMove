from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
INPUT_XML = REPO_ROOT / "tests" / "fixtures" / "benchmark" / "input.srcdiff.xml"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.contracts import RunMode
from benchmarks.performance import build_schedule, run_performance
from benchmarks.provenance import sha256_file


def write_profile_tool(path: Path, milliseconds: float, fail: bool = False) -> Path:
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import json, shutil, sys\n"
        "from pathlib import Path\n"
        + ("raise SystemExit(23)\n" if fail else "")
        + "source, output = Path(sys.argv[1]), Path(sys.argv[2])\n"
        "shutil.copyfile(source, output)\n"
        "results = Path(sys.argv[sys.argv.index('--results') + 1])\n"
        "results.write_text(json.dumps({'move_count': 0}))\n"
        f"print('profile.total_ms={milliseconds}')\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


class PerformanceBenchmarkTests(unittest.TestCase):
    def test_schedule_is_reproducible_paired_and_position_balanced(self) -> None:
        arguments = {
            "case_ids": ["case-b", "case-a"],
            "variant_names": ["baseline", "candidate"],
            "warmups": 1,
            "repetitions": 4,
            "seed": 19,
        }
        first = build_schedule(**arguments)
        second = build_schedule(**arguments)
        self.assertEqual(first, second)

        measured = [entry for entry in first if entry["phase"] == "measured"]
        for case_id in arguments["case_ids"]:
            case_entries = [entry for entry in measured if entry["case_id"] == case_id]
            for variant in arguments["variant_names"]:
                positions = [
                    entry["position_in_pair"]
                    for entry in case_entries
                    if entry["variant"] == variant
                ]
                self.assertEqual(positions.count(1), 2)
                self.assertEqual(positions.count(2), 2)
        with self.assertRaisesRegex(ValueError, "variant count"):
            build_schedule(
                case_ids=["tiny"],
                variant_names=["one", "two", "three"],
                warmups=0,
                repetitions=2,
                seed=0,
            )

    def test_run_records_raw_measurements_summary_and_paired_deltas(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            baseline = write_profile_tool(root / "baseline", 10.0)
            candidate = write_profile_tool(root / "candidate", 15.0)
            run_dir, manifest, summary = run_performance(
                output_root=root / "performance",
                variants={"baseline": baseline, "candidate": candidate},
                inputs={"tiny": INPUT_XML},
                input_source={"kind": "fixture"},
                warmups=1,
                repetitions=2,
                seed=7,
                timeout_seconds=2.0,
                cache_policy="fixture_cache_policy",
                mode=RunMode.DEVELOPMENT,
                run_id="fixture-comparison",
            )

            self.assertEqual(manifest["status"], "completed")
            self.assertEqual(
                manifest["policy"]["ordering"],
                "paired_interleaved_position_balanced",
            )
            self.assertEqual(
                manifest["policy"]["cache_policy"], "fixture_cache_policy"
            )
            self.assertEqual(summary["counts"]["warmup_attempts"], 2)
            self.assertEqual(summary["counts"]["measured_attempts"], 4)
            self.assertEqual(summary["counts"]["measured_failed"], 0)
            self.assertEqual(
                summary["variants"]["baseline"]["metrics"]["internal_total_ms"][
                    "median"
                ],
                10.0,
            )
            comparison = summary["comparisons"]["candidate"]["metrics"][
                "internal_total_ms"
            ]
            self.assertEqual(comparison["paired"], 2)
            self.assertEqual(comparison["candidate_minus_baseline"]["median"], 5.0)
            self.assertEqual(comparison["candidate_over_baseline"]["median"], 1.5)

            with (run_dir / "raw.csv").open(encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 6)
            self.assertEqual(
                {row["input_sha256"] for row in rows}, {sha256_file(INPUT_XML)}
            )
            self.assertTrue(all(float(row["wall_seconds"]) > 0 for row in rows))
            self.assertEqual(
                {row["output_retention"] for row in rows},
                {"discarded_after_validation"},
            )
            self.assertEqual(list((run_dir / "attempts").glob("*/srcmove.xml")), [])
            self.assertEqual(
                manifest["artifacts"]["raw_csv"]["sha256"],
                sha256_file(run_dir / "raw.csv"),
            )
            self.assertEqual(
                manifest["artifacts"]["summary"]["sha256"],
                sha256_file(run_dir / "summary.json"),
            )
            with self.assertRaises(FileExistsError):
                run_performance(
                    output_root=root / "performance",
                    variants={"baseline": baseline, "candidate": candidate},
                    inputs={"tiny": INPUT_XML},
                    input_source={"kind": "fixture"},
                    warmups=0,
                    repetitions=2,
                    seed=7,
                    timeout_seconds=2.0,
                    cache_policy="fixture_cache_policy",
                    mode=RunMode.DEVELOPMENT,
                    run_id="fixture-comparison",
                )

    def test_failed_measurements_remain_in_raw_data_and_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            baseline = write_profile_tool(root / "baseline", 10.0)
            failing = write_profile_tool(root / "failing", 0.0, fail=True)
            run_dir, _, summary = run_performance(
                output_root=root / "performance",
                variants={"baseline": baseline, "failing": failing},
                inputs={"tiny": INPUT_XML},
                input_source={"kind": "fixture"},
                warmups=0,
                repetitions=2,
                seed=3,
                timeout_seconds=2.0,
                cache_policy="fixture_cache_policy",
                mode=RunMode.DEVELOPMENT,
                run_id="fixture-failure",
            )

            self.assertEqual(summary["counts"]["measured_attempts"], 4)
            self.assertEqual(summary["counts"]["measured_successful"], 2)
            self.assertEqual(summary["counts"]["measured_failed"], 2)
            self.assertEqual(summary["variants"]["failing"]["failed"], 2)
            with (run_dir / "raw.csv").open(encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))
            failed = [row for row in rows if row["variant"] == "failing"]
            self.assertEqual(len(failed), 2)
            self.assertTrue(all(row["status"] == "failed" for row in failed))
            self.assertTrue(all(row["exit_code"] == "23" for row in failed))


if __name__ == "__main__":
    unittest.main()
