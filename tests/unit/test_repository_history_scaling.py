from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.repositories.benchmark_history_scaling import (
    build_schedule,
    build_summary,
    normalize_history_results,
    parse_args,
    parse_jobs,
)


class RepositoryHistoryScalingTests(unittest.TestCase):
    def test_jobs_and_schedule_are_validated_and_reproducible(self) -> None:
        self.assertEqual(parse_jobs("1,2,4,8"), [1, 2, 4, 8])
        with self.assertRaisesRegex(Exception, "unique"):
            parse_jobs("1,2,2")
        with self.assertRaisesRegex(Exception, "positive"):
            parse_jobs("1,0")

        first = build_schedule([1, 2, 4], repetitions=3, warmups=1, seed=17)
        second = build_schedule([1, 2, 4], repetitions=3, warmups=1, seed=17)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 12)
        measured = [entry for entry in first if entry["phase"] == "measured"]
        for repetition in range(1, 4):
            selected = [
                entry["jobs"]
                for entry in measured
                if entry["repetition"] == repetition
            ]
            self.assertEqual(set(selected), {1, 2, 4})

    def test_cli_defaults_to_result_retention(self) -> None:
        args = parse_args(
            [
                "sqlite",
                "--start",
                "HEAD",
                "--count",
                "300",
                "--jobs",
                "1,2,4,8",
            ]
        )
        self.assertEqual(args.jobs, [1, 2, 4, 8])
        self.assertEqual(args.repetitions, 3)
        self.assertEqual(args.retention, "results")

    def test_summary_reports_speedup_efficiency_and_conservative_knee(self) -> None:
        rows = []
        walls = {
            1: [99.0, 100.0, 101.0],
            2: [59.0, 60.0, 61.0],
            4: [54.0, 55.0, 56.0],
            8: [51.0, 52.0, 53.0],
        }
        sequence = 0
        for jobs, samples in walls.items():
            for repetition, wall in enumerate(samples, start=1):
                sequence += 1
                rows.append(
                    {
                        "sequence": sequence,
                        "phase": "measured",
                        "repetition": repetition,
                        "jobs": jobs,
                        "status": "success",
                        "wall_seconds": wall,
                        "throughput_pairs_per_second": 300 / wall,
                        "analyzed_pairs_per_second": 200 / wall,
                        "cpu_utilization": jobs * 0.7,
                        "peak_rss_bytes": jobs * 1000,
                        "disk_bytes": 5000,
                        "normalized_results_sha256": "a" * 64,
                        "configuration_fingerprint_sha256": "b" * 64,
                    }
                )

        summary = build_summary(
            rows, [1, 2, 4, 8], marginal_threshold=0.10
        )

        self.assertEqual(summary["jobs"]["1"]["wall_seconds"]["median"], 100.0)
        self.assertEqual(summary["jobs"]["2"]["speedup"], 100 / 60)
        self.assertEqual(summary["jobs"]["2"]["parallel_efficiency"], 100 / 120)
        self.assertEqual(summary["diminishing_returns_after_jobs"], 2)
        self.assertTrue(summary["normalized_results_equivalent"])
        self.assertTrue(summary["configuration_equivalent"])

    def test_normalization_ignores_history_ids_paths_and_timings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            data_root = Path(temporary_directory) / "data"
            history_dir = data_root / "repository-histories" / "history-fixture"
            pairs_dir = history_dir / "pairs"
            results_path = history_dir / "results" / "000001.json"
            pairs_dir.mkdir(parents=True)
            results_path.parent.mkdir()
            results_path.write_text(
                json.dumps({"move_count": 1, "moves": [{"move_id": "stable"}]}),
                encoding="utf-8",
            )
            manifest = {
                "schema_version": 4,
                "history_id": "history-fixture",
                "pair_receipts": {"directory": "pairs", "count": 1},
            }
            pair = {
                "schema_version": 1,
                "sequence": 0,
                "old_commit": "a" * 40,
                "new_commit": "b" * 40,
                "status": "completed",
                "metrics": {"move_count": 1},
                "timings": {"pair_seconds": 10.0},
                "artifacts": {
                    "results_path": results_path.relative_to(data_root).as_posix()
                },
            }
            (history_dir / "history.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            (pairs_dir / "000001.json").write_text(
                json.dumps(pair), encoding="utf-8"
            )

            first_hash, normalized = normalize_history_results(
                history_dir, data_root
            )
            pair["timings"]["pair_seconds"] = 99.0
            pair["artifacts"]["ignored"] = "different/path"
            (pairs_dir / "000001.json").write_text(
                json.dumps(pair), encoding="utf-8"
            )
            second_hash, _ = normalize_history_results(history_dir, data_root)

            self.assertEqual(first_hash, second_hash)
            self.assertEqual(normalized[0]["results"]["move_count"], 1)


if __name__ == "__main__":
    unittest.main()
