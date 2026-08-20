from __future__ import annotations

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from repository_analysis.cli import _render_pair, build_parser, main
from repository_analysis.locking import AnalysisOperationLock
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
    def test_run_status_list_and_show_use_one_idempotent_interface(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository = self._history(root, 5)
            analysis = root / "analysis"
            common = [
                str(analysis),
                "--pairs",
                "2",
                "--format",
                "json",
            ]
            creation = [
                *common,
                "--repository",
                str(repository),
                "--name",
                "fixture-repository",
                "--srcdiff",
                str(executable(root / "srcdiff")),
                "--srcmove",
                str(executable(root / "srcmove")),
                "--exclude-suffix",
                ".txt",
            ]

            status, output, error = self._main(["run", *creation])
            self.assertEqual((status, error), (0, ""))
            self.assertEqual(json.loads(output)["coverage"]["durable"], 2)

            with patch.object(
                PairExecutor,
                "open_worker",
                side_effect=AssertionError("idempotent CLI retry opened a worker"),
            ):
                repeated, output, error = self._main(["run", *common])
            self.assertEqual((repeated, error), (0, ""))
            self.assertEqual(json.loads(output)["coverage"]["durable"], 2)

            status, output, error = self._main(
                ["status", str(analysis), "--format", "json"]
            )
            self.assertEqual((status, error), (0, ""))
            report = json.loads(output)
            self.assertEqual(report["coverage"]["committed"], 2)
            self.assertIsNone(report["pending"])
            self.assertEqual(report["invocation"]["target_kind"], "pairs")
            self.assertEqual(report["invocation"]["target_value"], 2)
            self.assertEqual(report["invocation"]["result"], "target_reached")
            self.assertEqual(report["state"], "target_reached")

            status, output, error = self._main(
                [
                    "show",
                    str(analysis),
                    "1",
                    "--format",
                    "json",
                ]
            )
            self.assertEqual((status, error), (0, ""))
            details = json.loads(output)["pair"]
            self.assertEqual(details["distance_from_newest"], 0)
            self.assertEqual(details["status"], "no_analyzable_change")

            status, output, error = self._main(
                ["list", str(analysis), "--format", "json"]
            )
            self.assertEqual((status, error), (0, ""))
            self.assertEqual(len(json.loads(output)["pairs"]["items"]), 2)

            status, output, error = self._main(["status", str(analysis)])
            self.assertEqual((status, error), (0, ""))
            self.assertIn("2/2 pairs (100%)", output)
            self.assertIn("2 skipped", output)

            with AnalysisOperationLock(analysis, command="background-run"):
                status, output, error = self._main(
                    ["status", str(analysis), "--format", "json"]
                )
                self.assertEqual((status, error), (0, ""))
                self.assertEqual(json.loads(output)["state"], "running")

            for ordering in ([], ["--oldest-first"]):
                status, output, error = self._main(
                    [
                        "list",
                        str(analysis),
                        "--limit",
                        "1",
                        "--format",
                        "json",
                        *ordering,
                    ]
                )
                self.assertEqual((status, error), (0, ""))
                first = json.loads(output)
                first_number = first["pairs"]["items"][0]["number"]
                next_after = first["pairs"]["next_after"]
                self.assertIsNotNone(next_after)

                status, output, error = self._main(
                    [
                        "list",
                        str(analysis),
                        "--limit",
                        "1",
                        "--after",
                        str(next_after),
                        "--format",
                        "json",
                        *ordering,
                    ]
                )
                self.assertEqual((status, error), (0, ""))
                second = json.loads(output)
                self.assertNotEqual(
                    first_number, second["pairs"]["items"][0]["number"]
                )

    def test_human_show_hides_diagnostic_move_evidence(self) -> None:
        output = _render_pair(
            {
                "number": 9,
                "status": "completed",
                "old_commit": "a" * 40,
                "new_commit": "b" * 40,
                "analyzable_path_count": 1,
                "changed_path_count": 1,
                "timings": {"pair_seconds": 1.25},
                "moves": [
                    {
                        "match_kind": "exact",
                        "from_xpaths": ["/secret/source"],
                        "to_xpaths": ["/secret/destination"],
                        "from_text_digests": [{"sha256": "c" * 64}],
                    }
                ],
            }
        )

        self.assertIn("1. exact · 1 source region → 1 destination region", output)
        self.assertNotIn("/secret", output)
        self.assertNotIn("sha256", output)

    def test_target_options_are_mutually_exclusive_and_required(self) -> None:
        parser = build_parser()
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                parser.parse_args(["run", "analysis"])
            with self.assertRaises(SystemExit):
                parser.parse_args(
                    [
                        "run",
                        "analysis",
                        "--pairs",
                        "2",
                        "--all",
                    ]
                )

    def test_missing_creation_inputs_do_not_create_partial_database(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            analysis = Path(temporary_directory) / "analysis"

            status, _, error = self._main(
                [
                    "run",
                    str(analysis),
                    "--pairs",
                    "2",
                ]
            )

            self.assertEqual(status, 2)
            self.assertIn("new analysis requires", error)
            self.assertFalse((analysis / "analysis.sqlite3").exists())

    def test_frozen_configuration_cannot_be_overridden(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository = self._history(root, 3)
            analysis = root / "analysis"
            arguments = [
                "run",
                str(analysis),
                "--pairs",
                "1",
                "--repository",
                str(repository),
                "--name",
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
                    "run",
                    str(analysis),
                    "--pairs",
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
                    "run",
                    str(analysis),
                    "--pairs",
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
                ["status", str(missing)]
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
