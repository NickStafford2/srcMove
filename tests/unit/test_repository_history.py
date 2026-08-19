from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.progress import ProgressDisplay
from benchmarks.corpus import create_input_snapshot
from benchmarks.repositories.adapter import (
    GitRepositorySnapshotAdapter,
    GitSnapshotEntry,
    GitSnapshotMaterializationError,
    RepositoryAdapter,
)
from benchmarks.repositories.run_history import (
    _aggregate,
    _coordinate_history_pairs,
    checkpoint_history_pair,
    export_changed_files,
    finalize_history_retention,
    inventory_changed_paths,
    load_history_results,
    print_history_results,
    print_history_summary,
    refresh_history_browse_view,
    parse_args,
    resolve_history_directory,
    select_first_parent_history,
    write_history_artifacts,
)
from benchmarks.process import write_json_atomic


def git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return result.stdout.strip()


def initialize_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    git(repo, "init", "--initial-branch=main")
    git(repo, "config", "user.name", "History Test")
    git(repo, "config", "user.email", "history@example.invalid")
    return repo


def commit_file(repo: Path, value: str, subject: str, timestamp: str | None = None) -> str:
    source = repo / "src" / "sample.c"
    source.parent.mkdir(exist_ok=True)
    source.write_text(value, encoding="utf-8")
    git(repo, "add", "src/sample.c")
    environment = None
    if timestamp is not None:
        import os

        environment = {
            **os.environ,
            "GIT_AUTHOR_DATE": timestamp,
            "GIT_COMMITTER_DATE": timestamp,
        }
    git(repo, "commit", "-m", subject, env=environment)
    return git(repo, "rev-parse", "HEAD")


