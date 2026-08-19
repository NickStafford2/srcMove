from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.repositories.run_history import (
    inventory_changed_paths,
    select_first_parent_history,
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

            self.assertEqual(changed, ["src/ignored.py", "src/sample.c"])
            self.assertEqual(analyzable, ["src/sample.c"])


if __name__ == "__main__":
    unittest.main()
