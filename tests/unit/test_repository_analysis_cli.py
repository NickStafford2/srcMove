from __future__ import annotations

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from repository_analysis.cli import build_parser, main
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


class RepositoryAnalysisCliTests(unittest.TestCase):
    def test_analyze_and_status_use_one_idempotent_public_interface(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository = self._history(root, 5)
            analysis = root / "analysis"
            common = [
                "--analysis-root",
                str(analysis),
                "--total-pairs",
                "2",
            ]
            creation = [
                *common,
                "--repository",
                str(repository),
                "--repository-id",
                "fixture-repository",
                "--srcdiff",
                str(executable(root / "srcdiff")),
                "--srcmove",
                str(executable(root / "srcmove")),
                "--exclude-suffix",
                ".txt",
            ]

            status, output, error = self._main(["analyze", *creation])
            self.assertEqual((status, error), (0, ""))
            self.assertEqual(json.loads(output)["completed_pair_count"], 2)

            with patch.object(
                PairExecutor,
                "open_worker",
                side_effect=AssertionError("idempotent CLI retry opened a worker"),
            ):
                repeated, output, error = self._main(["analyze", *common])
            self.assertEqual((repeated, error), (0, ""))
            self.assertEqual(json.loads(output)["completed_pair_count"], 2)

            status, output, error = self._main(
                ["status", "--analysis-root", str(analysis)]
            )
            self.assertEqual((status, error), (0, ""))
            report = json.loads(output)
            self.assertEqual(report["completed_pair_count"], 2)
            self.assertIsNone(report["pending"])
            self.assertEqual(report["invocation"]["target_kind"], "total_pairs")
            self.assertEqual(report["invocation"]["target_value"], "2")
            self.assertEqual(report["invocation"]["result"], "target_reached")

            status, output, error = self._main(
                [
                    "inspect",
                    "--analysis-root",
                    str(analysis),
                    "--distance-from-newest",
                    "0",
                ]
            )
            self.assertEqual((status, error), (0, ""))
            details = json.loads(output)
            self.assertEqual(details["distance_from_newest"], 0)
            self.assertEqual(details["status"], "no_analyzable_change")

    def test_target_options_are_mutually_exclusive_and_required(self) -> None:
        parser = build_parser()
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                parser.parse_args(["analyze", "--analysis-root", "analysis"])
            with self.assertRaises(SystemExit):
                parser.parse_args(
                    [
                        "analyze",
                        "--analysis-root",
                        "analysis",
                        "--total-pairs",
                        "2",
                        "--all",
                    ]
                )

    def test_new_analysis_reports_missing_creation_inputs_without_partial_database(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            analysis = Path(temporary_directory) / "analysis"

            status, _, error = self._main(
                [
                    "analyze",
                    "--analysis-root",
                    str(analysis),
                    "--total-pairs",
                    "2",
                ]
            )

            self.assertEqual(status, 2)
            self.assertIn("new analysis requires", error)
            self.assertFalse((analysis / "analysis.sqlite3").exists())

    def test_frozen_configuration_cannot_be_overridden_on_existing_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository = self._history(root, 3)
            analysis = root / "analysis"
            arguments = [
                "analyze",
                "--analysis-root",
                str(analysis),
                "--total-pairs",
                "1",
                "--repository",
                str(repository),
                "--repository-id",
                "fixture-repository",
                "--srcdiff",
                str(executable(root / "srcdiff")),
                "--srcmove",
                str(executable(root / "srcmove")),
                "--exclude-suffix",
                ".txt",
            ]
            self.assertEqual(self._main(arguments)[0], 0)

            status, _, error = self._main(
                [
                    "analyze",
                    "--analysis-root",
                    str(analysis),
                    "--total-pairs",
                    "2",
                    "--directory",
                    "repository_analysis",
                ]
            )
            self.assertEqual(status, 2)
            self.assertIn("configuration drift", error)

    def test_legacy_state_is_rejected_instead_of_mixed_with_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            analysis = root / "analysis"
            analysis.mkdir()
            (analysis / "current.json").write_text("{}", encoding="utf-8")

            status, _, error = self._main(
                [
                    "analyze",
                    "--analysis-root",
                    str(analysis),
                    "--total-pairs",
                    "1",
                ]
            )

            self.assertEqual(status, 2)
            self.assertIn("unsupported legacy state", error)
            self.assertFalse((analysis / "analysis.sqlite3").exists())

    def test_status_typo_does_not_create_an_analysis_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            missing = Path(temporary_directory) / "missing"

            status, _, error = self._main(
                ["status", "--analysis-root", str(missing)]
            )

            self.assertEqual(status, 2)
            self.assertIn("not an owned directory", error)
            self.assertFalse(missing.exists())

    def _history(self, root: Path, count: int) -> Path:
        repository = root / "repository"
        repository.mkdir()
        git(repository, "init", "--initial-branch=main")
        git(repository, "config", "user.name", "CLI Test")
        git(repository, "config", "user.email", "cli@example.invalid")
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
        return status, output.getvalue().strip(), error.getvalue()


if __name__ == "__main__":
    unittest.main()
