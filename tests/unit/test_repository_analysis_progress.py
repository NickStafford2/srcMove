from __future__ import annotations

from dataclasses import FrozenInstanceError
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from repository_analysis.contracts import PairStatus
from repository_analysis.progress import (
    AnalysisProgressStart,
    NullAnalysisObserver,
    PairPublished,
    TerminalAnalysisObserver,
)


def _start(*, target: int | None = 10) -> AnalysisProgressStart:
    return AnalysisProgressStart(
        name="sqlite",
        target_total=target,
        covered=0,
        analyzed=0,
        skipped=0,
        failed=0,
        moves=0,
        jobs=8,
    )


class _LiveOutput(io.StringIO):
    def isatty(self) -> bool:
        return True


class RepositoryAnalysisProgressTests(unittest.TestCase):
    def test_events_are_frozen_and_validate_counters(self) -> None:
        event = _start()
        with self.assertRaises(FrozenInstanceError):
            event.covered = 1  # type: ignore[misc]
        with self.assertRaises(ValueError):
            PairPublished(covered=-1, status=PairStatus.COMPLETED)
        with self.assertRaises(ValueError):
            AnalysisProgressStart("sqlite", 10, 0, 0, 0, 0, 0, 0)

    def test_null_observer_accepts_all_events(self) -> None:
        observer = NullAnalysisObserver()
        observer.analysis_started(_start())
        observer.pair_published(PairPublished(1, PairStatus.COMPLETED, 2))
        observer.analysis_finished(detail="done")

    def test_context_entry_immediately_reports_preparation(self) -> None:
        output = io.StringIO()
        observer = TerminalAnalysisObserver(stream=output)

        with observer:
            self.assertEqual(output.getvalue(), "[history] preparing: 00:00\n")

        self.assertIn("[history] complete:", output.getvalue())

    def test_redirected_progress_is_durable_and_sparse(self) -> None:
        output = io.StringIO()
        with TerminalAnalysisObserver(
            stream=output, log_interval_seconds=30
        ) as observer:
            observer.analysis_started(_start())
            for covered, status, moves in (
                (1, PairStatus.COMPLETED, 2),
                (2, PairStatus.NO_ANALYZABLE_CHANGE, 0),
                (3, PairStatus.SRCDIFF_FAILED, 0),
                (4, PairStatus.COMPLETED, 1),
                (5, PairStatus.NO_ANALYZABLE_CHANGE, 0),
            ):
                observer.pair_published(PairPublished(covered, status, moves))
            observer.analysis_finished()
            observer.analysis_finished(result="failed", detail="duplicate")

        lines = output.getvalue().splitlines()
        self.assertEqual(lines[0], "[history] preparing: 00:00")
        self.assertIn("[sqlite] started: 0/10", lines[1])
        self.assertIn("[sqlite] complete: 5/10  50%", lines[-1])
        self.assertIn("2 analyzed · 2 skipped · 1 failed", lines[-1])
        self.assertIn("3 moves · 8 workers", lines[-1])
        self.assertNotIn("duplicate", output.getvalue())
        # Preparation, start, and completion; a five-pair run is too small for
        # intermediate redirected milestones.
        self.assertEqual(len(lines), 3)

    def test_live_progress_has_spinner_bar_and_delayed_eta(self) -> None:
        class Clock:
            now = 100.0

            def __call__(self) -> float:
                return self.now

        clock = Clock()
        output = _LiveOutput()
        with patch("repository_analysis.progress.time.monotonic", clock):
            with TerminalAnalysisObserver(
                stream=output, refresh_seconds=60
            ) as observer:
                observer.analysis_started(_start())
                for covered in range(1, 4):
                    clock.now += 0.5
                    observer.pair_published(
                        PairPublished(covered, PairStatus.COMPLETED)
                    )
                self.assertIn("ETA 00:03", output.getvalue())

        rendered = output.getvalue()
        self.assertIn("Analyzing sqlite", rendered)
        self.assertIn("[█", rendered)
        self.assertIn("3/10  30%", rendered)
        self.assertIn("3 analyzed", rendered)
        self.assertIn("✓ Analysis sqlite complete", rendered)

    def test_unknown_target_never_invents_percentage_or_eta(self) -> None:
        output = io.StringIO()
        with TerminalAnalysisObserver(stream=output) as observer:
            observer.analysis_started(_start(target=None))
            observer.pair_published(PairPublished(1, PairStatus.COMPLETED))

        self.assertIn("1 pairs covered", output.getvalue())
        self.assertNotIn("%", output.getvalue())
        self.assertNotIn("ETA", output.getvalue())

    def test_disabled_and_broken_streams_cannot_affect_analysis(self) -> None:
        quiet = io.StringIO()
        with TerminalAnalysisObserver(stream=quiet, enabled=False) as observer:
            observer.analysis_started(_start())
            observer.pair_published(PairPublished(1, PairStatus.COMPLETED))
        self.assertEqual(quiet.getvalue(), "")

        class BrokenStream(io.StringIO):
            def write(self, value: str) -> int:
                raise OSError("closed")

        with TerminalAnalysisObserver(stream=BrokenStream()) as observer:
            observer.analysis_started(_start())
            observer.pair_published(PairPublished(1, PairStatus.COMPLETED))

    def test_context_exception_emits_one_failure_line(self) -> None:
        output = io.StringIO()
        with self.assertRaisesRegex(RuntimeError, "boom"):
            with TerminalAnalysisObserver(stream=output) as observer:
                observer.analysis_started(_start())
                raise RuntimeError("boom")

        self.assertIn("[sqlite] failed:", output.getvalue())
        self.assertIn("— boom", output.getvalue())
        self.assertNotIn("[sqlite] complete:", output.getvalue())

    def test_completed_with_failures_and_exceeded_target_are_explicit(self) -> None:
        output = io.StringIO()
        with TerminalAnalysisObserver(stream=output) as observer:
            observer.analysis_started(
                AnalysisProgressStart("sqlite", 2, 3, 1, 1, 1, 0, 2)
            )
            observer.analysis_finished(result="complete_with_failures")

        rendered = output.getvalue()
        self.assertIn("complete with failures", rendered)
        self.assertIn("3 pairs covered · target 2 satisfied", rendered)
        self.assertNotIn("3/2", rendered)


if __name__ == "__main__":
    unittest.main()
