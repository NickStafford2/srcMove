from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.repositories.run_history import (
    _aggregate,
    export_changed_files,
    inventory_changed_paths,
    load_history_results,
    print_history_results,
    print_history_summary,
    resolve_history_directory,
    select_first_parent_history,
    write_history_artifacts,
)


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


if __name__ == "__main__":
    unittest.main()
