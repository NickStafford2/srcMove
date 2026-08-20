from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from repository_analysis.database import AnalysisDatabase
from repository_analysis.contracts import PairOutcome, PairStatus
from repository_analysis.inputs import (
    AnalysisConfiguration,
    RepositoryIdentity,
    freeze_analysis_inputs,
    observe_executable,
    build_pair_work_items,
)
from repository_analysis.retention import RetentionPolicy


def executable(path: Path, content: bytes = b"#!/bin/sh\nexit 0\n") -> Path:
    path.write_bytes(content)
    path.chmod(0o755)
    return path


class AnalysisDatabaseTests(unittest.TestCase):
    def test_only_truthful_compact_retention_is_supported(self) -> None:
        self.assertEqual(
            RetentionPolicy().record(),
            {
                "schema_version": 1,
                "mode": "compact",
                "successful_pairs": "metrics_xpaths_and_text_digests",
                "failed_pairs": "bounded_process_evidence",
                "tool_outputs": "discard_after_compaction",
                "materialized_inputs": "ephemeral",
            },
        )
        with self.assertRaisesRegex(ValueError, "unsupported"):
            RetentionPolicy(mode="full")

    def test_invocations_are_append_only_and_reconcile_interrupted_writer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository = root / "repository"
            repository.mkdir()
            manifest = self._manifest(
                repository,
                observe_executable(executable(root / "srcdiff")),
                observe_executable(executable(root / "srcmove")),
                commits=("a", "b"),
            )
            with AnalysisDatabase.create(
                root / "analysis",
                manifest,
                batch_id="a" * 32,
                target_kind="total_pairs",
                target_value="1",
                reaches_root=True,
                retention_policy=RetentionPolicy(),
            ) as database:
                first = database.begin_invocation(
                    "1" * 32,
                    target_kind="total_pairs",
                    target_value="1",
                    jobs=2,
                    started_at="2026-01-01T00:00:00+00:00",
                )
                self.assertEqual(first.result, "running")

                second = database.begin_invocation(
                    "2" * 32,
                    target_kind="all",
                    target_value=None,
                    jobs=4,
                    started_at="2026-01-02T00:00:00+00:00",
                )

                self.assertEqual(database.invocation("1" * 32).result, "interrupted")
                self.assertEqual(second.created_order, 1)
                batch = database.pending_batch()
                assert batch is not None
                database.record_outcome(
                    batch,
                    PairOutcome(
                        build_pair_work_items(manifest)[0],
                        PairStatus.NO_ANALYZABLE_CHANGE,
                    ),
                    invocation_id="2" * 32,
                )
                self.assertNotEqual(
                    database.invocation("2" * 32).last_durable_at,
                    second.last_durable_at,
                )
                finished = database.finish_invocation(
                    "2" * 32,
                    result="target_reached",
                    ended_at="2026-01-02T00:00:03+00:00",
                    wall_seconds=3.0,
                )
                self.assertEqual(finished.result, "target_reached")
                self.assertEqual(finished.wall_seconds, 3.0)
                self.assertEqual(database.latest_invocation(), finished)
                with self.assertRaisesRegex(ValueError, "already finalized"):
                    database.finish_invocation(
                        "2" * 32,
                        result="failed",
                        ended_at="2026-01-02T00:00:04+00:00",
                        wall_seconds=4.0,
                    )

    def test_schema_v1_root_is_rejected_with_fresh_start_instruction(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository = root / "repository"
            repository.mkdir()
            manifest = self._manifest(
                repository,
                observe_executable(executable(root / "srcdiff")),
                observe_executable(executable(root / "srcmove")),
                commits=("a", "b"),
            )
            analysis = root / "analysis"
            database = AnalysisDatabase.create(
                analysis,
                manifest,
                batch_id="b" * 32,
                target_kind="total_pairs",
                target_value="1",
                reaches_root=True,
                retention_policy=RetentionPolicy(),
            )
            database.close()
            with sqlite3.connect(analysis / "analysis.sqlite3") as connection:
                connection.execute("PRAGMA user_version = 1")

            with self.assertRaisesRegex(ValueError, "start a fresh analysis root"):
                AnalysisDatabase.open(analysis)

    def test_batches_extend_without_renumbering_completed_pairs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository = root / "repository"
            repository.mkdir()
            srcdiff = observe_executable(executable(root / "srcdiff"))
            srcmove = observe_executable(executable(root / "srcmove"))
            analysis_root = root / "analysis"
            initial = self._manifest(
                repository, srcdiff, srcmove, commits=("d", "e", "f")
            )

            with AnalysisDatabase.create(
                analysis_root,
                initial,
                batch_id="1" * 32,
                target_kind="total_pairs",
                target_value="2",
                reaches_root=False,
                retention_policy=RetentionPolicy(),
            ) as database:
                state = database.analysis()
                self.assertEqual(state.revision, 1)
                self.assertEqual(state.completed_pair_count, 0)
                batch = database.pending_batch()
                self.assertIsNotNone(batch)
                assert batch is not None
                self.assertEqual(database.pending_manifest(batch), initial)
                self.assertEqual(database.completed_prefix(batch), 0)

                work = build_pair_work_items(initial)
                database.record_outcome(
                    batch, PairOutcome(work[0], PairStatus.NO_ANALYZABLE_CHANGE)
                )
                self.assertEqual(database.completed_prefix(batch), 1)
                database.record_outcome(
                    batch, PairOutcome(work[1], PairStatus.NO_ANALYZABLE_CHANGE)
                )
                committed = database.commit_pending_batch(batch)
                self.assertEqual(committed.revision, 2)
                self.assertEqual(committed.completed_pair_count, 2)
                self.assertEqual(committed.oldest_completed_commit, "d")
                summary = database.summary()
                self.assertEqual(summary["completed_pair_count"], 2)
                self.assertEqual(summary["no_analyzable_change"], 2)
                details = database.pair_details(1)
                self.assertEqual(details["old_commit"], "d")
                self.assertEqual(details["new_commit"], "e")
                self.assertEqual(details["moves"], [])

                older = self._manifest(
                    repository, srcdiff, srcmove, commits=("b", "c", "d")
                )
                older_batch = database.add_pending_batch(
                    older,
                    batch_id="2" * 32,
                    target_kind="total_pairs",
                    target_value="4",
                    reaches_root=True,
                    retention_policy=RetentionPolicy(),
                )
                distances = database.connection.execute(
                    "SELECT distance_from_newest FROM pairs ORDER BY distance_from_newest"
                ).fetchall()
                self.assertEqual([row[0] for row in distances], [0, 1, 2, 3])
                self.assertEqual(older_batch.base_revision, 2)
                self.assertEqual(database.analysis().revision, 3)

                with self.assertRaisesRegex(ValueError, "no committed pair"):
                    database.pair_details(2)

    def test_pair_outcomes_are_exclusive_and_completion_requires_full_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository = root / "repository"
            repository.mkdir()
            srcdiff = observe_executable(executable(root / "srcdiff"))
            srcmove = observe_executable(executable(root / "srcmove"))
            manifest = self._manifest(
                repository, srcdiff, srcmove, commits=("a", "b", "c")
            )
            database = AnalysisDatabase.create(
                root / "analysis",
                manifest,
                batch_id="a" * 32,
                target_kind="all",
                target_value=None,
                reaches_root=True,
                retention_policy=RetentionPolicy(),
            )
            self.addCleanup(database.close)
            batch = database.pending_batch()
            assert batch is not None

            outcome = PairOutcome(
                build_pair_work_items(manifest)[0],
                PairStatus.NO_ANALYZABLE_CHANGE,
            )
            database.record_outcome(batch, outcome)
            with self.assertRaisesRegex(ValueError, "already sealed"):
                database.record_outcome(batch, outcome)
            with self.assertRaisesRegex(ValueError, "not complete"):
                database.commit_pending_batch(batch)

    def test_database_reopens_with_canonical_manifest_and_schema_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository = root / "repository"
            repository.mkdir()
            srcdiff = observe_executable(executable(root / "srcdiff"))
            srcmove = observe_executable(executable(root / "srcmove"))
            manifest = self._manifest(
                repository, srcdiff, srcmove, commits=("a", "b")
            )
            database = AnalysisDatabase.create(
                root / "analysis",
                manifest,
                batch_id="f" * 32,
                target_kind="through",
                target_value="a",
                reaches_root=False,
                retention_policy=RetentionPolicy(),
            )
            database.close()

            with AnalysisDatabase.open(root / "analysis") as reopened:
                batch = reopened.pending_batch()
                self.assertIsNotNone(batch)
                assert batch is not None
                self.assertEqual(reopened.pending_manifest(batch), manifest)

    def test_read_only_status_can_observe_last_committed_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository = root / "repository"
            repository.mkdir()
            srcdiff = observe_executable(executable(root / "srcdiff"))
            srcmove = observe_executable(executable(root / "srcmove"))
            analysis = root / "analysis"
            manifest = self._manifest(
                repository, srcdiff, srcmove, commits=("a", "b")
            )
            with AnalysisDatabase.create(
                analysis,
                manifest,
                batch_id="e" * 32,
                target_kind="total_pairs",
                target_value="1",
                reaches_root=False,
                retention_policy=RetentionPolicy(),
            ) as writer:
                writer.connection.execute("BEGIN IMMEDIATE")
                try:
                    writer.connection.execute(
                        "UPDATE analysis SET revision = 99 WHERE singleton = 1"
                    )
                    with AnalysisDatabase.open(
                        analysis, read_only=True
                    ) as reader:
                        self.assertEqual(reader.analysis().revision, 1)
                finally:
                    writer.connection.execute("ROLLBACK")

    def test_writer_recovers_exact_interrupted_database_publication_link(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository = root / "repository"
            repository.mkdir()
            manifest = self._manifest(
                repository,
                observe_executable(executable(root / "srcdiff")),
                observe_executable(executable(root / "srcmove")),
                commits=("a", "b"),
            )
            analysis = root / "analysis"
            database = AnalysisDatabase.create(
                analysis,
                manifest,
                batch_id="d" * 32,
                target_kind="total_pairs",
                target_value="1",
                reaches_root=False,
                retention_policy=RetentionPolicy(),
            )
            database.close()
            interrupted = analysis / ".analysis.sqlite3.tmp-interrupted"
            os.link(analysis / "analysis.sqlite3", interrupted)

            with self.assertRaisesRegex(ValueError, "one owned regular file"):
                AnalysisDatabase.open(analysis, read_only=True)
            self.assertTrue(interrupted.exists())

            with AnalysisDatabase.open(analysis) as recovered:
                self.assertEqual(recovered.analysis().revision, 1)
            self.assertFalse(interrupted.exists())

    def _manifest(self, repository, srcdiff, srcmove, *, commits):
        return freeze_analysis_inputs(
            repository=repository,
            repository_identity=RepositoryIdentity("fixture-repository"),
            commits=commits,
            configuration=AnalysisConfiguration(excluded_suffixes=(".txt",)),
            srcdiff=srcdiff,
            srcmove=srcmove,
        )


if __name__ == "__main__":
    unittest.main()
