from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from repository_analysis.analysis import AnalysisTarget, analyze_repository
from repository_analysis.database import AnalysisDatabase
from repository_analysis.inputs import AnalysisConfiguration, RepositoryIdentity
from repository_analysis.locking import AnalysisBusyError, AnalysisOperationLock
from repository_analysis.worker import PairExecutor


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


class AnalyzeRepositoryTests(unittest.TestCase):
    def test_total_target_is_idempotent_and_extends_without_renumbering(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository, commits = self._history(root, 7)
            analysis = root / "analysis"
            srcdiff = executable(root / "srcdiff")
            srcmove = executable(root / "srcmove")

            first = self._analyze(
                analysis, repository, srcdiff, srcmove, total_pairs=2
            )
            self.assertEqual(first.summary["completed_pair_count"], 2)
            self.assertEqual(first.summary["oldest_completed_commit"], commits[4])
            stale = analysis / "scratch" / "interrupted" / "large-input.c"
            stale.parent.mkdir(parents=True)
            stale.write_bytes(b"stale materialized input")

            with patch.object(
                PairExecutor,
                "open_worker",
                side_effect=AssertionError("idempotent target opened a worker"),
            ):
                repeated = analyze_repository(
                    analysis_root=analysis,
                    target=AnalysisTarget("total_pairs", 2),
                    jobs=1,
                )
            self.assertEqual(repeated.execution.submitted_count, 0)
            self.assertEqual(repeated.summary["completed_pair_count"], 2)
            self.assertEqual(
                repeated.summary["invocation"]["result"], "target_reached"
            )
            self.assertFalse(stale.exists())

            with AnalysisDatabase.open(analysis, read_only=True) as database:
                invocations = database.connection.execute(
                    "SELECT result FROM invocations ORDER BY created_order"
                ).fetchall()
            self.assertEqual(
                [row[0] for row in invocations],
                ["target_reached", "target_reached"],
            )

            extended = analyze_repository(
                analysis_root=analysis,
                target=AnalysisTarget("total_pairs", 4),
                jobs=2,
            )
            self.assertEqual(extended.summary["completed_pair_count"], 4)
            self.assertEqual(extended.summary["oldest_completed_commit"], commits[2])

    def test_root_bounded_target_records_exhaustion_and_repeats_as_noop(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository, commits = self._history(root, 4)
            analysis = root / "analysis"
            srcdiff = executable(root / "srcdiff")
            srcmove = executable(root / "srcmove")

            result = self._analyze(
                analysis, repository, srcdiff, srcmove, total_pairs=100
            )
            self.assertEqual(result.summary["completed_pair_count"], 3)
            self.assertEqual(result.summary["oldest_completed_commit"], commits[0])
            self.assertTrue(result.summary["history_exhausted"])

            with patch.object(
                PairExecutor,
                "open_worker",
                side_effect=AssertionError("exhausted analysis opened a worker"),
            ):
                repeated = analyze_repository(
                    analysis_root=analysis,
                    target=AnalysisTarget("total_pairs", 100),
                    jobs=1,
                )
            self.assertEqual(repeated.execution.submitted_count, 0)
            self.assertTrue(repeated.summary["history_exhausted"])

    def test_through_target_is_bound_to_frozen_newest_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository, commits = self._history(root, 6)
            analysis = root / "analysis"
            srcdiff = executable(root / "srcdiff")
            srcmove = executable(root / "srcmove")

            result = self._analyze(
                analysis,
                repository,
                srcdiff,
                srcmove,
                through=commits[2],
            )
            self.assertEqual(result.summary["completed_pair_count"], 3)
            self.assertEqual(result.summary["oldest_completed_commit"], commits[2])
            self._commit(repository, "branch-moved")

            with patch.object(
                PairExecutor,
                "open_worker",
                side_effect=AssertionError("completed through target opened a worker"),
            ):
                repeated = analyze_repository(
                    analysis_root=analysis,
                    target=AnalysisTarget("through", commits[2]),
                    jobs=1,
                )
            self.assertEqual(repeated.summary["newest_commit"], commits[-1])
            self.assertEqual(repeated.execution.submitted_count, 0)

    def test_terminal_failure_is_committed_and_retry_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository = root / "repository"
            repository.mkdir()
            git(repository, "init", "--initial-branch=main")
            git(repository, "config", "user.name", "Analysis Test")
            git(repository, "config", "user.email", "analysis@example.invalid")
            (repository / "fixture.c").write_text("int one;\n", encoding="utf-8")
            git(repository, "add", "fixture.c")
            git(repository, "commit", "-m", "one")
            (repository / "fixture.c").write_text("int two;\n", encoding="utf-8")
            git(repository, "commit", "-am", "two")
            analysis = root / "analysis"
            srcdiff = executable(root / "srcdiff")
            srcmove = executable(root / "srcmove")

            result = analyze_repository(
                analysis_root=analysis,
                target=AnalysisTarget("total_pairs", 1),
                jobs=1,
                repository=repository,
                repository_identity=RepositoryIdentity("fixture-repository"),
                srcdiff_path=srcdiff,
                srcmove_path=srcmove,
            )
            self.assertEqual(result.summary["completed_pair_count"], 1)
            self.assertEqual(result.summary["failed"], 1)
            self.assertEqual(result.summary["statuses"], {"srcdiff_failed": 1})

            with patch.object(
                PairExecutor,
                "open_worker",
                side_effect=AssertionError("committed failure opened a worker"),
            ):
                repeated = analyze_repository(
                    analysis_root=analysis,
                    target=AnalysisTarget("total_pairs", 1),
                    jobs=1,
                )
            self.assertEqual(repeated.summary["failed"], 1)
            self.assertEqual(repeated.execution.submitted_count, 0)

    def test_sealed_pending_batch_commits_without_reopening_workers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository, _ = self._history(root, 5)
            analysis = root / "analysis"
            srcdiff = executable(root / "srcdiff")
            srcmove = executable(root / "srcmove")
            with patch.object(
                AnalysisDatabase,
                "commit_pending_batch",
                side_effect=RuntimeError("injected after sealed outcomes"),
            ):
                with self.assertRaisesRegex(RuntimeError, "injected"):
                    self._analyze(
                        analysis, repository, srcdiff, srcmove, total_pairs=2
                    )

            with patch.object(
                PairExecutor,
                "open_worker",
                side_effect=AssertionError("smaller target opened a worker"),
            ):
                with self.assertRaisesRegex(ValueError, "smaller than frozen"):
                    analyze_repository(
                        analysis_root=analysis,
                        target=AnalysisTarget("total_pairs", 1),
                        jobs=1,
                    )

            with patch.object(
                PairExecutor,
                "open_worker",
                side_effect=AssertionError("sealed pending batch opened a worker"),
            ):
                resumed = analyze_repository(
                    analysis_root=analysis,
                    target=AnalysisTarget("total_pairs", 2),
                    jobs=1,
                )
            self.assertEqual(resumed.summary["completed_pair_count"], 2)
            self.assertEqual(resumed.execution.submitted_count, 0)

            extended = analyze_repository(
                analysis_root=analysis,
                target=AnalysisTarget("total_pairs", 3),
                jobs=1,
            )
            self.assertEqual(extended.summary["completed_pair_count"], 3)

    def test_all_history_is_split_into_bounded_internal_batches(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository, _ = self._history(root, 7)
            analysis = root / "analysis"
            with patch("repository_analysis.analysis.DEFAULT_BATCH_PAIR_LIMIT", 2):
                result = analyze_repository(
                    analysis_root=analysis,
                    target=AnalysisTarget("all", None),
                    jobs=2,
                    repository=repository,
                    repository_identity=RepositoryIdentity("fixture-repository"),
                    configuration=AnalysisConfiguration(excluded_suffixes=(".txt",)),
                    srcdiff_path=executable(root / "srcdiff"),
                    srcmove_path=executable(root / "srcmove"),
                )
            self.assertEqual(result.summary["completed_pair_count"], 6)
            self.assertTrue(result.summary["history_exhausted"])
            with AnalysisDatabase.open(analysis) as database:
                sizes = database.connection.execute(
                    "SELECT pair_count FROM batches ORDER BY created_order"
                ).fetchall()
            self.assertEqual([row[0] for row in sizes], [2, 2, 2])

    def test_retry_after_final_state_commit_does_not_extend(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository, _ = self._history(root, 4)
            analysis = root / "analysis"
            original_summary = AnalysisDatabase.summary
            calls = 0

            def fail_first_summary(database):
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise RuntimeError("injected after final state commit")
                return original_summary(database)

            with patch.object(AnalysisDatabase, "summary", fail_first_summary):
                with self.assertRaisesRegex(RuntimeError, "final state commit"):
                    self._analyze(
                        analysis,
                        repository,
                        executable(root / "srcdiff"),
                        executable(root / "srcmove"),
                        total_pairs=2,
                    )

            with patch.object(
                PairExecutor,
                "open_worker",
                side_effect=AssertionError("committed retry opened a worker"),
            ):
                repeated = analyze_repository(
                    analysis_root=analysis,
                    target=AnalysisTarget("total_pairs", 2),
                    jobs=1,
                )
            self.assertEqual(repeated.summary["completed_pair_count"], 2)
            self.assertEqual(repeated.execution.submitted_count, 0)

    def test_lock_contention_precedes_database_load_and_worker_open(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository, _ = self._history(root, 3)
            analysis = root / "analysis"
            self._analyze(
                analysis,
                repository,
                executable(root / "srcdiff"),
                executable(root / "srcmove"),
                total_pairs=1,
            )
            database_bytes = (analysis / "analysis.sqlite3").read_bytes()

            with AnalysisOperationLock(analysis, command="owner"):
                with patch.object(
                    AnalysisDatabase,
                    "open",
                    side_effect=AssertionError("contender loaded analysis state"),
                ), patch.object(
                    PairExecutor,
                    "open_worker",
                    side_effect=AssertionError("contender opened a worker"),
                ):
                    with self.assertRaises(AnalysisBusyError):
                        analyze_repository(
                            analysis_root=analysis,
                            target=AnalysisTarget("total_pairs", 2),
                            jobs=1,
                        )

            self.assertEqual(
                (analysis / "analysis.sqlite3").read_bytes(), database_bytes
            )

    def test_keyboard_interrupt_is_recorded_as_interrupted_invocation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository, _ = self._history(root, 3)
            analysis = root / "analysis"
            self._analyze(
                analysis,
                repository,
                executable(root / "srcdiff"),
                executable(root / "srcmove"),
                total_pairs=1,
            )

            with patch(
                "repository_analysis.analysis._advance_analysis",
                side_effect=KeyboardInterrupt,
            ), self.assertRaises(KeyboardInterrupt):
                analyze_repository(
                    analysis_root=analysis,
                    target=AnalysisTarget("total_pairs", 1),
                    jobs=1,
                )

            with AnalysisDatabase.open(analysis, read_only=True) as database:
                invocation = database.latest_invocation()
            assert invocation is not None
            self.assertEqual(invocation.result, "interrupted")
            self.assertEqual(invocation.error, "KeyboardInterrupt")

    def _analyze(
        self,
        analysis,
        repository,
        srcdiff,
        srcmove,
        *,
        total_pairs=None,
        through=None,
    ):
        target = (
            AnalysisTarget("through", through)
            if through is not None
            else AnalysisTarget("total_pairs", total_pairs)
        )
        return analyze_repository(
            analysis_root=analysis,
            target=target,
            jobs=2,
            repository=repository,
            repository_identity=RepositoryIdentity("fixture-repository"),
            configuration=AnalysisConfiguration(excluded_suffixes=(".txt",)),
            srcdiff_path=srcdiff,
            srcmove_path=srcmove,
        )

    def _history(self, root: Path, count: int):
        repository = root / "repository"
        repository.mkdir()
        git(repository, "init", "--initial-branch=main")
        git(repository, "config", "user.name", "Analysis Test")
        git(repository, "config", "user.email", "analysis@example.invalid")
        commits = tuple(self._commit(repository, f"commit-{index}") for index in range(count))
        return repository, commits

    def _commit(self, repository: Path, content: str) -> str:
        (repository / "fixture.txt").write_text(content, encoding="utf-8")
        git(repository, "add", "fixture.txt")
        git(repository, "commit", "-m", content)
        return git(repository, "rev-parse", "HEAD")


if __name__ == "__main__":
    unittest.main()
