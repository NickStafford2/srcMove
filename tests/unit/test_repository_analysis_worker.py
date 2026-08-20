from __future__ import annotations

import hashlib
import os
import signal
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from repository_analysis import PairExecutor, PairStatus, PairWorkItem, run_pairs
from repository_analysis.git import GitBatch
from repository_analysis.process import (
    run_process,
    validate_xml_artifact,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
FAKE_TOOL = REPO_ROOT / "tests" / "fixtures" / "benchmark" / "fake_tool.py"


def run_git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    return result.stdout.strip()


def create_history(root: Path) -> tuple[Path, tuple[str, str, str]]:
    repository = root / "repository"
    repository.mkdir()
    run_git(repository, "init", "--quiet")
    run_git(repository, "config", "user.name", "Fixture")
    run_git(repository, "config", "user.email", "fixture@example.com")
    source = repository / "source.cpp"
    source.write_text("int value = 1;\n", encoding="utf-8")
    run_git(repository, "add", "source.cpp")
    run_git(repository, "commit", "--quiet", "-m", "first")
    first = run_git(repository, "rev-parse", "HEAD")
    source.write_text("int value = 2;\n", encoding="utf-8")
    run_git(repository, "commit", "--quiet", "-am", "second")
    second = run_git(repository, "rev-parse", "HEAD")
    source.write_text("int value = 3;\n", encoding="utf-8")
    run_git(repository, "commit", "--quiet", "-am", "third")
    third = run_git(repository, "rev-parse", "HEAD")
    return repository, (first, second, third)


def executable_copy(root: Path, name: str) -> Path:
    destination = root / name
    shutil.copy2(FAKE_TOOL, destination)
    destination.chmod(0o755)
    return destination


def item(
    sequence: int,
    old_commit: str,
    new_commit: str,
    repository: Path,
    srcdiff: Path,
    srcmove: Path,
) -> PairWorkItem:
    return PairWorkItem(
        sequence=sequence,
        old_commit=old_commit,
        new_commit=new_commit,
        fingerprint=f"fingerprint-{sequence}",
        repository=repository,
        srcdiff=srcdiff,
        srcmove=srcmove,
        srcdiff_timeout_seconds=2.0,
        srcmove_timeout_seconds=2.0,
    )


class PairExecutorTests(unittest.TestCase):
    def test_worker_session_setup_failure_propagates_without_deadlock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            invalid_root = root / "not-a-directory"
            invalid_root.write_text("fixture", encoding="utf-8")

            with self.assertRaises(FileExistsError):
                run_pairs(
                    [
                        PairWorkItem(
                            sequence=0,
                            old_commit="old",
                            new_commit="new",
                            fingerprint="fingerprint",
                        )
                    ],
                    PairExecutor(invalid_root),
                    lambda outcome: None,
                    worker_count=2,
                )

    def test_worker_reuses_one_git_batch_and_runs_tools_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository, commits = create_history(root)
            tools = root / "tools"
            tools.mkdir()
            srcdiff = executable_copy(tools, "srcdiff-valid-archive")
            srcmove = executable_copy(tools, "srcmove-valid-archive")
            work = [
                item(0, commits[0], commits[1], repository, srcdiff, srcmove),
                item(1, commits[1], commits[2], repository, srcdiff, srcmove),
            ]
            outcomes = []
            real_batch = GitBatch
            starts: list[int] = []

            class CountingBatch(real_batch):
                def __init__(self, repository: Path) -> None:
                    super().__init__(repository)
                    starts.append(self.process_id)

            with mock.patch("repository_analysis.worker.GitBatch", CountingBatch):
                run_pairs(
                    work,
                    PairExecutor(root / "analysis"),
                    outcomes.append,
                    worker_count=1,
                )

            self.assertEqual(len(starts), 1)
            self.assertEqual([outcome.status for outcome in outcomes], [
                PairStatus.COMPLETED,
                PairStatus.COMPLETED,
            ])
            for outcome in outcomes:
                self.assertEqual(dict(outcome.metrics)["move_count"], 0)
                self.assertTrue(outcome.srcdiff_process.admitted)
                self.assertTrue(outcome.srcmove_process.admitted)
                kinds = [artifact.kind for artifact in outcome.artifacts]
                self.assertIn("git_blob", kinds)
                self.assertIn("json_results", kinds)
                source_artifact = next(
                    artifact
                    for artifact in outcome.artifacts
                    if artifact.kind == "git_blob"
                    and dict(artifact.details)["side"] == "new"
                )
                self.assertEqual(
                    source_artifact.sha256,
                    hashlib.sha256(source_artifact.path.read_bytes()).hexdigest(),
                )
                self.assertEqual(
                    Path(outcome.srcmove_process.command[1]),
                    outcome.srcdiff_process.output_artifact.path,
                )
            self.assertFalse(any(_process_exists(pid) for pid in starts))

    def test_srcdiff_validation_failure_does_not_run_srcmove(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository, commits = create_history(root)
            tools = root / "tools"
            tools.mkdir()
            srcdiff = executable_copy(tools, "srcdiff-malformed")
            marker = root / "srcmove-ran"
            srcmove = tools / "srcmove"
            srcmove.write_text(
                "#!/bin/sh\ntouch \"$SRMOVE_MARKER\"\nexit 99\n",
                encoding="utf-8",
            )
            srcmove.chmod(0o755)
            with mock.patch.dict(os.environ, {"SRMOVE_MARKER": str(marker)}):
                outcomes = []
                run_pairs(
                    [item(0, commits[0], commits[1], repository, srcdiff, srcmove)],
                    PairExecutor(root / "analysis"),
                    outcomes.append,
                    worker_count=1,
                )

            outcome = outcomes[0]
            self.assertEqual(outcome.status, PairStatus.SRCDIFF_FAILED)
            self.assertIn("malformed", outcome.error)
            self.assertIsNone(outcome.srcmove_process)
            self.assertEqual(
                outcome.srcdiff_process.output_artifact.validation_status,
                "malformed",
            )
            self.assertTrue(outcome.srcdiff_process.output_artifact.sha256)
            self.assertFalse(marker.exists())

    def test_missing_results_is_a_srcmove_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository, commits = create_history(root)
            tools = root / "tools"
            tools.mkdir()
            srcdiff = executable_copy(tools, "srcdiff-valid-archive")
            srcmove = tools / "srcmove-no-results"
            srcmove.write_text(
                "#!/usr/bin/env python3\n"
                "import sys\n"
                "from pathlib import Path\n"
                "Path(sys.argv[2]).write_text(\"<unit "
                "xmlns='http://www.srcML.org/srcML/src' "
                "xmlns:diff='http://www.srcML.org/srcDiff'><unit/></unit>\")\n",
                encoding="utf-8",
            )
            srcmove.chmod(0o755)
            outcomes = []
            run_pairs(
                [item(0, commits[0], commits[1], repository, srcdiff, srcmove)],
                PairExecutor(root / "analysis"),
                outcomes.append,
                worker_count=1,
            )

            outcome = outcomes[0]
            self.assertEqual(outcome.status, PairStatus.SRCMOVE_FAILED)
            self.assertTrue(outcome.srcmove_process.admitted)
            self.assertIn("results JSON is missing", outcome.error)


class ProcessSupervisorTests(unittest.TestCase):
    def test_bounded_capture_records_full_checksum(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            output = root / "output.xml"
            xml = (
                "<unit xmlns='http://www.srcML.org/srcML/src' "
                "xmlns:diff='http://www.srcML.org/srcDiff'/>"
            )
            script = (
                "import pathlib,sys; "
                "sys.stdout.write('a'*200); "
                f"pathlib.Path(sys.argv[1]).write_text({xml!r})"
            )
            outcome = run_process(
                [sys.executable, "-c", script, str(output)],
                cwd=root,
                timeout_seconds=2.0,
                output_path=output,
                validator=lambda path: validate_xml_artifact(
                    path, shape="single_file", producing_stage="fixture"
                ),
                capture_prefix="fixture",
                log_limit=20,
            )

            self.assertTrue(outcome.admitted)
            self.assertEqual(outcome.stdout.retained_bytes, 20)
            self.assertEqual(outcome.stdout.omitted_bytes, 180)
            self.assertTrue(outcome.stdout.truncated)
            self.assertEqual(
                outcome.stdout.sha256, hashlib.sha256(b"a" * 200).hexdigest()
            )

    @unittest.skipUnless(os.name == "posix", "requires POSIX process groups")
    def test_timeout_force_kills_process_group(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            tool = executable_copy(root, "timeout-tree")
            output = root / "missing.xml"
            outcome = run_process(
                [str(tool), "timeout-tree"],
                cwd=root,
                timeout_seconds=0.5,
                timeout_grace_seconds=0.05,
                output_path=output,
                validator=lambda path: validate_xml_artifact(
                    path, shape="archive", producing_stage="fixture"
                ),
                capture_prefix="timeout",
            )

            self.assertEqual(outcome.termination_status, "timed_out")
            self.assertTrue(outcome.timed_out)
            self.assertEqual(outcome.cleanup_signals, (signal.SIGTERM, signal.SIGKILL))
            self.assertTrue(outcome.process_group_cleaned)


def _process_exists(process_id: int) -> bool:
    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return False
    return True


if __name__ == "__main__":
    unittest.main()
