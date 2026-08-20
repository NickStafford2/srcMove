from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from repository_analysis.analysis import AnalysisTarget, analyze_repository
from repository_analysis.cli import _render_pair, build_parser, main
from repository_analysis.configuration import (
    load_history_configuration,
    render_history_configuration,
)
from repository_analysis.locking import AnalysisOperationLock
from repository_analysis.inputs import AnalysisConfiguration, RepositoryIdentity
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
            analysis = repository / ".srcmove"
            self._init(repository, excluded_suffixes=(".py", ".txt"))
            common = [
                "--pairs",
                "2",
                "--format",
                "json",
            ]
            creation = [
                *common,
                "--name",
                "fixture-repository",
                "--srcdiff",
                str(executable(root / "srcdiff")),
                "--srcmove",
                str(executable(root / "srcmove")),
            ]

            status, output, error = self._main(["-C", str(repository), "run", *creation])
            self.assertEqual((status, error), (0, ""))
            self.assertEqual(json.loads(output)["coverage"]["durable"], 2)

            with patch.object(
                PairExecutor,
                "open_worker",
                side_effect=AssertionError("idempotent CLI retry opened a worker"),
            ):
                repeated, output, error = self._main(
                    ["-C", str(repository), "run", *common]
                )
            self.assertEqual((repeated, error), (0, ""))
            self.assertEqual(json.loads(output)["coverage"]["durable"], 2)

            status, output, error = self._main(
                ["-C", str(repository), "status", "--format", "json"]
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
                    "-C",
                    str(repository),
                    "show",
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
                ["-C", str(repository), "list", "--format", "json"]
            )
            self.assertEqual((status, error), (0, ""))
            self.assertEqual(len(json.loads(output)["pairs"]["items"]), 2)

            status, output, error = self._main(["-C", str(repository), "status"])
            self.assertEqual((status, error), (0, ""))
            self.assertIn("2/2 pairs (100%)", output)
            self.assertIn("2 skipped", output)

            with AnalysisOperationLock(analysis, command="background-run"):
                status, output, error = self._main(
                    ["-C", str(repository), "status", "--format", "json"]
                )
                self.assertEqual((status, error), (0, ""))
                self.assertEqual(json.loads(output)["state"], "running")

            for ordering in ([], ["--oldest-first"]):
                status, output, error = self._main(
                    [
                        "-C",
                        str(repository),
                        "list",
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
                        "-C",
                        str(repository),
                        "list",
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
                parser.parse_args(["run"])
            with self.assertRaises(SystemExit):
                parser.parse_args(
                    [
                        "run",
                        "--pairs",
                        "2",
                        "--all",
                    ]
                )

    def test_missing_creation_inputs_do_not_create_partial_database(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)

            status, _, error = self._main(
                [
                    "-C",
                    str(root),
                    "run",
                    "--pairs",
                    "2",
                ]
            )

            self.assertEqual(status, 2)
            self.assertIn("not inside a Git worktree", error)
            self.assertFalse((root / ".srcmove" / "analysis.sqlite3").exists())

    def test_frozen_configuration_cannot_be_overridden(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository = self._history(root, 3)
            analysis = repository / ".srcmove"
            self._init(repository, excluded_suffixes=(".py", ".txt"))
            arguments = [
                "-C",
                str(repository),
                "run",
                "--pairs",
                "1",
                "--name",
                "fixture-repository",
                "--srcdiff",
                str(executable(root / "srcdiff")),
                "--srcmove",
                str(executable(root / "srcmove")),
            ]
            self.assertEqual(self._main(arguments)[0], 0)

            before = json.loads(
                self._main(
                    ["-C", str(repository), "status", "--format", "json"]
                )[1]
            )["invocation"]["invocation_id"]
            configuration = load_history_configuration(analysis)
            analysis_settings = replace(
                configuration.analysis,
                selected_directory="repository_analysis",
            )
            (analysis / "config.toml").write_text(
                render_history_configuration(
                    replace(configuration, analysis=analysis_settings)
                ),
                encoding="utf-8",
            )
            status, _, error = self._main(
                ["-C", str(repository), "run", "--pairs", "2"]
            )
            self.assertEqual(status, 2)
            self.assertIn("configuration drift", error)
            after = json.loads(
                self._main(
                    ["-C", str(repository), "status", "--format", "json"]
                )[1]
            )["invocation"]["invocation_id"]
            self.assertEqual(after, before)

    def test_run_recovers_interrupted_initial_database_publication(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository = self._history(root, 3)
            analysis = repository / ".srcmove"
            self._init(repository, excluded_suffixes=(".py", ".txt"))
            creation = [
                "-C",
                str(repository),
                "run",
                "--pairs",
                "1",
                "--srcdiff",
                str(executable(root / "srcdiff")),
                "--srcmove",
                str(executable(root / "srcmove")),
            ]
            self.assertEqual(self._main(creation)[0], 0)
            interrupted = analysis / ".analysis.sqlite3.tmp-interrupted"
            os.link(analysis / "analysis.sqlite3", interrupted)

            status, _, error = self._main(
                [
                    "-C",
                    str(repository),
                    "run",
                    "--pairs",
                    "1",
                    "--progress",
                    "never",
                ]
            )

            self.assertEqual((status, error), (0, ""))
            self.assertFalse(interrupted.exists())

    def test_legacy_state_is_rejected_instead_of_mixed_with_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository = self._history(root, 2)
            analysis = repository / ".srcmove"
            analysis.mkdir()
            (analysis / "current.json").write_text("{}", encoding="utf-8")
            self.assertEqual(self._main(["-C", str(repository), "init"])[0], 0)

            status, _, error = self._main(
                [
                    "-C",
                    str(repository),
                    "run",
                    "--pairs",
                    "1",
                    "--srcdiff",
                    str(executable(root / "srcdiff")),
                    "--srcmove",
                    str(executable(root / "srcmove")),
                ]
            )

            self.assertEqual(status, 2)
            self.assertIn("unsupported legacy state", error)
            self.assertFalse((analysis / "analysis.sqlite3").exists())

    def test_status_typo_does_not_create_an_analysis_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = self._history(Path(temporary_directory), 2)

            status, _, error = self._main(
                ["-C", str(repository), "status"]
            )

            self.assertEqual(status, 2)
            self.assertIn("not an owned directory", error)
            self.assertFalse((repository / ".srcmove").exists())

    def test_nested_directory_discovers_repository_local_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository = self._history(root, 3)
            nested = repository / "src" / "nested"
            nested.mkdir(parents=True)
            self._init(repository, excluded_suffixes=(".py", ".txt"))

            status, output, error = self._main(
                [
                    "-C",
                    str(nested),
                    "run",
                    "--pairs",
                    "1",
                    "--format",
                    "json",
                    "--srcdiff",
                    str(executable(root / "srcdiff")),
                    "--srcmove",
                    str(executable(root / "srcmove")),
                ]
            )

            self.assertEqual((status, error), (0, ""))
            self.assertEqual(json.loads(output)["analysis"]["name"], "repository")
            self.assertTrue((repository / ".srcmove" / "analysis.sqlite3").is_file())

    def test_renamed_state_is_inert_but_explicitly_queryable_and_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository = self._history(root, 3)
            self._init(repository, excluded_suffixes=(".py", ".txt"))
            creation = [
                "-C",
                str(repository),
                "run",
                "--pairs",
                "1",
                "--srcdiff",
                str(executable(root / "srcdiff")),
                "--srcmove",
                str(executable(root / "srcmove")),
            ]
            self.assertEqual(self._main(creation)[0], 0)
            active = repository / ".srcmove"
            self.assertEqual((active / ".gitignore").read_text(), "*\n")
            self.assertEqual(git(repository, "status", "--short", "--untracked-files=all"), "")

            archived = repository / ".srcmoveOld"
            active.rename(archived)
            self.assertEqual(git(repository, "status", "--short", "--untracked-files=all"), "")
            self.assertEqual(self._main(["-C", str(repository), "status"])[0], 2)
            status, output, error = self._main(
                [
                    "-C",
                    str(repository),
                    "--state-dir",
                    ".srcmoveOld",
                    "status",
                    "--format",
                    "json",
                ]
            )
            self.assertEqual((status, error), (0, ""))
            self.assertEqual(json.loads(output)["coverage"]["durable"], 1)

    def test_analysis_extends_after_repository_is_moved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository = self._history(root, 4)
            self._init(repository, excluded_suffixes=(".py", ".txt"))
            creation = [
                "-C",
                str(repository),
                "run",
                "--pairs",
                "1",
                "--format",
                "json",
                "--srcdiff",
                str(executable(root / "srcdiff")),
                "--srcmove",
                str(executable(root / "srcmove")),
            ]
            self.assertEqual(self._main(creation)[0], 0)

            moved = root / "moved-repository"
            repository.rename(moved)
            status, output, error = self._main(
                [
                    "-C",
                    str(moved),
                    "run",
                    "--pairs",
                    "2",
                    "--format",
                    "json",
                ]
            )

            self.assertEqual((status, error), (0, ""))
            self.assertEqual(json.loads(output)["coverage"]["durable"], 2)

    def test_no_op_run_verifies_frozen_executable_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository = self._history(root, 3)
            self._init(repository, excluded_suffixes=(".py", ".txt"))
            creation = [
                "-C",
                str(repository),
                "run",
                "--pairs",
                "1",
                "--srcdiff",
                str(executable(root / "srcdiff")),
                "--srcmove",
                str(executable(root / "srcmove")),
            ]
            self.assertEqual(self._main(creation)[0], 0)
            admitted = next((repository / ".srcmove" / "tools").glob("*/srcmove"))
            admitted.chmod(0o700)
            admitted.write_bytes(b"changed")

            status, _, error = self._main(
                ["-C", str(repository), "run", "--pairs", "1"]
            )

            self.assertEqual(status, 2)
            self.assertIn("analysis-owned srcMove executable drift", error)

    def test_python_changes_are_skipped_by_default_and_can_be_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository = self._history(root, 2, filename="fixture.py")
            self._init(repository)
            base = [
                "-C",
                str(repository),
                "run",
                "--pairs",
                "1",
                "--format",
                "json",
                "--srcdiff",
                str(executable(root / "srcdiff")),
                "--srcmove",
                str(executable(root / "srcmove")),
            ]

            status, output, error = self._main(base)
            self.assertEqual((status, error), (0, ""))
            self.assertEqual(json.loads(output)["outcomes"]["skipped"], 1)

            (repository / ".srcmove").rename(repository / ".srcmove-default")
            self._init(repository, excluded_suffixes=())
            status, output, error = self._main(base)
            self.assertEqual(status, 1)
            self.assertEqual(error, "")
            self.assertEqual(
                json.loads(output)["outcomes"]["by_status"]["srcdiff_failed"], 1
            )

    def test_run_requires_init_and_init_does_not_create_database(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository = self._history(root, 2)

            status, _, error = self._main(
                ["-C", str(repository), "run", "--pairs", "1"]
            )
            self.assertEqual(status, 2)
            self.assertIn("run srcmove-history init first", error)
            self.assertFalse((repository / ".srcmove").exists())

            status, output, error = self._main(["-C", str(repository), "init"])
            self.assertEqual((status, error), (0, ""))
            self.assertIn("Initialized repository analysis", output)
            self.assertTrue((repository / ".srcmove" / "config.toml").is_file())
            self.assertEqual(
                load_history_configuration(repository / ".srcmove")
                .analysis.excluded_suffixes,
                (".py",),
            )
            self.assertFalse(
                (repository / ".srcmove" / "analysis.sqlite3").exists()
            )
            before = (repository / ".srcmove" / "config.toml").read_bytes()
            status, output, error = self._main(["-C", str(repository), "init"])
            self.assertEqual((status, error), (0, ""))
            self.assertIn("Already initialized", output)
            self.assertEqual(
                (repository / ".srcmove" / "config.toml").read_bytes(), before
            )

    def test_mutable_jobs_setting_applies_after_first_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository = self._history(root, 3)
            self._init(repository, excluded_suffixes=(".py", ".txt"))
            creation = [
                "-C",
                str(repository),
                "run",
                "--pairs",
                "1",
                "--srcdiff",
                str(executable(root / "srcdiff")),
                "--srcmove",
                str(executable(root / "srcmove")),
            ]
            self.assertEqual(self._main(creation)[0], 0)
            analysis = repository / ".srcmove"
            configuration = load_history_configuration(analysis)
            (analysis / "config.toml").write_text(
                render_history_configuration(replace(configuration, jobs=5)),
                encoding="utf-8",
            )

            self.assertEqual(
                self._main(
                    [
                        "-C",
                        str(repository),
                        "run",
                        "--pairs",
                        "1",
                        "--jobs",
                        "2",
                    ]
                )[0],
                0,
            )
            report = json.loads(
                self._main(
                    ["-C", str(repository), "status", "--format", "json"]
                )[1]
            )
            self.assertEqual(report["invocation"]["jobs"], 2)
            self.assertEqual(
                self._main(
                    ["-C", str(repository), "run", "--pairs", "1"]
                )[0],
                0,
            )
            report = json.loads(
                self._main(
                    ["-C", str(repository), "status", "--format", "json"]
                )[1]
            )
            self.assertEqual(report["invocation"]["jobs"], 5)

    def test_init_backfills_configuration_for_existing_database(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository = self._history(root, 3)
            analysis = repository / ".srcmove"
            frozen = AnalysisConfiguration(excluded_suffixes=(".txt",))
            analyze_repository(
                analysis_root=analysis,
                target=AnalysisTarget("total_pairs", 1),
                jobs=3,
                repository=repository,
                repository_identity=RepositoryIdentity("fixture"),
                configuration=frozen,
                srcdiff_path=executable(root / "srcdiff"),
                srcmove_path=executable(root / "srcmove"),
            )
            self.assertFalse((analysis / "config.toml").exists())

            status, _, error = self._main(["-C", str(repository), "init"])

            self.assertEqual((status, error), (0, ""))
            backfilled = load_history_configuration(analysis)
            self.assertEqual(backfilled.analysis, frozen)
            self.assertEqual(backfilled.jobs, 3)

    def _history(
        self, root: Path, count: int, *, filename: str = "fixture.txt"
    ) -> Path:
        repository = root / "repository"
        repository.mkdir()
        git(repository, "init", "--initial-branch=main")
        git(repository, "config", "user.name", "CLI Test")
        git(repository, "config", "user.email", "cli@example.invalid")
        for index in range(count):
            (repository / filename).write_text(
                f"commit-{index}", encoding="utf-8"
            )
            git(repository, "add", filename)
            git(repository, "commit", "-m", f"commit-{index}")
        return repository

    def _init(
        self,
        repository: Path,
        *,
        excluded_suffixes: tuple[str, ...] | None = None,
    ) -> None:
        status, _, error = self._main(["-C", str(repository), "init"])
        self.assertEqual((status, error), (0, ""))
        if excluded_suffixes is None:
            return
        analysis = repository / ".srcmove"
        configuration = load_history_configuration(analysis)
        updated = replace(
            configuration,
            analysis=replace(
                configuration.analysis,
                excluded_suffixes=excluded_suffixes,
            ),
        )
        (analysis / "config.toml").write_text(
            render_history_configuration(updated), encoding="utf-8"
        )

    def _main(self, arguments: list[str]) -> tuple[int, str, str]:
        output = io.StringIO()
        error = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            status = main(arguments)
        return status, output.getvalue().strip(), error.getvalue()


if __name__ == "__main__":
    unittest.main()
