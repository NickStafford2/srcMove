from __future__ import annotations

import hashlib
import os
import signal
import shutil
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from repository_analysis.contracts import PairStatus, PairWorkItem
from repository_analysis.coordinator import run_pairs
from repository_analysis.git import GitBatch, GitMaterializationError
from repository_analysis.process import (
    run_process,
    validate_xml_artifact,
)
from repository_analysis.worker import PairExecutor, _remove_tree_within


REPO_ROOT = Path(__file__).resolve().parents[3]
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
    def test_cleanup_unlinks_symlinks_without_crossing_analysis_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            analysis = root / "analysis"
            owned = analysis / "worker" / "pair"
            owned.mkdir(parents=True)
            outside = root / "outside"
            outside.mkdir()
            evidence = outside / "keep.txt"
            evidence.write_text("keep", encoding="utf-8")
            (owned / "outside-link").symlink_to(outside, target_is_directory=True)

            _remove_tree_within(owned, analysis)

            self.assertFalse(owned.exists())
            self.assertEqual(evidence.read_text(encoding="utf-8"), "keep")
            with self.assertRaisesRegex(ValueError, "escapes analysis root"):
                _remove_tree_within(outside, analysis)
            self.assertTrue(outside.exists())

    def test_publication_acknowledgement_removes_worker_scratch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository, commits = create_history(root)
            tools = root / "tools"
            tools.mkdir()
            srcdiff = executable_copy(tools, "srcdiff-valid-archive")
            srcmove = executable_copy(tools, "srcmove-valid-archive")
            analysis = root / "analysis"
            executor = PairExecutor(analysis)
            published_results: list[Path] = []

            def publish(outcome) -> None:
                results = next(
                    artifact.path
                    for artifact in outcome.artifacts
                    if artifact.kind == "json_results"
                )
                self.assertTrue(results.is_file())
                published_results.append(results)

            run_pairs(
                [item(0, commits[0], commits[1], repository, srcdiff, srcmove)],
                executor,
                publish,
                worker_count=1,
                acknowledge_pair=executor.acknowledge,
            )

            self.assertEqual(len(published_results), 1)
            self.assertFalse(published_results[0].exists())
            self.assertEqual(
                list(analysis.glob("repository-analysis-worker-*")), []
            )

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
                self.assertEqual(
                    outcome.srcdiff_process.command.count("--archive"), 1
                )
                self.assertEqual(
                    outcome.srcdiff_process.output_artifact.shape, "archive"
                )
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

    def test_special_git_modes_do_not_fail_an_otherwise_analyzable_pair(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository, commits = create_history(root)
            (repository / "source.cpp").write_text(
                "int value = 4;\n", encoding="utf-8"
            )
            (repository / "linked.cpp").symlink_to("source.cpp")
            run_git(repository, "add", "source.cpp", "linked.cpp")
            run_git(
                repository,
                "update-index",
                "--add",
                "--cacheinfo",
                f"160000,{commits[-1]},vendor/module",
            )
            run_git(repository, "commit", "--quiet", "-m", "special paths")
            newest = run_git(repository, "rev-parse", "HEAD")
            tools = root / "tools"
            tools.mkdir()
            srcdiff = executable_copy(tools, "srcdiff-valid-archive")
            srcmove = executable_copy(tools, "srcmove-valid-archive")
            outcomes = []

            run_pairs(
                [
                    item(
                        0,
                        commits[-1],
                        newest,
                        repository,
                        srcdiff,
                        srcmove,
                    )
                ],
                PairExecutor(root / "analysis"),
                outcomes.append,
                worker_count=1,
            )

            self.assertEqual(outcomes[0].status, PairStatus.COMPLETED)
            self.assertEqual(
                [path.path for path in outcomes[0].analyzable_paths],
                ["source.cpp"],
            )
            reasons = {
                path.path: path.exclusion_reasons
                for path in outcomes[0].changed_paths
                if path.exclusion_reasons
            }
            self.assertEqual(
                reasons,
                {
                    "linked.cpp": ("unsupported_git_mode: symlink",),
                    "vendor/module": ("unsupported_git_mode: submodule",),
                },
            )
            materialized = [
                artifact.path.as_posix()
                for artifact in outcomes[0].artifacts
                if artifact.kind == "git_blob"
            ]
            self.assertTrue(materialized)
            self.assertFalse(
                any(
                    path.endswith("/linked.cpp") or "/vendor/module" in path
                    for path in materialized
                )
            )

    def test_materialization_failure_has_export_failed_status(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository, commits = create_history(root)
            tools = root / "tools"
            tools.mkdir()
            srcdiff = executable_copy(tools, "srcdiff-valid-archive")
            srcmove = executable_copy(tools, "srcmove-valid-archive")
            outcomes = []

            with mock.patch.object(
                GitBatch,
                "materialize",
                side_effect=GitMaterializationError(
                    "injected materialization failure"
                ),
            ):
                run_pairs(
                    [item(0, commits[0], commits[1], repository, srcdiff, srcmove)],
                    PairExecutor(root / "analysis"),
                    outcomes.append,
                    worker_count=1,
                )

            outcome = outcomes[0]
            self.assertEqual(outcome.status, PairStatus.EXPORT_FAILED)
            self.assertIn("injected materialization failure", outcome.error)
            self.assertIsNone(outcome.srcdiff_process)
            self.assertIsNone(outcome.srcmove_process)

    def test_incomplete_work_item_has_orchestration_failed_status(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            outcomes = []
            work_item = PairWorkItem(
                sequence=0,
                old_commit="old",
                new_commit="new",
                fingerprint="incomplete",
            )

            run_pairs(
                [work_item],
                PairExecutor(Path(temporary_directory) / "analysis"),
                outcomes.append,
                worker_count=1,
            )

            outcome = outcomes[0]
            self.assertEqual(outcome.status, PairStatus.ORCHESTRATION_FAILED)
            self.assertIn("missing execution fields", outcome.error)
            self.assertIsNone(outcome.srcdiff_process)
            self.assertIsNone(outcome.srcmove_process)

    def test_srcdiff_process_failures_are_terminal_and_skip_srcmove(self) -> None:
        cases = {
            "nonzero": ("exited", 23, None, "exited with code 23"),
            "signal": ("signaled", None, signal.SIGTERM, "terminated by signal"),
            "timeout": ("timed_out", None, None, "timed out"),
            "spawn": ("spawn_failed", None, None, "could not start"),
        }
        for name, (termination, exit_code, signal_number, error_text) in cases.items():
            with (
                self.subTest(name=name),
                tempfile.TemporaryDirectory() as temporary_directory,
            ):
                root = Path(temporary_directory)
                repository, commits = create_history(root)
                tools = root / "tools"
                tools.mkdir()
                srcdiff = (
                    tools / "srcdiff-does-not-exist"
                    if name == "spawn"
                    else executable_copy(tools, f"srcdiff-{name}")
                )
                marker = root / "srcmove-ran"
                srcmove = tools / "srcmove"
                srcmove.write_text(
                    "#!/bin/sh\ntouch \"$SRMOVE_MARKER\"\nexit 99\n",
                    encoding="utf-8",
                )
                srcmove.chmod(0o755)
                work_item = item(
                    0, commits[0], commits[1], repository, srcdiff, srcmove
                )
                if name == "timeout":
                    work_item = replace(work_item, srcdiff_timeout_seconds=0.1)

                with mock.patch.dict(os.environ, {"SRMOVE_MARKER": str(marker)}):
                    outcomes = []
                    run_pairs(
                        [work_item],
                        PairExecutor(root / "analysis"),
                        outcomes.append,
                        worker_count=1,
                    )

                outcome = outcomes[0]
                self.assertEqual(outcome.status, PairStatus.SRCDIFF_FAILED)
                self.assertEqual(
                    outcome.srcdiff_process.termination_status, termination
                )
                self.assertEqual(outcome.srcdiff_process.exit_code, exit_code)
                self.assertEqual(
                    outcome.srcdiff_process.signal_number, signal_number
                )
                self.assertIn(error_text, outcome.error)
                self.assertIsNone(outcome.srcmove_process)
                self.assertFalse(marker.exists())

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

    def test_srcmove_process_failures_have_srcmove_failed_status(self) -> None:
        cases = {
            "nonzero": ("exited", 23, None, "exited with code 23"),
            "signal": ("signaled", None, signal.SIGTERM, "terminated by signal"),
            "timeout": ("timed_out", None, None, "timed out"),
            "malformed": ("exited", 0, None, "artifact validation failed"),
            "spawn": ("spawn_failed", None, None, "could not start"),
        }
        for name, (termination, exit_code, signal_number, error_text) in cases.items():
            with (
                self.subTest(name=name),
                tempfile.TemporaryDirectory() as temporary_directory,
            ):
                root = Path(temporary_directory)
                repository, commits = create_history(root)
                tools = root / "tools"
                tools.mkdir()
                srcdiff = executable_copy(tools, "srcdiff-valid-archive")
                srcmove = (
                    tools / "srcmove-does-not-exist"
                    if name == "spawn"
                    else executable_copy(tools, f"srcmove-{name}")
                )
                work_item = item(
                    0, commits[0], commits[1], repository, srcdiff, srcmove
                )
                if name == "timeout":
                    work_item = replace(work_item, srcmove_timeout_seconds=0.1)
                outcomes = []

                run_pairs(
                    [work_item],
                    PairExecutor(root / "analysis"),
                    outcomes.append,
                    worker_count=1,
                )

                outcome = outcomes[0]
                self.assertEqual(outcome.status, PairStatus.SRCMOVE_FAILED)
                self.assertTrue(outcome.srcdiff_process.admitted)
                self.assertEqual(
                    outcome.srcmove_process.termination_status, termination
                )
                self.assertEqual(outcome.srcmove_process.exit_code, exit_code)
                self.assertEqual(
                    outcome.srcmove_process.signal_number, signal_number
                )
                self.assertIn(error_text, outcome.error)


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