class RepositoryHistoryTests(unittest.TestCase):
    def test_history_retention_cli_defaults_and_no_cache_alias(self) -> None:
        base = ["start", "sqlite", "--start", "HEAD", "--count", "1"]

        self.assertEqual(parse_args(base).retention, "results")
        self.assertEqual(parse_args(base).jobs, 1)
        self.assertEqual(parse_args([*base, "--jobs", "4"]).jobs, 4)
        self.assertEqual(parse_args([*base, "--no-cache"]).retention, "results")
        self.assertEqual(
            parse_args([*base, "--retention", "ephemeral"]).retention,
            "ephemeral",
        )

    def test_parallel_coordinator_publishes_in_order_with_isolated_work(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            history_dir = Path(temporary_directory) / "history"
            history_dir.mkdir()
            history = {
                "schema_version": 4,
                "history_id": "history-fixture",
                "status": "running",
                "pairs": [
                    {
                        "schema_version": 1,
                        "sequence": sequence,
                        "old_commit": chr(97 + sequence) * 40,
                        "new_commit": chr(98 + sequence) * 40,
                        "status": "pending",
                    }
                    for sequence in range(2)
                ],
            }
            completed: list[int] = []
            work_directories: list[Path] = []

            def worker(
                pair: dict, *, pair_work_dir: Path, **_: object
            ) -> dict:
                work_directories.append(pair_work_dir)
                pair_work_dir.mkdir(parents=True)
                if pair["sequence"] == 0:
                    time.sleep(0.1)
                completed.append(pair["sequence"])
                return {
                    **pair,
                    "status": "completed",
                    "counts": {"included_files": 2},
                    "metrics": {
                        "move_group_count": pair["sequence"],
                        "move_pair_count": pair["sequence"],
                    },
                    "timings": {"pair_seconds": 0.1},
                }

            _coordinate_history_pairs(
                history_dir,
                history,
                jobs=2,
                worker_arguments={},
                worker=worker,
                progress=ProgressDisplay("test", total=2, enabled=False),
            )

            self.assertEqual(completed, [1, 0])
            self.assertEqual(
                [path.name for path in work_directories], ["000001", "000002"]
            )
            self.assertEqual(len(set(work_directories)), 2)
            self.assertFalse((history_dir / ".work").exists())
            receipts = sorted((history_dir / "pairs").glob("*.json"))
            self.assertEqual(
                [path.name for path in receipts],
                ["000001.json", "000002.json"],
            )
            self.assertEqual(
                [json.loads(path.read_text())["sequence"] for path in receipts],
                [0, 1],
            )
            self.assertFalse((history_dir / "summary.csv").exists())
            self.assertFalse((history_dir / "moves").exists())

    def test_pair_checkpoint_writes_one_receipt_without_rewriting_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            history_dir = Path(temporary_directory) / "history"
            pairs_dir = history_dir / "pairs"
            pairs_dir.mkdir(parents=True)
            manifest_path = history_dir / "history.json"
            manifest_path.write_text('{"status":"running"}\n', encoding="utf-8")
            pair = {
                "schema_version": 1,
                "sequence": 0,
                "old_commit": "a" * 40,
                "new_commit": "b" * 40,
                "status": "completed",
                "timings": {"pair_seconds": 0.1},
            }
            history = {"status": "running", "pairs": [pair]}

            with patch(
                "benchmarks.repositories.run_history.write_json_atomic",
                wraps=write_json_atomic,
            ) as atomic_write:
                checkpoint_history_pair(history_dir, history, pair)

            self.assertEqual(atomic_write.call_count, 1)
            self.assertEqual(
                atomic_write.call_args.args[0], pairs_dir / "000001.json"
            )
            self.assertEqual(
                manifest_path.read_text(encoding="utf-8"),
                '{"status":"running"}\n',
            )
            persisted = json.loads(
                (pairs_dir / "000001.json").read_text(encoding="utf-8")
            )
            self.assertNotIn(
                "history_artifact_write_seconds", persisted["timings"]
            )
            self.assertGreater(
                pair["timings"]["history_artifact_write_seconds"], 0.0
            )

    def test_results_retention_keeps_results_and_removes_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            data_root = Path(temporary_directory) / "benchmark-data"
            history_dir = data_root / "repository-histories" / "history-fixture"
            pipeline = history_dir / ".pipeline"
            run_dir = pipeline / "runs" / "run-fixture"
            run_dir.mkdir(parents=True)
            positive_results = run_dir / "positive.json"
            zero_results = run_dir / "zero.json"
            positive_results.write_text('{"move_count": 1}', encoding="utf-8")
            zero_results.write_text('{"move_count": 0}', encoding="utf-8")
            (run_dir / "srcmove.xml").write_text("<unit/>", encoding="utf-8")
            (pipeline / "large.srcdiff.xml").write_text("<unit/>", encoding="utf-8")
            history = {
                "retention": "results",
                "pairs": [
                    {
                        "sequence": 0,
                        "status": "completed",
                        "metrics": {"move_count": 1},
                        "artifacts": {
                            "results_path": positive_results.relative_to(
                                data_root
                            ).as_posix()
                        },
                    },
                    {
                        "sequence": 1,
                        "status": "completed",
                        "metrics": {"move_count": 0},
                        "artifacts": {
                            "results_path": zero_results.relative_to(
                                data_root
                            ).as_posix()
                        },
                    },
                    {
                        "sequence": 2,
                        "status": "srcdiff_failed",
                        "artifacts": {"srcdiff_attempt": "discarded/attempt.json"},
                    },
                ],
            }

            finalize_history_retention(history_dir, history, data_root, pipeline)

            self.assertFalse(pipeline.exists())
            self.assertEqual(
                json.loads((history_dir / "results" / "000001.json").read_text()),
                {"move_count": 1},
            )
            self.assertEqual(
                json.loads((history_dir / "results" / "000002.json").read_text()),
                {"move_count": 0},
            )
            self.assertEqual(
                history["pairs"][0]["artifacts"]["results_path"],
                "repository-histories/history-fixture/results/000001.json",
            )
            self.assertNotIn("artifacts", history["pairs"][2])
            self.assertEqual(history["retention_summary"]["result_pairs"], 2)
            self.assertEqual(
                history["retention_summary"]["positive_evidence_pairs"], 0
            )

            browse_dir = history_dir / "moves" / "000001"
            browse_dir.mkdir(parents=True)
            (browse_dir / "srcmove.xml").symlink_to(
                pipeline / "discarded-srcmove.xml"
            )
            (browse_dir / "srcdiff.xml").symlink_to(
                pipeline / "discarded-srcdiff.xml"
            )
            refresh_history_browse_view(history_dir, history["pairs"])
            self.assertEqual(
                (browse_dir / "results.json").resolve(),
                (history_dir / "results" / "000001.json").resolve(),
            )
            self.assertFalse((browse_dir / "srcmove.xml").exists())
            self.assertFalse((browse_dir / "srcmove.xml").is_symlink())
            self.assertFalse((browse_dir / "srcdiff.xml").exists())
            self.assertFalse((browse_dir / "srcdiff.xml").is_symlink())

    def test_ephemeral_retention_removes_only_isolated_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            data_root = Path(temporary_directory) / "benchmark-data"
            history_dir = data_root / "repository-histories" / "history-fixture"
            pipeline = history_dir / ".pipeline"
            pipeline.mkdir(parents=True)
            (pipeline / "temporary.bin").write_bytes(b"temporary")
            shared = data_root / "shared-marker"
            shared.parent.mkdir(parents=True, exist_ok=True)
            shared.write_bytes(b"keep")
            history = {
                "retention": "ephemeral",
                "pairs": [
                    {
                        "sequence": 0,
                        "status": "completed",
                        "metrics": {"move_count": 1},
                        "artifacts": {"results_path": "discarded/results.json"},
                    }
                ],
            }

            finalize_history_retention(
                history_dir, history, data_root, pipeline
            )

            self.assertFalse(pipeline.exists())
            self.assertEqual(shared.read_bytes(), b"keep")
            self.assertNotIn("artifacts", history["pairs"][0])
            self.assertEqual(
                history["retention_summary"]["positive_evidence_pairs"], 0
            )

    def test_show_resolves_latest_history_and_prints_move_details(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            data_root = Path(temporary_directory) / "benchmark-data"
            history_dir = data_root / "repository-histories" / "history-fixture"
            pairs_dir = history_dir / "pairs"
            results_path = data_root / "runs" / "run-fixture" / "results.json"
            pairs_dir.mkdir(parents=True)
            results_path.parent.mkdir(parents=True)
            results_path.write_text(
                json.dumps(
                    {
                        "move_count": 1,
                        "moves": [
                            {
                                "move_id": "move-1",
                                "match_kind": "exact",
                                "from_xpaths": [
                                    "/src:unit[@filename='src/sample.c']/"
                                    "src:function[src:name='before']/diff:delete[1]"
                                ],
                                "to_xpaths": [
                                    "/src:unit[@filename='src/sample.c']/"
                                    "src:function[src:name='after']/diff:insert[1]"
                                ],
                                "from_raw_texts": ["int moved = 1;"],
                                "to_raw_texts": ["int moved = 1;"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            pair = {
                "schema_version": 1,
                "sequence": 0,
                "old_commit": "a" * 40,
                "new_commit": "b" * 40,
                "status": "completed",
                "metrics": {
                    "move_count": 1,
                    "move_group_count": 1,
                    "move_pair_count": 1,
                    "annotated_region_count": 2,
                },
                "artifacts": {
                    "results_path": results_path.relative_to(data_root).as_posix()
                },
            }
            (pairs_dir / "000001.json").write_text(
                json.dumps(pair), encoding="utf-8"
            )
            manifest = {
                "schema_version": 4,
                "history_id": "history-fixture",
                "label": "fixture-label",
                "case": "fixture",
                "status": "completed",
                "aggregates": {"move_group_count": 1, "move_pair_count": 1},
                "commits": [
                    {
                        "commit": "b" * 40,
                        "subject": "move a declaration",
                    }
                ],
                "pair_receipts": {"directory": "pairs", "count": 1},
            }
            (history_dir / "history.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )

            resolved = resolve_history_directory(data_root, None)
            loaded_history, loaded_pairs = load_history_results(resolved)
            output = StringIO()
            print_history_results(
                loaded_history, loaded_pairs, data_root, stream=output
            )

            self.assertEqual(resolved, history_dir.resolve())
            self.assertEqual(
                resolve_history_directory(data_root, "fixture-label"),
                history_dir.resolve(),
            )
            text = output.getvalue()
            self.assertIn("Pair 1/1  aaaaaaaa → bbbbbbbb", text)
            self.assertIn("exact  id=move-1", text)
            self.assertIn("From:  src/sample.c :: before", text)
            self.assertIn("To:  src/sample.c :: after", text)
            self.assertEqual(text.count("int moved = 1;"), 2)

    def test_summary_reports_moves_timings_label_and_failed_pair(self) -> None:
        pairs = [
            {
                "sequence": 0,
                "old_commit": "a" * 40,
                "new_commit": "b" * 40,
                "status": "completed",
                "metrics": {
                    "move_group_count": 3,
                    "move_pair_count": 4,
                    "annotated_region_count": 7,
                },
                "timings": {
                    "pair_seconds": 5.9,
                    "inventory_seconds": 0.1,
                    "export_seconds": 0.2,
                    "input_snapshot_seconds": 0.2,
                    "srcdiff_stage_seconds": 3.3,
                    "srcdiff_execution_seconds": 0.0,
                    "srcdiff_cached_execution_seconds": 5.5,
                    "cache_reuse_seconds": 3.5,
                    "srcmove_stage_seconds": 0.8,
                    "srcmove_execution_seconds": 0.6,
                    "other_seconds": 1.8,
                },
                "dispositions": {
                    "input_snapshot": "verified and reused",
                    "srcdiff_corpus": "verified and reused",
                    "srcmove_run": "executed",
                },
            },
            {
                "sequence": 1,
                "old_commit": "b" * 40,
                "new_commit": "c" * 40,
                "status": "srcdiff_failed",
                "error": {"message": "srcDiff timed out"},
                "timings": {
                    "pair_seconds": 2.0,
                    "srcdiff_execution_seconds": 0.5,
                    "other_seconds": 1.5,
                },
            },
        ]
        history = {
            "history_id": "history-fixture",
            "status": "completed_with_failures",
            "label": "sqlite-50-pair",
            "case": "sqlite",
            "elapsed_seconds": 7.9,
            "pairs": pairs,
            "aggregates": _aggregate(pairs),
        }
        output = StringIO()

        print_history_summary(history, Path("/tmp/history-fixture"), stream=output)

        text = output.getvalue()
        self.assertIn("Historical repository analysis: sqlite-50-pair", text)
        self.assertIn("3 groups, 4 pairs, 7 annotated regions", text)
        self.assertIn(
            "srcDiff execution 0.5s, cache reuse 3.5s, "
            "srcMove execution 0.6s, other 3.3s",
            text,
        )
        self.assertIn(
            "srcDiff execution provenance 5.5s (not included in current time)",
            text,
        )
        self.assertIn("Profile: srcDiff snapshot verify", text)
        self.assertIn("srcMove corpus verify", text)
        self.assertNotIn("repository index", text)
        self.assertIn("history artifacts", text)
        self.assertIn("2/2 bbbbbbbb → cccccccc — srcDiff timed out", text)

    def test_parallel_summary_separates_wall_time_from_summed_pair_work(self) -> None:
        pairs = [
            {
                "sequence": sequence,
                "old_commit": "a" * 40,
                "new_commit": "b" * 40,
                "status": "completed",
                "metrics": {},
                "timings": {
                    "pair_seconds": 8.0,
                    "srcdiff_execution_seconds": 5.0,
                    "cache_reuse_seconds": 0.0,
                    "srcmove_execution_seconds": 1.0,
                    "other_seconds": 2.0,
                },
            }
            for sequence in range(2)
        ]
        history = {
            "history_id": "history-parallel",
            "status": "completed",
            "case": "sqlite",
            "jobs": 2,
            "elapsed_seconds": 9.0,
            "pairs": pairs,
            "aggregates": _aggregate(pairs),
        }
        output = StringIO()

        print_history_summary(history, Path("/tmp/history-parallel"), stream=output)

        text = output.getvalue()
        self.assertIn("00:09 wall; summed pair work", text)
        self.assertIn("srcDiff execution 10.0s", text)
        self.assertIn("srcMove execution 2.0s, other 4.0s", text)
        self.assertNotIn("other -", text)

    def test_history_manifest_references_separate_pair_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            history_dir = Path(temporary_directory) / "history"
            history_dir.mkdir()
            pair = {
                "schema_version": 1,
                "sequence": 0,
                "old_commit": "a" * 40,
                "new_commit": "b" * 40,
                "status": "no_analyzable_change",
            }
            history = {
                "schema_version": 4,
                "history_id": "history-fixture",
                "status": "completed",
                "commits": [
                    {
                        "commit": "b" * 40,
                        "committer_time_iso8601": "2026-01-01T00:00:00Z",
                        "subject": "fixture",
                        "is_merge": False,
                    }
                ],
                "pairs": [pair],
            }

            write_history_artifacts(history_dir, history)

            manifest = json.loads(
                (history_dir / "history.json").read_text(encoding="utf-8")
            )
            receipt = json.loads(
                (history_dir / "pairs" / "000001.json").read_text(encoding="utf-8")
            )
            self.assertNotIn("pairs", manifest)
            self.assertEqual(manifest["pair_receipts"]["count"], 1)
            self.assertEqual(receipt, pair)

    def test_positive_pair_creates_zero_copy_browse_view_and_latest_link(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            data_root = Path(temporary_directory) / "benchmark-data"
            history_dir = (
                data_root / "repository-histories" / "history-positive-fixture"
            )
            history_dir.mkdir(parents=True)
            attempt_dir = data_root / "runs" / "run-fixture" / "attempts" / "one"
            attempt_dir.mkdir(parents=True)
            results = attempt_dir / "results.json"
            srcmove = attempt_dir / "srcmove.xml"
            attempt = attempt_dir / "attempt.json"
            results.write_text('{"move_count": 1}', encoding="utf-8")
            srcmove.write_text("<unit/>", encoding="utf-8")
            attempt.write_text("{}", encoding="utf-8")
            corpus_dir = data_root / "corpora" / "corpus-fixture"
            srcdiff = corpus_dir / "cases" / "fixture" / "input.srcdiff.xml"
            srcdiff.parent.mkdir(parents=True)
            srcdiff.write_text("<unit/>", encoding="utf-8")
            corpus_manifest = corpus_dir / "manifest.json"
            corpus_manifest.write_text(
                json.dumps(
                    {
                        "cases": [
                            {
                                "generation_status": "accepted",
                                "input_path": "cases/fixture/input.srcdiff.xml",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            pair = {
                "schema_version": 1,
                "sequence": 0,
                "old_commit": "a" * 40,
                "new_commit": "b" * 40,
                "status": "completed",
                "metrics": {"move_count": 1},
                "artifacts": {
                    "results_path": results.relative_to(data_root).as_posix(),
                    "srcmove_attempt": attempt.relative_to(data_root).as_posix(),
                    "corpus_manifest": corpus_manifest.relative_to(
                        data_root
                    ).as_posix(),
                },
            }
            history = {
                "schema_version": 4,
                "history_id": history_dir.name,
                "status": "completed",
                "commits": [
                    {
                        "commit": "b" * 40,
                        "committer_time_iso8601": "2026-01-01T00:00:00Z",
                        "subject": "fixture",
                        "is_merge": False,
                    }
                ],
                "pairs": [pair],
            }

            write_history_artifacts(history_dir, history)

            browse_dir = history_dir / "moves" / "000001"
            expected = {
                "results.json": results,
                "srcmove.xml": srcmove,
                "srcdiff.xml": srcdiff,
            }
            for name, target in expected.items():
                link = browse_dir / name
                self.assertTrue(link.is_symlink())
                self.assertEqual(link.resolve(), target.resolve())
            latest = data_root / "repository-histories" / "latest"
            self.assertTrue(latest.is_symlink())
            self.assertEqual(latest.resolve(), history_dir.resolve())

    def test_selects_requested_pairs_in_oldest_to_newest_ancestry_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = initialize_repo(Path(temporary_directory))
            commits = [
                commit_file(repo, f"int value_{index};\n", f"commit {index}")
                for index in range(5)
            ]

            resolved, selected = select_first_parent_history(repo, "HEAD", 3)

            self.assertEqual(resolved, commits[-1])
            self.assertEqual([item.commit for item in selected], commits[-4:])
            self.assertEqual([item.subject for item in selected], [
                "commit 1",
                "commit 2",
                "commit 3",
                "commit 4",
            ])

    def test_uses_ancestry_order_when_timestamps_are_not_monotonic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = initialize_repo(Path(temporary_directory))
            first = commit_file(repo, "int first;\n", "first", "2026-01-03T00:00:00Z")
            second = commit_file(repo, "int second;\n", "second", "2026-01-01T00:00:00Z")
            third = commit_file(repo, "int third;\n", "third", "2026-01-02T00:00:00Z")

            _, selected = select_first_parent_history(repo, "HEAD", 2)

            self.assertEqual([item.commit for item in selected], [first, second, third])

    def test_root_boundary_returns_fewer_pairs_than_requested(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = initialize_repo(Path(temporary_directory))
            first = commit_file(repo, "int first;\n", "first")
            second = commit_file(repo, "int second;\n", "second")

            _, selected = select_first_parent_history(repo, "HEAD", 10)

            self.assertEqual([item.commit for item in selected], [first, second])

    def test_first_parent_selection_records_merge_parents(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = initialize_repo(Path(temporary_directory))
            first = commit_file(repo, "int first;\n", "first")
            git(repo, "checkout", "-b", "topic")
            (repo / "topic.c").write_text("int topic;\n", encoding="utf-8")
            git(repo, "add", "topic.c")
            git(repo, "commit", "-m", "topic")
            git(repo, "checkout", "main")
            second = commit_file(repo, "int main;\n", "main")
            git(repo, "merge", "--no-ff", "topic", "-m", "merge topic")
            merge = git(repo, "rev-parse", "HEAD")

            _, selected = select_first_parent_history(repo, "HEAD", 2)

            self.assertEqual([item.commit for item in selected], [first, second, merge])
            self.assertEqual(len(selected[-1].parents), 2)
            self.assertTrue(selected[-1].is_merge)

    def test_rejects_invalid_count_and_single_commit_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = initialize_repo(Path(temporary_directory))
            commit_file(repo, "int first;\n", "first")
            with self.assertRaisesRegex(ValueError, "positive"):
                select_first_parent_history(repo, "HEAD", 0)
            with self.assertRaisesRegex(RuntimeError, "fewer than two"):
                select_first_parent_history(repo, "HEAD", 1)

    def test_rejects_invalid_start_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = initialize_repo(Path(temporary_directory))
            commit_file(repo, "int first;\n", "first")

            with self.assertRaisesRegex(RuntimeError, "git rev-parse"):
                select_first_parent_history(repo, "does-not-exist", 1)

    def test_rejects_shallow_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = initialize_repo(root)
            for index in range(3):
                commit_file(source, f"int value_{index};\n", f"commit {index}")
            shallow = root / "shallow"
            subprocess.run(
                [
                    "git",
                    "clone",
                    "--depth=1",
                    source.resolve().as_uri(),
                    str(shallow),
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            with self.assertRaisesRegex(RuntimeError, "non-shallow"):
                select_first_parent_history(shallow, "HEAD", 1)

    def test_changed_path_inventory_applies_directory_and_suffix_filters(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = initialize_repo(Path(temporary_directory))
            first = commit_file(repo, "int first;\n", "first")
            (repo / "src" / "sample.c").write_text("int second;\n", encoding="utf-8")
            (repo / "src" / "ignored.py").write_text("value = 1\n", encoding="utf-8")
            (repo / "outside.txt").write_text("outside\n", encoding="utf-8")
            git(repo, "add", ".")
            git(repo, "commit", "-m", "mixed")
            second = git(repo, "rev-parse", "HEAD")

            changed, analyzable = inventory_changed_paths(
                repo, first, second, "src", [".py"]
            )

            self.assertEqual(
                [change.path for change in changed],
                ["src/ignored.py", "src/sample.c"],
            )
            self.assertEqual(
                [change.path for change in analyzable], ["src/sample.c"]
            )

    def test_sparse_export_preserves_modified_added_deleted_and_renamed_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repo = initialize_repo(root)
            files = {
                "src/modified.c": "int before;\n",
                "src/deleted.c": "int deleted;\n",
                "src/renamed.c": "int renamed;\n",
                "src/ignored.py": "before = 1\n",
            }
            for relative, contents in files.items():
                path = repo / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(contents, encoding="utf-8")
            git(repo, "add", ".")
            git(repo, "commit", "-m", "old tree")
            old_commit = git(repo, "rev-parse", "HEAD")

            (repo / "src" / "modified.c").write_text("int after;\n", encoding="utf-8")
            (repo / "src" / "deleted.c").unlink()
            (repo / "src" / "added.c").write_text("int added;\n", encoding="utf-8")
            (repo / "src" / "ignored.py").write_text("after = 1\n", encoding="utf-8")
            (repo / "src" / "nested").mkdir()
            git(repo, "mv", "src/renamed.c", "src/nested/renamed.c")
            git(repo, "add", ".")
            git(repo, "commit", "-m", "new tree")
            new_commit = git(repo, "rev-parse", "HEAD")

            changed, analyzable = inventory_changed_paths(
                repo, old_commit, new_commit, "src", [".py"]
            )
            original = root / "exports" / "original"
            modified = root / "exports" / "modified"
            export_changed_files(
                repo, old_commit, new_commit, analyzable, original, modified
            )

            self.assertEqual(
                {change.status for change in changed}, {"A", "D", "M"}
            )
            self.assertEqual(
                {change.path for change in analyzable},
                {
                    "src/added.c",
                    "src/deleted.c",
                    "src/modified.c",
                    "src/nested/renamed.c",
                    "src/renamed.c",
                },
            )
            self.assertEqual(
                {
                    path.relative_to(original).as_posix()
                    for path in original.rglob("*")
                    if path.is_file()
                },
                {"src/deleted.c", "src/modified.c", "src/renamed.c"},
            )
            self.assertEqual(
                {
                    path.relative_to(modified).as_posix()
                    for path in modified.rglob("*")
                    if path.is_file()
                },
                {"src/added.c", "src/modified.c", "src/nested/renamed.c"},
            )
            self.assertEqual(
                (original / "src" / "modified.c").read_text(encoding="utf-8"),
                "int before;\n",
            )
            self.assertEqual(
                (modified / "src" / "modified.c").read_text(encoding="utf-8"),
                "int after;\n",
            )

    def test_direct_git_snapshot_matches_export_then_copy_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repo = initialize_repo(root)
            for relative, contents in {
                "src/modified.c": "int before;\n",
                "src/deleted.c": "int deleted;\n",
                "src/executable.sh": "#!/bin/sh\necho before\n",
            }.items():
                path = repo / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(contents, encoding="utf-8")
            (repo / "src" / "executable.sh").chmod(0o755)
            git(repo, "add", ".")
            git(repo, "commit", "-m", "old tree")
            old_commit = git(repo, "rev-parse", "HEAD")

            (repo / "src" / "modified.c").write_text(
                "int after;\n", encoding="utf-8"
            )
            (repo / "src" / "deleted.c").unlink()
            (repo / "src" / "added.c").write_text(
                "int added;\n", encoding="utf-8"
            )
            (repo / "src" / "executable.sh").write_text(
                "#!/bin/sh\necho after\n", encoding="utf-8"
            )
            git(repo, "add", ".")
            git(repo, "commit", "-m", "new tree")
            new_commit = git(repo, "rev-parse", "HEAD")

            _, analyzable = inventory_changed_paths(
                repo, old_commit, new_commit, "src", []
            )
            exports = root / "exports"
            export_changed_files(
                repo,
                old_commit,
                new_commit,
                analyzable,
                exports / "original",
                exports / "modified",
            )
            source = {
                "repository": "example.invalid/repository",
                "old_commit": old_commit,
                "new_commit": new_commit,
            }
            legacy_dir, legacy = create_input_snapshot(
                data_root=root / "legacy-data",
                adapter=RepositoryAdapter(
                    case_id="history-case",
                    original=exports / "original",
                    modified=exports / "modified",
                    metadata={"source": source},
                ),
                source=source,
                filter_configuration={"excluded_suffixes": []},
            )
            direct_adapter = GitRepositorySnapshotAdapter(
                case_id="history-case",
                repository=repo,
                entries=[
                    GitSnapshotEntry(
                        path=change.path,
                        old_mode=change.old_mode,
                        new_mode=change.new_mode,
                        old_blob=change.old_blob,
                        new_blob=change.new_blob,
                    )
                    for change in analyzable
                ],
                work_dir=root / "pair-work",
                metadata={"source": source},
            )
            direct_dir, direct = create_input_snapshot(
                data_root=root / "direct-data",
                adapter=direct_adapter,
                source=source,
                filter_configuration={"excluded_suffixes": []},
            )

            self.assertEqual(
                direct["input_snapshot_id"], legacy["input_snapshot_id"]
            )
            self.assertEqual(direct["identity_sha256"], legacy["identity_sha256"])
            self.assertEqual(direct["cases"], legacy["cases"])
            self.assertEqual(
                sorted(
                    (
                        path.relative_to(direct_dir).as_posix(),
                        path.read_bytes(),
                    )
                    for path in direct_dir.rglob("*")
                    if path.is_file() and path.name != "manifest.json"
                ),
                sorted(
                    (
                        path.relative_to(legacy_dir).as_posix(),
                        path.read_bytes(),
                    )
                    for path in legacy_dir.rglob("*")
                    if path.is_file() and path.name != "manifest.json"
                ),
            )
            self.assertEqual(
                (direct_dir / "sources/history-case/original/src/executable.sh")
                .stat()
                .st_mode
                & 0o777,
                0o755,
            )
            self.assertEqual(
                (direct_dir / "sources/history-case/modified/src/executable.sh")
                .stat()
                .st_mode
                & 0o777,
                0o755,
            )
            reused_dir, reused = create_input_snapshot(
                data_root=root / "direct-data",
                adapter=direct_adapter,
                source=source,
                filter_configuration={"excluded_suffixes": []},
            )
            self.assertEqual(reused_dir, direct_dir)
            self.assertEqual(reused, direct)

    def test_mode_only_change_is_not_analyzable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = initialize_repo(Path(temporary_directory))
            first = commit_file(repo, "int first;\n", "first")
            source = repo / "src" / "sample.c"
            source.chmod(0o755)
            git(repo, "add", "src/sample.c")
            git(repo, "commit", "-m", "mode only")
            second = git(repo, "rev-parse", "HEAD")

            changed, analyzable = inventory_changed_paths(
                repo, first, second, "src", []
            )

            self.assertEqual(len(changed), 1)
            self.assertFalse(changed[0].content_changed)
            self.assertEqual(analyzable, [])

    def test_sparse_export_rejects_symbolic_links(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repo = initialize_repo(root)
            old_commit = commit_file(repo, "int first;\n", "first")
            (repo / "src" / "link.c").symlink_to("sample.c")
            git(repo, "add", "src/link.c")
            git(repo, "commit", "-m", "link")
            new_commit = git(repo, "rev-parse", "HEAD")
            _, analyzable = inventory_changed_paths(
                repo, old_commit, new_commit, "src", []
            )

            with self.assertRaisesRegex(RuntimeError, "regular files"):
                export_changed_files(
                    repo,
                    old_commit,
                    new_commit,
                    analyzable,
                    root / "original",
                    root / "modified",
                )

            with self.assertRaisesRegex(
                GitSnapshotMaterializationError, "unsupported new Git object mode"
            ):
                create_input_snapshot(
                    data_root=root / "direct-data",
                    adapter=GitRepositorySnapshotAdapter(
                        case_id="symlink-case",
                        repository=repo,
                        entries=[
                            GitSnapshotEntry(
                                path=change.path,
                                old_mode=change.old_mode,
                                new_mode=change.new_mode,
                                old_blob=change.old_blob,
                                new_blob=change.new_blob,
                            )
                            for change in analyzable
                        ],
                        work_dir=root / "pair-work",
                    ),
                    source={"old_commit": old_commit, "new_commit": new_commit},
                    filter_configuration={"excluded_suffixes": []},
                )


if __name__ == "__main__":
    unittest.main()
