from __future__ import annotations

import csv
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
INPUT_XML = REPO_ROOT / "tests" / "fixtures" / "benchmark" / "input.srcdiff.xml"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarking.contracts import RunMode
from performance.benchmark import (
    build_schedule,
    inspect_workload,
    load_workloads,
    parse_profile_output,
    run_measurement,
    run_performance,
)
from performance.profile_study import _load_records
from benchmarking.provenance import sha256_file


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
    def test_profile_parser_preserves_timer_and_counter_units(self) -> None:
        self.assertEqual(
            parse_profile_output(
                "profile.pipeline.total_ms=12.375\n"
                "profile.parse.reader_events=10932\n"
                "profile.annotation.tagged_nodes=0\n"
                "profile.invalid_fractional_counter=1.5\n"
            ),
            {
                "pipeline.total_ms": 12.375,
                "parse.reader_events": 10932,
                "annotation.tagged_nodes": 0,
            },
        )

    def test_schedule_is_reproducible_paired_and_position_balanced(self) -> None:
        arguments = {
            "workload_names": ["large-b", "large-a"],
            "variant_names": ["baseline", "candidate"],
            "warmups": 1,
            "repetitions": 4,
            "seed": 19,
        }
        first = build_schedule(**arguments)
        second = build_schedule(**arguments)
        self.assertEqual(first, second)

        measured = [entry for entry in first if entry["phase"] == "measured"]
        for workload_name in arguments["workload_names"]:
            workload_entries = [
                entry
                for entry in measured
                if entry["workload"] == workload_name
            ]
            for variant in arguments["variant_names"]:
                positions = [
                    entry["position_in_pair"]
                    for entry in workload_entries
                    if entry["variant"] == variant
                ]
                self.assertEqual(positions.count(1), 2)
                self.assertEqual(positions.count(2), 2)
        with self.assertRaisesRegex(ValueError, "variant count"):
            build_schedule(
                workload_names=["tiny"],
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
                workloads={"tiny": INPUT_XML},
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
            workload = manifest["workloads"]["tiny"]
            self.assertEqual(workload["path"], str(INPUT_XML.resolve()))
            self.assertEqual(workload["sha256"], sha256_file(INPUT_XML))
            self.assertEqual(workload["size_bytes"], INPUT_XML.stat().st_size)
            self.assertEqual(workload["xml_shape"], "single_file")
            self.assertGreater(workload["metrics"]["xml_element_count"], 0)
            self.assertEqual(
                workload["metrics"]["diff_region_count"],
                workload["metrics"]["diff_delete_region_count"]
                + workload["metrics"]["diff_insert_region_count"],
            )
            self.assertEqual(
                manifest["observation"]["workloads"]["tiny"]["sha256"],
                workload["sha256"],
            )
            self.assertNotIn("inputs", manifest["observation"])
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
                {row["workload_sha256"] for row in rows},
                {sha256_file(INPUT_XML)},
            )
            self.assertTrue(all(float(row["wall_seconds"]) > 0 for row in rows))
            self.assertEqual(
                {row["output_retention"] for row in rows},
                {"discarded_after_validation"},
            )
            self.assertEqual(list((run_dir / "attempts").glob("*/srcmove.xml")), [])
            self.assertFalse((run_dir / INPUT_XML.name).exists())
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
                    workloads={"tiny": INPUT_XML},
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
            run_dir, manifest, summary = run_performance(
                output_root=root / "performance",
                variants={"baseline": baseline, "failing": failing},
                workloads={"tiny": INPUT_XML},
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

            successful_attempt = next(
                run_dir / row["attempt_path"]
                for row in rows
                if row["status"] == "success"
            )
            (successful_attempt / "results.json").write_text("{", encoding="utf-8")
            study_records = _load_records(run_dir, manifest)
            self.assertEqual(len(study_records), 4)
            self.assertTrue(
                all(
                    row["results_record_status"] == "missing"
                    for row in study_records
                    if row["status"] == "failed"
                )
            )
            self.assertEqual(
                next(
                    row["results_record_status"]
                    for row in study_records
                    if row["attempt_path"]
                    == str(successful_attempt.relative_to(run_dir))
                ),
                "malformed",
            )

    def test_workloads_are_explicit_resolved_and_unique(self) -> None:
        workloads = load_workloads([f"large={INPUT_XML}"])
        self.assertEqual(workloads, {"large": INPUT_XML.resolve()})
        with self.assertRaisesRegex(ValueError, "at least one workload"):
            load_workloads([])
        with self.assertRaisesRegex(ValueError, "duplicate workload"):
            load_workloads([f"same={INPUT_XML}", f"same={INPUT_XML}"])

    def test_workload_checksum_is_rechecked_before_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            workload_path = root / "large.srcdiff.xml"
            shutil.copyfile(INPUT_XML, workload_path)
            observation = inspect_workload(workload_path)
            workload_path.write_bytes(workload_path.read_bytes() + b"\n")
            executable = write_profile_tool(root / "srcMove", 10.0)
            run_dir = root / "run"
            (run_dir / "attempts").mkdir(parents=True)

            with self.assertRaisesRegex(ValueError, "workload changed"):
                run_measurement(
                    run_dir=run_dir,
                    schedule_entry={
                        "sequence": 1,
                        "phase": "measured",
                        "repetition": 1,
                        "workload": "large",
                        "variant": "current",
                        "position_in_pair": 1,
                    },
                    executable=executable,
                    executable_sha256=sha256_file(executable),
                    workload_path=workload_path,
                    workload_observation=observation,
                    timeout_seconds=2.0,
                )
            self.assertEqual(list((run_dir / "attempts").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
