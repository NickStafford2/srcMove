from __future__ import annotations

import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from srcmove_history.benchmarks.scaling import (
    _trial_data_storage,
    build_schedule,
    build_summary,
    parse_args,
    parse_jobs,
    run_trial as run_scaling_trial,
)
from benchmarking.provenance import sha256_file
from srcmove_history.benchmarks.trial import (
    normalized_analysis_result,
    parse_args as parse_trial_args,
    run_trial as run_analysis_trial,
)


class SrcMoveHistoryScalingTests(unittest.TestCase):
    def test_trial_adapter_runs_the_production_analysis_service(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository, srcdiff, srcmove = self._fixture(root)
            analysis = root / "analysis"
            args = parse_trial_args(
                [
                    "--analysis-root", str(analysis),
                    "--output", str(root / "result.json"),
                    "--repository", str(repository),
                    "--name", "fixture",
                    "--start", "HEAD",
                    "--count", "1",
                    "--jobs", "1",
                    "--srcdiff", str(srcdiff),
                    "--srcmove", str(srcmove),
                    "--srcdiff-timeout", "5",
                    "--srcmove-timeout", "5",
                    "--src-encoding", "UTF-8",
                ]
            )

            result = run_analysis_trial(args)

            self.assertEqual(result["summary"]["completed_pair_count"], 1)
            self.assertEqual(result["summary"]["completed"], 1)
            self.assertEqual(len(result["pairs"]), 1)
            self.assertEqual(len(result["normalized_results_sha256"]), 64)

    def test_scaling_trial_invokes_the_production_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository, srcdiff, srcmove = self._fixture(root)
            study_dir = root / "study"
            (study_dir / "trials").mkdir(parents=True)
            adapter = (
                REPO_ROOT / "srcmove_history/benchmarks/trial.py"
            )

            result = run_scaling_trial(
                study_dir=study_dir,
                schedule_entry={
                    "sequence": 1,
                    "phase": "measured",
                    "repetition": 1,
                    "position": 1,
                    "jobs": 1,
                },
                case_name="fixture",
                repository=repository,
                start_commit="HEAD",
                pair_count=1,
                selected_dir=None,
                srcdiff=srcdiff,
                srcmove=srcmove,
                srcdiff_timeout=5,
                srcmove_timeout=5,
                source_encoding="UTF-8",
                position=False,
                expected_files={
                    "srcdiff": (srcdiff, sha256_file(srcdiff)),
                    "srcmove": (srcmove, sha256_file(srcmove)),
                    "adapter": (adapter, sha256_file(adapter)),
                },
            )

            self.assertEqual(result["status"], "success")
            self.assertEqual(result["selected_pairs"], 1)
            self.assertEqual(result["analyzed_pairs"], 1)
            self.assertTrue(
                (study_dir / result["analysis_result"]).is_file()
            )

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

    def test_cli_uses_production_compact_retention(self) -> None:
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
        self.assertFalse(hasattr(args, "retention"))
        self.assertIsNone(args.scratch_root)
        self.assertEqual(args.results_root.name, "benchmark-results")

    def test_scratch_trial_data_is_promoted_and_removed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            scratch_root = root / "scratch"
            scratch_root.mkdir()
            durable_root = root / "study" / "trial" / "data"
            observation = {}

            with _trial_data_storage(
                durable_root, scratch_root, observation
            ) as execution_root:
                self.assertTrue(
                    execution_root.is_relative_to(scratch_root.resolve())
                )
                artifact = execution_root / "analysis-result.json"
                artifact.parent.mkdir(parents=True)
                artifact.write_text("{}", encoding="utf-8")

            self.assertEqual(
                (durable_root / "analysis-result.json").read_text(encoding="utf-8"),
                "{}",
            )
            self.assertEqual(list(scratch_root.iterdir()), [])
            self.assertTrue(observation["scratch_enabled"])
            self.assertEqual(
                observation["scratch_root"], str(scratch_root.resolve())
            )
            self.assertGreaterEqual(observation["scratch_promotion_seconds"], 0.0)

            args = parse_args(
                [
                    "sqlite",
                    "--start",
                    "HEAD",
                    "--count",
                    "1",
                    "--jobs",
                    "4",
                    "--scratch-root",
                    str(scratch_root),
                ]
            )
            self.assertEqual(args.scratch_root, scratch_root)

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
                        "definition_fingerprint_sha256": "b" * 64,
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
        self.assertTrue(summary["definition_equivalent"])

    def test_normalization_ignores_invocations_paths_and_timings(self) -> None:
        summary = {
            "completed_pair_count": 1,
            "completed": 1,
            "no_analyzable_change": 0,
            "failed": 0,
            "analysis": {"root": "/first/path"},
        }
        detail = {
            "distance_from_newest": 0,
            "old_commit": "a" * 40,
            "new_commit": "b" * 40,
            "pair_fingerprint": "c" * 64,
            "status": "completed",
            "invocation_id": "d" * 32,
            "changed_path_count": 2,
            "analyzable_path_count": 2,
            "metrics": {"move_count": 1},
            "timings": {"pair_seconds": 10.0},
            "results_observation": {"size_bytes": 10, "sha256": "e" * 64},
            "moves": [{"match_kind": "exact"}],
        }

        first = normalized_analysis_result(summary, [detail])
        summary["analysis"]["root"] = "/second/path"
        detail["invocation_id"] = "f" * 32
        detail["timings"]["pair_seconds"] = 99.0
        second = normalized_analysis_result(summary, [detail])

        self.assertEqual(
            first["normalized_results_sha256"],
            second["normalized_results_sha256"],
        )
        self.assertEqual(first["pairs"][0]["metrics"]["move_count"], 1)

    @staticmethod
    def _git(repository: Path, *arguments: str) -> None:
        subprocess.run(
            ["git", *arguments],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        )

    @classmethod
    def _fixture(cls, root: Path) -> tuple[Path, Path, Path]:
        repository = root / "repository"
        repository.mkdir()
        cls._git(repository, "init", "--initial-branch=main")
        cls._git(repository, "config", "user.name", "Scaling Test")
        cls._git(repository, "config", "user.email", "scaling@example.invalid")
        source = repository / "fixture.c"
        source.write_text("int first;\n", encoding="utf-8")
        cls._git(repository, "add", "fixture.c")
        cls._git(repository, "commit", "-m", "first")
        source.write_text("int second;\n", encoding="utf-8")
        cls._git(repository, "commit", "-am", "second")

        fake_tool = REPO_ROOT / "tests/fixtures/benchmark/fake_tool.py"
        srcdiff = root / "valid-archive-srcdiff"
        srcmove = root / "valid-archive-srcmove"
        wrapper = (
            "#!/bin/sh\nexec "
            f"{shlex.quote(sys.executable)} {shlex.quote(str(fake_tool))} "
            'valid-archive "$@"\n'
        )
        for executable in (srcdiff, srcmove):
            executable.write_text(wrapper, encoding="utf-8")
            executable.chmod(0o755)
        return repository, srcdiff, srcmove


if __name__ == "__main__":
    unittest.main()
