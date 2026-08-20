from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from repository_analysis.git import (
    retain_history,
    retained_history_ref,
    select_first_parent_history,
    verify_frozen_commits,
)


def git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def initialize(repository: Path) -> None:
    repository.mkdir()
    git(repository, "init", "--initial-branch=main")
    git(repository, "config", "user.name", "Analysis Test")
    git(repository, "config", "user.email", "analysis@example.invalid")


def commit(repository: Path, name: str, content: str) -> str:
    (repository / name).write_text(content, encoding="utf-8")
    git(repository, "add", name)
    git(repository, "commit", "-m", content.strip())
    return git(repository, "rev-parse", "HEAD")


class RepositoryAnalysisGitTests(unittest.TestCase):
    def test_first_parent_selection_is_exact_root_bounded_and_merge_aware(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory) / "repository"
            initialize(repository)
            first = commit(repository, "base.c", "first\n")
            git(repository, "checkout", "-b", "topic")
            commit(repository, "topic.c", "topic\n")
            git(repository, "checkout", "main")
            second = commit(repository, "base.c", "second\n")
            git(repository, "merge", "--no-ff", "topic", "-m", "merge")
            merge = git(repository, "rev-parse", "HEAD")

            selected = select_first_parent_history(repository, "HEAD", 10)

            self.assertEqual(selected.resolved_start, merge)
            self.assertEqual(selected.commits, (first, second, merge))

    def test_rejects_shallow_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source"
            initialize(source)
            commit(source, "one.c", "one\n")
            commit(source, "two.c", "two\n")
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

    def test_retention_ref_preserves_commits_after_branch_moves(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory) / "repository"
            initialize(repository)
            first = commit(repository, "one.c", "one\n")
            second = commit(repository, "two.c", "two\n")
            ref = retained_history_ref(b"manifest")
            retain_history(repository, ref, second)
            git(repository, "reset", "--hard", first)

            verify_frozen_commits(repository, (first, second), retained_ref=ref)
            self.assertEqual(git(repository, "rev-parse", ref), second)


if __name__ == "__main__":
    unittest.main()
