from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from repository_analysis.git import (
    first_parent_distance,
    inventory_changed_paths,
    retain_history,
    retained_history_ref,
    select_first_parent_history,
    select_older_first_parent_history,
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
    def test_inventory_excludes_symlinks_and_submodules_with_reasons(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory) / "repository"
            initialize(repository)
            old_commit = commit(repository, "source.cpp", "old\n")
            (repository / "source.cpp").write_text("new\n", encoding="utf-8")
            (repository / "linked.cpp").symlink_to("source.cpp")
            git(repository, "add", "source.cpp", "linked.cpp")
            git(
                repository,
                "update-index",
                "--add",
                "--cacheinfo",
                f"160000,{old_commit},vendor/module",
            )
            git(repository, "commit", "-m", "mixed regular and special paths")
            new_commit = git(repository, "rev-parse", "HEAD")

            changed, analyzable = inventory_changed_paths(
                repository, old_commit, new_commit, None, ()
            )

            by_path = {change.path: change for change in changed}
            self.assertEqual(
                by_path["linked.cpp"].exclusion_reasons,
                ("unsupported_git_mode: symlink",),
            )
            self.assertEqual(
                by_path["vendor/module"].exclusion_reasons,
                ("unsupported_git_mode: submodule",),
            )
            self.assertEqual(
                [change.path for change in analyzable], ["source.cpp"]
            )

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
            self.assertTrue(selected.history_exhausted)

            bounded = select_older_first_parent_history(
                repository, "HEAD", pair_count=1
            )
            self.assertEqual(bounded.commits, (second, merge))
            self.assertFalse(bounded.history_exhausted)

            through = select_older_first_parent_history(
                repository, "HEAD", through=second
            )
            self.assertEqual(through.commits, (second, merge))
            self.assertFalse(through.history_exhausted)

            root_frontier = select_older_first_parent_history(
                repository, first, pair_count=25
            )
            self.assertEqual(root_frontier.commits, (first,))
            self.assertTrue(root_frontier.history_exhausted)

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

    def test_first_parent_distance_rejects_a_side_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory) / "repository"
            initialize(repository)
            first = commit(repository, "one.c", "one\n")
            git(repository, "checkout", "-b", "side")
            side = commit(repository, "side.c", "side\n")
            git(repository, "checkout", "main")
            second = commit(repository, "two.c", "two\n")
            git(repository, "merge", "--no-ff", "side", "-m", "merge")
            newest = git(repository, "rev-parse", "HEAD")

            self.assertEqual(first_parent_distance(repository, newest, first), 2)
            self.assertEqual(first_parent_distance(repository, newest, second), 1)
            with self.assertRaisesRegex(ValueError, "not on.*first-parent"):
                first_parent_distance(repository, newest, side)


if __name__ == "__main__":
    unittest.main()
