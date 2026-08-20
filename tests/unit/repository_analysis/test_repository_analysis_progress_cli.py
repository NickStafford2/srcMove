from __future__ import annotations

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from repository_analysis.cli import main
from repository_analysis.configuration import (
    load_history_configuration,
    render_history_configuration,
)
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


class RepositoryAnalysisProgressCliTests(unittest.TestCase):
    def test_human_run_reports_immediate_sparse_redirected_progress(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            arguments = self._creation_arguments(root, pairs=4)

            status, output, error = self._main(arguments)

            self.assertEqual(status, 0)
            self.assertIn("4/4 pairs", output)
            lines = error.splitlines()
            self.assertGreaterEqual(len(lines), 2)
            self.assertIn("preparing", lines[0])
            self.assertTrue(any("0/4" in line for line in lines))
            self.assertTrue(any("4/4" in line for line in lines[1:]))
            self.assertLessEqual(len(lines), 4)

    def test_json_auto_suppresses_progress_and_keeps_stdout_valid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            arguments = self._creation_arguments(root, pairs=2)

            status, output, error = self._main(
                [*arguments, "--format", "json"]
            )

            self.assertEqual(status, 0)
            self.assertEqual(error, "")
            document = json.loads(output)
            self.assertEqual(document["coverage"]["durable"], 2)

    def test_progress_always_uses_stderr_without_contaminating_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            arguments = self._creation_arguments(root, pairs=2)

            status, output, error = self._main(
                [
                    *arguments,
                    "--format",
                    "json",
                    "--progress",
                    "always",
                ]
            )

            self.assertEqual(status, 0)
            self.assertEqual(json.loads(output)["coverage"]["durable"], 2)
            self.assertIn("0/2", error)
            self.assertIn("2/2", error)
            self.assertNotIn(error, output)

    def test_progress_never_suppresses_human_run_progress(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            arguments = self._creation_arguments(root, pairs=2)

            status, output, error = self._main(
                [*arguments, "--progress", "never"]
            )

            self.assertEqual(status, 0)
            self.assertIn("2/2 pairs", output)
            self.assertEqual(error, "")

    def test_no_op_run_finishes_cleanly_without_opening_workers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            creation = self._creation_arguments(root, pairs=2)
            self.assertEqual(
                self._main([*creation, "--progress", "never"])[0], 0
            )

            with patch.object(
                PairExecutor,
                "open_worker",
                side_effect=AssertionError("no-op run opened a worker"),
            ):
                status, output, error = self._main(
                    [
                        "-C",
                        str(root / "repository"),
                        "run",
                        "--pairs",
                        "2",
                        "--progress",
                        "always",
                    ]
                )

            self.assertEqual(status, 0)
            self.assertIn("2/2 pairs", output)
            self.assertIn("2/2", error)
            self.assertNotIn("error", error.lower())

    def test_keyboard_interrupt_renders_one_non_failure_message(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            arguments = self._creation_arguments(
                Path(temporary_directory), pairs=1
            )
            with patch(
                "repository_analysis.cli.analyze_repository",
                side_effect=KeyboardInterrupt,
            ):
                status, output, error = self._main(arguments)

        self.assertEqual(status, 130)
        self.assertEqual(output, "")
        self.assertEqual(error.lower().count("interrupted"), 1)
        self.assertNotIn("failed", error.lower())

    def _creation_arguments(self, root: Path, *, pairs: int) -> list[str]:
        repository = self._history(root, pairs + 1)
        self.assertEqual(self._main(["-C", str(repository), "init"])[0], 0)
        analysis = repository / ".srcmove"
        configuration = load_history_configuration(analysis)
        configuration = replace(
            configuration,
            analysis=replace(
                configuration.analysis,
                excluded_suffixes=(".py", ".txt"),
            ),
            jobs=2,
        )
        (analysis / "config.toml").write_text(
            render_history_configuration(configuration), encoding="utf-8"
        )
        return [
            "-C",
            str(repository),
            "run",
            "--pairs",
            str(pairs),
            "--name",
            "progress-fixture",
            "--srcdiff",
            str(executable(root / "srcdiff")),
            "--srcmove",
            str(executable(root / "srcmove")),
        ]

    def _history(self, root: Path, count: int) -> Path:
        repository = root / "repository"
        repository.mkdir()
        git(repository, "init", "--initial-branch=main")
        git(repository, "config", "user.name", "Progress CLI Test")
        git(repository, "config", "user.email", "progress@example.invalid")
        for index in range(count):
            (repository / "fixture.txt").write_text(
                f"commit-{index}", encoding="utf-8"
            )
            git(repository, "add", "fixture.txt")
            git(repository, "commit", "-m", f"commit-{index}")
        return repository

    def _main(self, arguments: list[str]) -> tuple[int, str, str]:
        output = io.StringIO()
        error = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            status = main(arguments)
        return status, output.getvalue().strip(), error.getvalue().strip()


if __name__ == "__main__":
    unittest.main()
