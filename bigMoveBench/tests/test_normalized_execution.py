from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
import uuid
from contextlib import closing
from pathlib import Path
from unittest import mock

from bigMoveBench.contracts import SemanticResult, SemanticStatus
from bigMoveBench.normalized_execution import SerialBenchmarkExecutionRunner
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
        attempt_id = f"attempt-{stage}-{uuid.uuid4()}"
        attempt_dir = kwargs["attempts_root"] / attempt_id
        attempt_dir.mkdir(parents=True)
        output = attempt_dir / kwargs["output_filename"]
        output.write_text("<unit/>\n", encoding="utf-8")
        if stage == "srcmove":
            (attempt_dir / "results.json").write_text(
                json.dumps({"move_count": 1, "moves": []}), encoding="utf-8"
            )
        return attempt_dir, {
            "attempt_id": attempt_id,
            "admitted": True,
            "xml": {"status": "valid", "sha256": "b" * 64},
        }


class NormalizedExecutionTests(unittest.TestCase):
    def _runner(
        self, benchmark_cases, run_dir: Path, **kwargs
    ) -> SerialBenchmarkExecutionRunner:
        return SerialBenchmarkExecutionRunner(
            benchmark_cases,
            run_dir=run_dir,
            srcdiff=Path("/fake/srcdiff"),
            srcmove=Path("/fake/srcMove"),
            srcdiff_observation=TOOL_OBSERVATION,
            srcmove_observation=TOOL_OBSERVATION,
            **kwargs,
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
            self.assertNotIn("case_outcomes", summary)
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

    def test_semantic_ineligible_is_terminal_without_srcmove(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = test_benchmark_cases.NormalizedBenchmarkCasesTests()
            _, _, benchmark_cases, _ = fixture.publish_fixture(root)
            tools = FakeToolAttempts()
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
                    benchmark_cases, root / "results" / "semantic"
                ).run()
            self.assertEqual(tools.calls, ["srcdiff"])
            self.assertEqual(summary["counts"]["srcdiff_semantic_ineligible"], 1)
            self.assertEqual(summary["counts"]["executed"], 0)

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
                    self._runner(benchmark_cases, run_dir).run()

                successful_tools = FakeToolAttempts()
                patches = self._successful_patches(successful_tools)
                with patches[0], patches[1], patches[2]:
                    _, summary = self._runner(benchmark_cases, run_dir).run()
                self.assertEqual(summary["counts"]["oracle_pass"], 1)
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
