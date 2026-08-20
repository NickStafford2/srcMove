from __future__ import annotations

import contextlib
import csv
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from repository_analysis.chain import load_verified_analysis_state
from repository_analysis.cli import main
from repository_analysis.worker import PairExecutor


def git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def executable(path: Path, content: bytes = b"#!/bin/sh\nexit 99\n") -> Path:
    path.write_bytes(content)
    path.chmod(0o755)
    return path


class RepositoryAnalysisCliTests(unittest.TestCase):
    def test_continue_older_expands_one_transactional_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository = root / "repository"
            repository.mkdir()
            git(repository, "init", "--initial-branch=main")
            git(repository, "config", "user.name", "CLI Test")
            git(repository, "config", "user.email", "cli@example.invalid")
            commits = tuple(
                self._commit(repository, f"commit-{index}") for index in range(7)
            )
            srcdiff = executable(root / "srcdiff")
            srcmove = executable(root / "srcmove")
            analysis = root / "analysis"

            self.assertEqual(
                self._main(
                    [
                        "start",
                        "--repository",
                        str(repository),
                        "--repository-id",
                        "fixture-repository",
                        "--analysis-root",
                        str(analysis),
                        "--count",
                        "2",
                        "--srcdiff",
                        str(srcdiff),
                        "--srcmove",
                        str(srcmove),
                        "--exclude-suffix",
                        ".txt",
                    ]
                ),
                0,
            )
            initial_receipts = {
                path.name: path.read_bytes()
                for path in (analysis / "pairs").glob("*.json")
            }
            self.assertEqual(
                self._main(
                    [
                        "continue-older",
                        "--analysis-root",
                        str(analysis),
                        "--count",
                        "2",
                        "--jobs",
                        "2",
                    ]
                ),
                0,
            )
            self.assertEqual(
                self._main(
                    [
                        "continue-older",
                        "--analysis-root",
                        str(analysis),
                        "--count",
                        "2",
                    ]
                ),
                0,
            )

            newer_manifest = json.loads((analysis / "manifest.json").read_text())
            older_manifest = json.loads(
                (analysis / "segments" / "000001" / "manifest.json").read_text()
            )
            oldest_manifest = json.loads(
                (analysis / "segments" / "000002" / "manifest.json").read_text()
            )
            self.assertEqual(newer_manifest["commits"], list(commits[4:]))
            self.assertEqual(older_manifest["commits"], list(commits[2:5]))
            self.assertEqual(oldest_manifest["commits"], list(commits[:3]))
            self.assertIsNone(newer_manifest["continuation"])
            self.assertEqual(
                older_manifest["continuation"]["boundary_commit"], commits[4]
            )
            self.assertEqual(
                older_manifest["continuation"]["newer_segment_path"], "."
            )
            self.assertEqual(
                oldest_manifest["continuation"]["boundary_commit"], commits[2]
            )
            self.assertEqual(
                oldest_manifest["continuation"]["newer_segment_path"],
                "segments/000001",
            )

            state = json.loads((analysis / "current.json").read_text())
            self.assertEqual(state["generation"], 2)
            self.assertEqual(state["commits"], list(commits))
            self.assertEqual(
                [segment["path"] for segment in state["segments"]],
                ["segments/000002", "segments/000001", "."],
            )
            summary = json.loads((analysis / "summary.json").read_text())
            self.assertEqual(summary["segment_count"], 3)
            self.assertEqual(summary["selected_pairs"], 6)
            self.assertEqual(summary["no_analyzable_change"], 6)
            with (analysis / "summary.csv").open(
                newline="", encoding="utf-8"
            ) as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(
                [row["sequence"] for row in rows],
                ["0", "1", "2", "3", "4", "5"],
            )
            self.assertEqual(
                [(row["old_commit"], row["new_commit"]) for row in rows],
                list(zip(commits, commits[1:])),
            )
            self.assertEqual(
                {
                    path.name: path.read_bytes()
                    for path in (analysis / "pairs").glob("*.json")
                },
                initial_receipts,
            )
            self.assertFalse((analysis / "pending" / "continuation").exists())

            oldest_manifest["repository_identity"]["value"] = "drifted"
            (analysis / "segments" / "000002" / "manifest.json").write_text(
                json.dumps(oldest_manifest, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "checksum drift"):
                load_verified_analysis_state(analysis)

    def test_continue_older_rejects_incomplete_newer_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository = root / "repository"
            repository.mkdir()
            git(repository, "init", "--initial-branch=main")
            git(repository, "config", "user.name", "CLI Test")
            git(repository, "config", "user.email", "cli@example.invalid")
            for index in range(4):
                self._commit(repository, f"commit-{index}")
            analysis = root / "analysis"
            srcdiff = executable(root / "srcdiff")
            srcmove = executable(root / "srcmove")
            self.assertEqual(
                self._main(
                    [
                        "start",
                        "--repository",
                        str(repository),
                        "--repository-id",
                        "fixture-repository",
                        "--analysis-root",
                        str(analysis),
                        "--count",
                        "2",
                        "--srcdiff",
                        str(srcdiff),
                        "--srcmove",
                        str(srcmove),
                        "--exclude-suffix",
                        ".txt",
                    ]
                ),
                0,
            )
            (analysis / "pairs" / "000001.json").unlink()
            with contextlib.redirect_stderr(io.StringIO()):
                status = self._main(
                    [
                        "continue-older",
                        "--analysis-root",
                        str(analysis),
                        "--count",
                        "1",
                    ]
                )

            self.assertEqual(status, 2)
            self.assertFalse((analysis / "pending" / "continuation").exists())

    def test_pending_continuation_resumes_without_workers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            analysis = self._continuation_fixture(root)
            before = (analysis / "current.json").read_bytes()
            arguments = [
                "continue-older",
                "--analysis-root",
                str(analysis),
                "--count",
                "2",
            ]
            with (
                patch(
                    "repository_analysis.cli.promote_pending_continuation",
                    side_effect=RuntimeError("injected promotion interruption"),
                ),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(self._main(arguments), 2)

            pending = analysis / "pending" / "continuation"
            self.assertTrue((pending / "manifest.json").is_file())
            self.assertEqual((analysis / "current.json").read_bytes(), before)
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(
                    self._main(
                        [
                            "continue-older",
                            "--analysis-root",
                            str(analysis),
                            "--count",
                            "1",
                        ]
                    ),
                    2,
                )
            self.assertEqual((analysis / "current.json").read_bytes(), before)
            with patch.object(
                PairExecutor,
                "open_worker",
                side_effect=AssertionError("sealed pending segment opened a worker"),
            ):
                self.assertEqual(self._main(arguments), 0)

            self.assertFalse(pending.exists())
            self.assertTrue((analysis / "segments" / "000001").is_dir())
            self.assertEqual(
                load_verified_analysis_state(analysis).generation, 1
            )

    def test_continue_older_reconciles_promoted_segment_before_new_work(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            analysis = self._continuation_fixture(root)
            arguments = [
                "continue-older",
                "--analysis-root",
                str(analysis),
                "--count",
                "2",
            ]
            with (
                patch(
                    "repository_analysis.chain._replace_current_state",
                    side_effect=RuntimeError("injected state publication interruption"),
                ),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(self._main(arguments), 2)

            self.assertEqual(load_verified_analysis_state(analysis).generation, 0)
            self.assertTrue((analysis / "segments" / "000001").is_dir())
            with patch.object(
                PairExecutor,
                "open_worker",
                side_effect=AssertionError("reconciliation opened a worker"),
            ):
                self.assertEqual(self._main(arguments), 0)

            state = load_verified_analysis_state(analysis)
            self.assertEqual(state.generation, 1)
            self.assertEqual(len(state.commits), 5)

    def test_current_state_loader_rejects_schema_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            analysis = self._continuation_fixture(Path(temporary_directory))
            path = analysis / "current.json"
            baseline = json.loads(path.read_text(encoding="utf-8"))
            mutations = (
                lambda value: value.update({"unknown": True}),
                lambda value: value.pop("segments"),
                lambda value: value.update({"generation": True}),
                lambda value: value.update({"schema_version": 999}),
            )
            for index, mutate in enumerate(mutations):
                with self.subTest(index=index):
                    value = json.loads(json.dumps(baseline))
                    mutate(value)
                    path.write_text(
                        json.dumps(value, sort_keys=True, indent=2) + "\n",
                        encoding="utf-8",
                    )
                    with self.assertRaises(ValueError):
                        load_verified_analysis_state(analysis)
            path.write_text(
                '{"schema_version":1,"schema_version":1}\n', encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "duplicate JSON field"):
                load_verified_analysis_state(analysis)


    def test_moved_branch_resume_uses_frozen_complete_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository = root / "repository"
            repository.mkdir()
            git(repository, "init", "--initial-branch=main")
            git(repository, "config", "user.name", "CLI Test")
            git(repository, "config", "user.email", "cli@example.invalid")
            self._commit(repository, "one")
            self._commit(repository, "two")
            frozen_tip = self._commit(repository, "three")
            analysis = root / "analysis"
            srcdiff = executable(root / "srcdiff")
            srcmove = executable(root / "srcmove")
            common = [
                "--analysis-root",
                str(analysis),
                "--repository-id",
                "fixture-repository",
                "--srcdiff",
                str(srcdiff),
                "--srcmove",
                str(srcmove),
                "--exclude-suffix",
                ".txt",
            ]

            status = self._main(
                [
                    "start",
                    "--repository",
                    str(repository),
                    "--start",
                    "HEAD",
                    "--count",
                    "2",
                    *common,
                ]
            )
            self.assertEqual(status, 0)
            second_receipt = analysis / "pairs" / "000001.json"
            self.assertTrue(second_receipt.is_file())
            second_receipt.unlink()

            moved_tip = self._commit(repository, "four")
            self.assertNotEqual(moved_tip, frozen_tip)
            with patch(
                "repository_analysis.cli.select_first_parent_history",
                side_effect=AssertionError("resume resolved a moving branch"),
            ):
                status = self._main(["resume", *common])

            self.assertEqual(status, 0)
            self.assertTrue(second_receipt.is_file())
            with patch.object(
                PairExecutor,
                "open_worker",
                side_effect=AssertionError("completed resume opened a worker"),
            ):
                status = self._main(["resume", *common])

            self.assertEqual(status, 0)
            self.assertEqual(
                len(list((analysis / "pairs").glob("*.json"))), 2
            )

    def test_resume_executable_drift_fails_without_changing_analysis_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository = root / "repository"
            repository.mkdir()
            git(repository, "init", "--initial-branch=main")
            git(repository, "config", "user.name", "CLI Test")
            git(repository, "config", "user.email", "cli@example.invalid")
            self._commit(repository, "one")
            self._commit(repository, "two")
            analysis = root / "analysis"
            srcdiff = executable(root / "srcdiff")
            srcmove = executable(root / "srcmove")
            common = [
                "--analysis-root",
                str(analysis),
                "--repository-id",
                "fixture-repository",
                "--srcdiff",
                str(srcdiff),
                "--srcmove",
                str(srcmove),
                "--exclude-suffix",
                ".txt",
            ]
            self.assertEqual(
                self._main(
                    [
                        "start",
                        "--repository",
                        str(repository),
                        "--count",
                        "1",
                        *common,
                    ]
                ),
                0,
            )
            before = {
                path.relative_to(analysis): path.read_bytes()
                for path in analysis.rglob("*")
                if path.is_file()
            }
            executable(srcdiff, b"#!/bin/sh\nexit 0\n")

            error = io.StringIO()
            with contextlib.redirect_stderr(error):
                status = self._main(["resume", *common])

            self.assertEqual(status, 2)
            self.assertIn("executable drift", error.getvalue())
            self.assertEqual(
                {
                    path.relative_to(analysis): path.read_bytes()
                    for path in analysis.rglob("*")
                    if path.is_file()
                },
                before,
            )

    def test_start_error_does_not_publish_partial_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository = root / "repository"
            repository.mkdir()
            git(repository, "init", "--initial-branch=main")
            analysis = root / "analysis"
            with contextlib.redirect_stderr(io.StringIO()):
                status = self._main(
                    [
                        "start",
                        "--repository",
                        str(repository),
                        "--start",
                        "missing",
                        "--count",
                        "1",
                        "--analysis-root",
                        str(analysis),
                        "--repository-id",
                        "fixture-repository",
                        "--srcdiff",
                        str(executable(root / "srcdiff")),
                        "--srcmove",
                        str(executable(root / "srcmove")),
                    ]
                )

            self.assertEqual(status, 2)
            self.assertFalse((analysis / "manifest.json").exists())

    def _commit(self, repository: Path, value: str) -> str:
        (repository / "fixture.txt").write_text(value, encoding="utf-8")
        git(repository, "add", "fixture.txt")
        git(repository, "commit", "-m", value)
        return git(repository, "rev-parse", "HEAD")

    def _continuation_fixture(self, root: Path) -> Path:
        repository = root / "repository"
        repository.mkdir()
        git(repository, "init", "--initial-branch=main")
        git(repository, "config", "user.name", "CLI Test")
        git(repository, "config", "user.email", "cli@example.invalid")
        for index in range(5):
            self._commit(repository, f"commit-{index}")
        analysis = root / "analysis"
        srcdiff = executable(root / "srcdiff")
        srcmove = executable(root / "srcmove")
        status = self._main(
            [
                "start",
                "--repository",
                str(repository),
                "--repository-id",
                "fixture-repository",
                "--analysis-root",
                str(analysis),
                "--count",
                "2",
                "--srcdiff",
                str(srcdiff),
                "--srcmove",
                str(srcmove),
                "--exclude-suffix",
                ".txt",
            ]
        )
        self.assertEqual(status, 0)
        return analysis

    def _main(self, arguments: list[str]) -> int:
        with contextlib.redirect_stdout(io.StringIO()):
            return main(arguments)


if __name__ == "__main__":
    unittest.main()
