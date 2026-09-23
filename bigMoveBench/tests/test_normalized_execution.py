from __future__ import annotations

import io
import json
import sqlite3
import tempfile
import time
import unittest
import uuid
from contextlib import closing
from pathlib import Path
from unittest import mock

from bigMoveBench.benchmark_cases import SerialBenchmarkCaseRunner
from bigMoveBench.contracts import SemanticResult, SemanticStatus
from bigMoveBench.normalized_execution import SerialBenchmarkExecutionRunner
from bigMoveBench.runner_profile import RunnerProfiler
from bigMoveBench.srcdiff_cache import DevelopmentSrcdiffCache
from bigMoveBench.tests import test_benchmark_cases


TOOL_OBSERVATION = {
    "status": "observed",
    "artifact": {"sha256": "a" * 64, "size_bytes": 1},
}


class FakeToolAttempts:
    def __init__(self, interrupt_stage: str | None = None) -> None:
        self.calls: list[str] = []
        self.interrupt_stage = interrupt_stage

    def __call__(self, **kwargs):
        stage = kwargs["stage"]
        self.calls.append(stage)
        if stage == self.interrupt_stage:
            raise RuntimeError(f"forced {stage} interruption")
        profile_callback = kwargs.get("profile_callback")
        if profile_callback is not None:
            profile_callback(
                "attempt_setup", 0.001, {"attempt_directories": 1}
            )
            profile_callback("process_supervision", 0.002, {})
            profile_callback(
                "attempt_started_write",
                0.003,
                {"json_writes": 1, "json_bytes": 100},
            )
            profile_callback(
                "attempt_capture_write",
                0.004,
                {"log_writes": 0, "log_bytes": 0},
            )
            profile_callback(
                "xml_validation", 0.005, {"validation_bytes": 128}
            )
            profile_callback(
                "attempt_terminal_write",
                0.006,
                {"json_writes": 1, "json_bytes": 200},
            )
        attempt_id = f"attempt-{stage}-{uuid.uuid4()}"
        attempt_dir = kwargs["attempts_root"] / attempt_id
        attempt_dir.mkdir(parents=True)
        output = attempt_dir / kwargs["output_filename"]
        output.write_text(
            (
                "<unit xmlns='http://www.srcML.org/srcML/src' "
                "xmlns:diff='http://www.srcML.org/srcDiff/diff'>"
                "<unit language='Java' filename='input.java'/></unit>"
                if stage == "srcdiff"
                else "<unit/>"
            ),
            encoding="utf-8",
        )
        if stage == "srcmove":
            (attempt_dir / "results.json").write_text(
                json.dumps({"move_count": 1, "moves": []}), encoding="utf-8"
            )
        return attempt_dir, {
            "attempt_id": attempt_id,
            "admitted": True,
            "process_elapsed_seconds": 0.01,
            "xml": {"status": "valid", "sha256": "b" * 64},
        }


class FailedToolAttempts(FakeToolAttempts):
    def __init__(self, failed_stage: str) -> None:
        super().__init__()
        self.failed_stage = failed_stage

    def __call__(self, **kwargs):
        attempt_dir, record = super().__call__(**kwargs)
        if kwargs["stage"] == self.failed_stage:
            record["admitted"] = False
            record["termination"] = {"status": "timed_out"}
        return attempt_dir, record


