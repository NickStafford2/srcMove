from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from repository_analysis.analysis import (
    AnalysisTarget,
    analysis_status,
    analyze_repository,
)
from repository_analysis.database import AnalysisDatabase
from repository_analysis.inputs import AnalysisConfiguration, RepositoryIdentity


def git(repository: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def executable(path: Path) -> Path:
    path.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
    path.chmod(0o755)
    return path


class RecordingObserver:
    def __init__(self, analysis: Path) -> None:
        self.analysis = analysis
        self.starts = []
        self.pairs = []
        self.visible_coverage = []
        self.finishes = []

    def analysis_started(self, event) -> None:
        self.starts.append(event)

    def pair_published(self, event) -> None:
        self.pairs.append(event)
        status = analysis_status(self.analysis)
        self.visible_coverage.append(status["durable_pair_count"])

    def analysis_finished(self, *, result="complete", detail=None) -> None:
        self.finishes.append((result, detail))


class RepositoryAnalysisObserverTests(unittest.TestCase):
    def test_events_follow_durable_publication_and_no_op_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository = self._history(root, 4)
            analysis = root / "analysis"
            observer = RecordingObserver(analysis)

            result = self._analyze(analysis, repository, observer, pairs=3)

            self.assertEqual(result.summary["completed_pair_count"], 3)
            self.assertEqual(observer.starts[0].covered, 0)
            self.assertEqual(observer.starts[0].target_total, 3)
            self.assertEqual([event.covered for event in observer.pairs], [1, 2, 3])
            self.assertEqual(observer.visible_coverage, [1, 2, 3])
            self.assertEqual(
                [event.status.value for event in observer.pairs],
                ["no_analyzable_change"] * 3,
            )
            self.assertEqual(observer.finishes, [("complete", None)])

            no_op = RecordingObserver(analysis)
            repeated = analyze_repository(
                analysis_root=analysis,
                target=AnalysisTarget("total_pairs", 3),
                jobs=1,
                observer=no_op,
            )

            self.assertEqual(repeated.execution.submitted_count, 0)
            self.assertEqual(no_op.starts[0].covered, 3)
            self.assertEqual(no_op.pairs, [])
            self.assertEqual(no_op.finishes, [("complete", None)])

    def test_resume_baseline_includes_durable_pending_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository = self._history(root, 4)
            analysis = root / "analysis"
            original = AnalysisDatabase.record_outcome
            calls = 0

            def fail_second(database, *arguments, **keywords):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise RuntimeError("injected publication stop")
                return original(database, *arguments, **keywords)

            with patch.object(AnalysisDatabase, "record_outcome", fail_second):
                with self.assertRaisesRegex(RuntimeError, "publication stop"):
                    self._analyze(
                        analysis,
                        repository,
                        RecordingObserver(analysis),
                        pairs=3,
                    )

            resumed = RecordingObserver(analysis)
            result = analyze_repository(
                analysis_root=analysis,
                target=AnalysisTarget("total_pairs", 3),
                jobs=2,
                observer=resumed,
            )

            self.assertEqual(result.summary["completed_pair_count"], 3)
            self.assertEqual(resumed.starts[0].covered, 1)
            self.assertEqual([event.covered for event in resumed.pairs], [2, 3])

    def test_broken_observer_is_disabled_without_failing_analysis(self) -> None:
        class BrokenObserver:
            def analysis_started(self, event) -> None:
                raise OSError("broken display")

            def pair_published(self, event) -> None:
                raise AssertionError("disabled observer was called again")

            def analysis_finished(self, *, result="complete", detail=None) -> None:
                raise AssertionError("disabled observer was called again")

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            result = self._analyze(
                root / "analysis",
                self._history(root, 3),
                BrokenObserver(),
                pairs=2,
            )

        self.assertEqual(result.summary["completed_pair_count"], 2)

    def test_all_history_progress_is_monotonic_across_internal_batches(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository = self._history(root, 6)
            analysis = root / "analysis"
            observer = RecordingObserver(analysis)
            with patch("repository_analysis.analysis.DEFAULT_BATCH_PAIR_LIMIT", 2):
                result = analyze_repository(
                    analysis_root=analysis,
                    target=AnalysisTarget("all", None),
                    jobs=2,
                    repository=repository,
                    repository_identity=RepositoryIdentity("observer-fixture"),
                    configuration=AnalysisConfiguration(
                        excluded_suffixes=(".txt",)
                    ),
                    srcdiff_path=executable(root / "srcdiff"),
                    srcmove_path=executable(root / "srcmove"),
                    observer=observer,
                )

            self.assertTrue(result.summary["history_exhausted"])
            self.assertIsNone(observer.starts[0].target_total)
            self.assertEqual(
                [event.covered for event in observer.pairs], [1, 2, 3, 4, 5]
            )

    def test_short_history_reports_exhaustion_instead_of_completion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            analysis = root / "analysis"
            observer = RecordingObserver(analysis)

            result = self._analyze(
                analysis,
                self._history(root, 3),
                observer,
                pairs=10,
            )

            self.assertTrue(result.summary["history_exhausted"])
            self.assertEqual(observer.finishes, [("history_exhausted", None)])

    def _analyze(self, analysis, repository, observer, *, pairs):
        root = analysis.parent
        return analyze_repository(
            analysis_root=analysis,
            target=AnalysisTarget("total_pairs", pairs),
            jobs=2,
            repository=repository,
            repository_identity=RepositoryIdentity("observer-fixture"),
            configuration=AnalysisConfiguration(excluded_suffixes=(".txt",)),
            srcdiff_path=executable(root / "srcdiff"),
            srcmove_path=executable(root / "srcmove"),
            observer=observer,
        )

    def _history(self, root: Path, count: int) -> Path:
        repository = root / "repository"
        repository.mkdir()
        git(repository, "init", "--initial-branch=main")
        git(repository, "config", "user.name", "Observer Test")
        git(repository, "config", "user.email", "observer@example.invalid")
        for index in range(count):
            (repository / "fixture.txt").write_text(
                f"commit-{index}", encoding="utf-8"
            )
            git(repository, "add", "fixture.txt")
            git(repository, "commit", "-m", f"commit-{index}")
        return repository


if __name__ == "__main__":
    unittest.main()