class NormalizedExecutionTests(unittest.TestCase):
    def _runner(
        self, benchmark_cases, run_dir: Path, **kwargs
    ) -> SerialBenchmarkExecutionRunner:
        kwargs.setdefault("progress_enabled", False)
        return SerialBenchmarkExecutionRunner(
            benchmark_cases,
            run_dir=run_dir,
            srcdiff=Path("/fake/srcdiff"),
            srcmove=Path("/fake/srcMove"),
            srcdiff_observation=TOOL_OBSERVATION,
            srcmove_observation=TOOL_OBSERVATION,
            **kwargs,
        )

    def test_reports_execution_progress(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = test_benchmark_cases.NormalizedBenchmarkCasesTests()
            _, _, benchmark_cases, _ = fixture.publish_two_case_fixture(root)
            tools = FakeToolAttempts()
            output = io.StringIO()
            patches = self._successful_patches(tools)
            with patches[0], patches[1], patches[2]:
                self._runner(
                    benchmark_cases,
                    root / "results" / "progress",
                    progress_enabled=True,
                    progress_stream=output,
                ).run()

            lines = output.getvalue().splitlines()
            self.assertEqual(
                lines[0],
                "[normalized execution] started: 0/2   0% 00:00 — type3",
            )
            self.assertIn(
                "[normalized execution] progress: 2/2 100%",
                lines[-2],
            )
            self.assertIn(
                "2 executed, 0 reused, 0 failed",
                lines[-1],
            )

    def _successful_patches(self, tool_attempts):
        return (
            mock.patch(
                "bigMoveBench.normalized_execution.execute_attempt",
                side_effect=tool_attempts,
            ),
            mock.patch(
                "bigMoveBench.normalized_execution.validate_srcdiff_semantics",
                return_value=SemanticResult(SemanticStatus.ELIGIBLE, {"reason": "ok"}),
            ),
            mock.patch(
                "bigMoveBench.normalized_execution._score_completed_case",
                return_value=(
                    "oracle_pass",
                    [],
                    {"from": "exact", "to": "exact"},
                    {"move_count": 1},
                ),
            ),
        )

    def test_streams_stages_to_terminal_transactions_and_reuses_them(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = test_benchmark_cases.NormalizedBenchmarkCasesTests()
            _, _, benchmark_cases, _ = fixture.publish_two_case_fixture(root)
            run_dir = root / "results" / "run-one"
            tools = FakeToolAttempts()
            patches = self._successful_patches(tools)
            with patches[0], patches[1], patches[2]:
                _, summary = self._runner(benchmark_cases, run_dir).run()

            self.assertEqual(tools.calls, ["srcdiff", "srcmove"] * 2)
            self.assertEqual(summary["status"], "completed")
            self.assertEqual(summary["counts"]["selected"], 2)
            self.assertEqual(summary["counts"]["oracle_pass"], 2)
            self.assertEqual(summary["counts"]["strict_passes"], 2)
            self.assertEqual(
                summary["rates"][
                    "conditional_srcmove_detection_and_classification"
                ],
                1.0,
            )
            self.assertEqual(
                sum(
                    group["selected"]
                    for group in summary["strata"]["type3_strength"].values()
                ),
                2,
            )
            self.assertIn("srcdiff_process_seconds", summary["timings"])
            self.assertIn("peak_rss_bytes", summary["resources"])
            self.assertNotIn("case_outcomes", summary)
            self.assertNotIn("runner_profile", summary)
            with closing(
                sqlite3.connect(run_dir / "execution.sqlite")
            ) as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT status, COUNT(*) FROM attempts GROUP BY status"
                    ).fetchall(),
                    [("terminal", 2)],
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM attempts "
                        "WHERE semantic_status='eligible' "
                        "AND srcmove_completed=1 AND outcome='oracle_pass'"
                    ).fetchone()[0],
                    2,
                )
                configuration = json.loads(
                    connection.execute(
                        "SELECT configuration_json FROM run_metadata"
                    ).fetchone()[0]
                )
                self.assertNotIn("runner_profile", configuration)
            csv_lines = (run_dir / "cases.csv").read_text(
                encoding="utf-8"
            ).splitlines()
            self.assertEqual(len(csv_lines), 3)
            self.assertIn("case_id,ordinal,outcome", csv_lines[0])
            self.assertEqual(
                summary["cases_csv"]["path"], "cases.csv"
            )

            reused_tools = FakeToolAttempts()
            patches = self._successful_patches(reused_tools)
            with patches[0], patches[1], patches[2]:
                _, resumed = self._runner(benchmark_cases, run_dir).run()
            self.assertEqual(reused_tools.calls, [])
            self.assertEqual(resumed["counts"], summary["counts"])

    def test_opt_in_runner_profile_preserves_case_order_and_outcomes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = test_benchmark_cases.NormalizedBenchmarkCasesTests()
            _, _, benchmark_cases, _ = fixture.publish_two_case_fixture(root)
            profile_path = root / "profiles" / "raw.jsonl"
            tools = FakeToolAttempts()
            patches = self._successful_patches(tools)
            with patches[0], patches[1], patches[2]:
                _, summary = self._runner(
                    benchmark_cases,
                    root / "results" / "profiled",
                    runner_profile_path=profile_path,
                ).run()

            records = [
                json.loads(line)
                for line in profile_path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(len(records), 2)
            self.assertEqual(
                [record["case_id"] for record in records],
                [row["case_id"] for row in self._case_rows(benchmark_cases)],
            )
            self.assertEqual(
                [record["outcome"] for record in records],
                ["oracle_pass", "oracle_pass"],
            )
            self.assertEqual(summary["counts"]["oracle_pass"], 2)
            for record in records:
                self.assertEqual(record["schema_version"], 2)
                self.assertEqual(record["run_id"], "profiled")
                self.assertTrue(record["attempt_id"].startswith("attempt-"))
                self.assertEqual(record["attempt_ordinal"], 0)
                self.assertIn("runner.case_total_ms", record["phases_ms"])
                self.assertIn("runner.semantic_validation_ms", record["phases_ms"])
                self.assertIn("runner.scoring_ms", record["phases_ms"])
                self.assertIn("runner.scratch_cleanup_ms", record["phases_ms"])
                self.assertEqual(record["counters"]["runner.hard_links"], 4)
                self.assertEqual(
                    record["counters"]["runner.scratch_links_removed"], 4
                )
                self.assertEqual(
                    record["counters"]["runner.sqlite_transactions"], 2
                )

            resumed_tools = FakeToolAttempts()
            resumed_profile_path = root / "profiles" / "resumed.jsonl"
            patches = self._successful_patches(resumed_tools)
            with patches[0], patches[1], patches[2]:
                self._runner(
                    benchmark_cases,
                    root / "results" / "profiled",
                    runner_profile_path=resumed_profile_path,
                ).run()
            self.assertEqual(resumed_tools.calls, [])
            self.assertEqual(
                len(profile_path.read_text(encoding="utf-8").splitlines()), 2
            )
            self.assertEqual(
                resumed_profile_path.read_text(encoding="utf-8"), ""
            )

    def test_disabled_profile_does_not_collect_case_timings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = test_benchmark_cases.NormalizedBenchmarkCasesTests()
            _, _, benchmark_cases, _ = fixture.publish_fixture(root)
            with SerialBenchmarkCaseRunner(benchmark_cases) as cases, mock.patch(
                "bigMoveBench.benchmark_cases.time.perf_counter_ns"
            ) as clock:
                self.assertEqual(cases.run(lambda case: None), 1)
            clock.assert_not_called()
            self.assertIsNone(cases.last_profile)

            tools = FakeToolAttempts()
            patches = self._successful_patches(tools)
            with (
                patches[0],
                patches[1],
                patches[2],
                mock.patch(
                    "bigMoveBench.normalized_execution.time.perf_counter"
                ) as runner_clock,
            ):
                self._runner(
                    benchmark_cases, root / "results" / "unprofiled"
                ).run()
            runner_clock.assert_not_called()

    def test_profile_path_cannot_overlap_execution_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = test_benchmark_cases.NormalizedBenchmarkCasesTests()
            _, _, benchmark_cases, _ = fixture.publish_fixture(root)
            run_dir = root / "results" / "unsafe-profile"
            with self.assertRaisesRegex(ValueError, "outside the execution"):
                self._runner(
                    benchmark_cases,
                    run_dir,
                    runner_profile_path=run_dir / "execution.sqlite",
                ).run()
            self.assertFalse((run_dir / "execution.sqlite").exists())

    def test_existing_profile_output_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "existing.jsonl"
            output.write_text('{"unrelated":true}\n', encoding="utf-8")
            with self.assertRaises(FileExistsError):
                RunnerProfiler(output)
            self.assertEqual(
                output.read_text(encoding="utf-8"), '{"unrelated":true}\n'
            )

    def test_profile_output_failure_disables_only_the_diagnostic(self) -> None:
        class FailingStream:
            def write(self, value):
                raise OSError("profile disk failure")

            def flush(self):
                return None

            def close(self):
                return None

        with tempfile.TemporaryDirectory() as temporary:
            profiler = RunnerProfiler(Path(temporary) / "raw.jsonl")
            assert profiler._stream is not None
            profiler._stream.close()
            profiler._stream = FailingStream()  # type: ignore[assignment]
            profiler.begin_case(
                case_id="case",
                ordinal=0,
                run_id="run",
                started_ns=time.perf_counter_ns(),
                phases_ms={},
                counters={},
            )
            profiler.identify_attempt("attempt", 0)
            errors = io.StringIO()
            with mock.patch("sys.stderr", errors):
                profiler.finish_case("oracle_pass")
            self.assertIn("runner profiling disabled", errors.getvalue())
            self.assertIsNone(profiler._stream)

            # A disabled profiler remains a no-op for later cases.
            profiler.begin_case(
                case_id="later",
                ordinal=1,
                run_id="run",
                started_ns=time.perf_counter_ns(),
                phases_ms={},
                counters={},
            )
            profiler.finish_case("oracle_pass")

    @staticmethod
    def _case_rows(benchmark_cases):
        with closing(
            sqlite3.connect(benchmark_cases.directory / "benchmark_cases.sqlite")
        ) as connection:
            connection.row_factory = sqlite3.Row
            return list(connection.execute("SELECT case_id FROM cases ORDER BY ordinal"))

    def test_development_cache_reuses_srcdiff_but_always_runs_srcmove(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = test_benchmark_cases.NormalizedBenchmarkCasesTests()
            _, _, benchmark_cases, _ = fixture.publish_two_case_fixture(root)
            cache = DevelopmentSrcdiffCache(root / "cache")

            first_tools = FakeToolAttempts()
            patches = self._successful_patches(first_tools)
            with patches[0], patches[1], patches[2]:
                _, first = self._runner(
                    benchmark_cases,
                    root / "results" / "cache-one",
                    srcdiff_cache=cache,
                ).run()
            self.assertEqual(first_tools.calls, ["srcdiff", "srcmove"] * 2)
            self.assertEqual(first["development_srcdiff_cache"]["hits"], 0)
            self.assertEqual(first["development_srcdiff_cache"]["misses"], 2)
            self.assertFalse(
                first["development_srcdiff_cache"]["suitable_for_thesis"]
            )

            second_tools = FakeToolAttempts()
            patches = self._successful_patches(second_tools)
            with patches[0], patches[1], patches[2]:
                _, second = self._runner(
                    benchmark_cases,
                    root / "results" / "cache-two",
                    srcdiff_cache=cache,
                ).run()
            self.assertEqual(second_tools.calls, ["srcmove"] * 2)
            self.assertEqual(second["development_srcdiff_cache"]["hits"], 2)
            self.assertEqual(second["development_srcdiff_cache"]["misses"], 0)

            refresh_tools = FakeToolAttempts()
            patches = self._successful_patches(refresh_tools)
            with patches[0], patches[1], patches[2]:
                _, refreshed = self._runner(
                    benchmark_cases,
                    root / "results" / "cache-refresh",
                    srcdiff_cache=cache,
                    refresh_srcdiff_cache=True,
                ).run()
            self.assertEqual(refresh_tools.calls, ["srcdiff", "srcmove"] * 2)
            self.assertEqual(refreshed["development_srcdiff_cache"]["hits"], 0)
            self.assertEqual(refreshed["development_srcdiff_cache"]["misses"], 2)

    def test_semantic_ineligible_is_terminal_without_srcmove(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = test_benchmark_cases.NormalizedBenchmarkCasesTests()
            _, _, benchmark_cases, _ = fixture.publish_fixture(root)
            tools = FakeToolAttempts()
            profile_path = root / "profiles" / "semantic.jsonl"
            with (
                mock.patch(
                    "bigMoveBench.normalized_execution.execute_attempt",
                    side_effect=tools,
                ),
                mock.patch(
                    "bigMoveBench.normalized_execution.validate_srcdiff_semantics",
                    return_value=SemanticResult(
                        SemanticStatus.INELIGIBLE,
                        {"reason": "payload_missing"},
                    ),
                ),
            ):
                _, summary = self._runner(
                    benchmark_cases,
                    root / "results" / "semantic",
                    runner_profile_path=profile_path,
                ).run()
            self.assertEqual(tools.calls, ["srcdiff"])
            self.assertEqual(summary["counts"]["srcdiff_semantic_ineligible"], 1)
            self.assertEqual(summary["counts"]["executed"], 0)
            record = json.loads(profile_path.read_text(encoding="utf-8"))
            self.assertEqual(record["outcome"], "srcdiff_semantic_ineligible")
            self.assertNotIn("runner.srcmove_process_ms", record["phases_ms"])
            self.assertNotIn("runner.scoring_ms", record["phases_ms"])

    def test_profile_records_tool_and_scoring_failures(self) -> None:
        scenarios = (
            ("srcdiff", "upstream_failure"),
            ("srcmove", "srcmove_tool_failure"),
            ("oracle", "oracle_failure"),
        )
        for failed_stage, expected_outcome in scenarios:
            with (
                self.subTest(stage=failed_stage),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = Path(temporary)
                fixture = test_benchmark_cases.NormalizedBenchmarkCasesTests()
                _, _, benchmark_cases, _ = fixture.publish_fixture(root)
                tools = (
                    FakeToolAttempts()
                    if failed_stage == "oracle"
                    else FailedToolAttempts(failed_stage)
                )
                oracle_result = (
                    (
                        "oracle_failure",
                        ["forced scoring failure"],
                        {"from": "not_checked", "to": "not_checked"},
                        {},
                    )
                    if failed_stage == "oracle"
                    else (
                        "oracle_pass",
                        [],
                        {"from": "exact", "to": "exact"},
                        {"move_count": 1},
                    )
                )
                with (
                    mock.patch(
                        "bigMoveBench.normalized_execution.execute_attempt",
                        side_effect=tools,
                    ),
                    mock.patch(
                        "bigMoveBench.normalized_execution.validate_srcdiff_semantics",
                        return_value=SemanticResult(SemanticStatus.ELIGIBLE, {}),
                    ),
                    mock.patch(
                        "bigMoveBench.normalized_execution._score_completed_case",
                        return_value=oracle_result,
                    ),
                ):
                    self._runner(
                        benchmark_cases,
                        root / "results" / failed_stage,
                        runner_profile_path=root / "profiles" / f"{failed_stage}.jsonl",
                    ).run()

                record = json.loads(
                    (root / "profiles" / f"{failed_stage}.jsonl").read_text(
                        encoding="utf-8"
                    )
                )
                self.assertEqual(record["outcome"], expected_outcome)

    def test_resume_seals_interruption_and_retries_each_pipeline_stage(self) -> None:
        for interrupted_stage in ("srcdiff", "srcmove", "oracle"):
            with (
                self.subTest(stage=interrupted_stage),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = Path(temporary)
                fixture = test_benchmark_cases.NormalizedBenchmarkCasesTests()
                _, _, benchmark_cases, _ = fixture.publish_fixture(root)
                run_dir = root / "results" / interrupted_stage
                profile_path = root / "profiles" / f"{interrupted_stage}.jsonl"
                resumed_profile_path = (
                    root / "profiles" / f"{interrupted_stage}-resumed.jsonl"
                )
                tools = FakeToolAttempts(
                    interrupt_stage=(
                        interrupted_stage if interrupted_stage != "oracle" else None
                    )
                )
                oracle = (
                    mock.Mock(side_effect=RuntimeError("forced oracle interruption"))
                    if interrupted_stage == "oracle"
                    else mock.Mock(
                        return_value=(
                            "oracle_pass",
                            [],
                            {"from": "exact", "to": "exact"},
                            {"move_count": 1},
                        )
                    )
                )
                with (
                    mock.patch(
                        "bigMoveBench.normalized_execution.execute_attempt",
                        side_effect=tools,
                    ),
                    mock.patch(
                        "bigMoveBench.normalized_execution.validate_srcdiff_semantics",
                        return_value=SemanticResult(SemanticStatus.ELIGIBLE, {}),
                    ),
                    mock.patch(
                        "bigMoveBench.normalized_execution._score_completed_case",
                        side_effect=oracle,
                    ),
                    self.assertRaisesRegex(RuntimeError, "forced"),
                ):
                    self._runner(
                        benchmark_cases,
                        run_dir,
                        runner_profile_path=profile_path,
                    ).run()

                successful_tools = FakeToolAttempts()
                patches = self._successful_patches(successful_tools)
                with patches[0], patches[1], patches[2]:
                    _, summary = self._runner(
                        benchmark_cases,
                        run_dir,
                        runner_profile_path=resumed_profile_path,
                    ).run()
                self.assertEqual(summary["counts"]["oracle_pass"], 1)
                self.assertEqual(profile_path.read_text(encoding="utf-8"), "")
                profile_records = [
                    json.loads(line)
                    for line in resumed_profile_path.read_text(
                        encoding="utf-8"
                    ).splitlines()
                ]
                self.assertEqual(len(profile_records), 1)
                self.assertEqual(profile_records[0]["outcome"], "oracle_pass")
                with closing(
                    sqlite3.connect(run_dir / "execution.sqlite")
                ) as connection:
                    self.assertEqual(
                        connection.execute(
                            "SELECT status, COUNT(*) FROM attempts GROUP BY status "
                            "ORDER BY status"
                        ).fetchall(),
                        [("interrupted", 1), ("terminal", 1)],
                    )
                    self.assertEqual(
                        connection.execute(
                            "SELECT GROUP_CONCAT(attempt_ordinal, ',') FROM attempts "
                            "ORDER BY attempt_ordinal"
                        ).fetchone()[0],
                        "0,1",
                    )


if __name__ == "__main__":
    unittest.main()
