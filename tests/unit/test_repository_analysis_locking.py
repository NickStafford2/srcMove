from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from repository_analysis.locking import (
    LOCK_FILE_NAME,
    AnalysisBusyError,
    AnalysisOperationLock,
    is_analysis_writer_locked,
    load_analysis_activity,
)


class AnalysisOperationLockTests(unittest.TestCase):
    def test_probe_does_not_create_a_missing_root_or_lock_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "missing-analysis"

            self.assertFalse(is_analysis_writer_locked(root))
            self.assertFalse(root.exists())

            root.mkdir()
            self.assertFalse(is_analysis_writer_locked(root))
            self.assertEqual(list(root.iterdir()), [])

    def test_probe_reports_held_and_available_locks_without_publishing_activity(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "analysis"

            with AnalysisOperationLock(root, command="owner"):
                before = load_analysis_activity(root)
                self.assertTrue(is_analysis_writer_locked(root))
                self.assertEqual(load_analysis_activity(root), before)
                with self.assertRaises(AnalysisBusyError):
                    with AnalysisOperationLock(root, command="contender"):
                        self.fail("probe disturbed the existing owner")

            before = load_analysis_activity(root)
            self.assertFalse(is_analysis_writer_locked(root))
            self.assertEqual(load_analysis_activity(root), before)

    def test_probe_rejects_symbolic_link_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            target = parent / "analysis"
            target.mkdir()
            alias = parent / "alias"
            alias.symlink_to(target, target_is_directory=True)

            with self.assertRaisesRegex(
                ValueError, "root must not be a symbolic link"
            ):
                is_analysis_writer_locked(alias)

    def test_probe_rejects_unsafe_lock_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "analysis"
            root.mkdir()
            target = root / "target"
            target.touch()
            (root / LOCK_FILE_NAME).symlink_to(target)

            with self.assertRaisesRegex(
                ValueError, "lock must not be a symbolic link"
            ):
                is_analysis_writer_locked(root)

    def test_probe_rejects_non_regular_and_multiply_linked_lock_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            directory_root = parent / "directory-lock-analysis"
            directory_root.mkdir()
            (directory_root / LOCK_FILE_NAME).mkdir()

            with self.assertRaisesRegex(ValueError, "one owned regular file"):
                is_analysis_writer_locked(directory_root)

            linked_root = parent / "linked-lock-analysis"
            linked_root.mkdir()
            lock_path = linked_root / LOCK_FILE_NAME
            lock_path.touch()
            (parent / "second-link").hardlink_to(lock_path)

            with self.assertRaisesRegex(ValueError, "one owned regular file"):
                is_analysis_writer_locked(linked_root)

    def test_exclusive_lock_records_completed_activity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "analysis"

            with AnalysisOperationLock(root, command="analyze") as operation:
                activity = load_analysis_activity(root)
                self.assertIsNotNone(activity)
                assert activity is not None
                self.assertTrue(activity["is_running"])
                self.assertEqual(activity["command"], "analyze")
                self.assertEqual(activity["invocation_id"], operation.invocation_id)
                self.assertIsNone(activity["ended_at"])

            activity = load_analysis_activity(root)
            self.assertIsNotNone(activity)
            assert activity is not None
            self.assertFalse(activity["is_running"])
            self.assertEqual(activity["result"], "completed")
            self.assertIsNotNone(activity["ended_at"])

    def test_second_writer_is_rejected_without_changing_owner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "analysis"

            with AnalysisOperationLock(root, command="first") as first:
                before = load_analysis_activity(root)
                with self.assertRaisesRegex(
                    AnalysisBusyError, "already running.*command=first"
                ):
                    with AnalysisOperationLock(root, command="second"):
                        self.fail("second writer acquired the analysis lock")
                self.assertEqual(load_analysis_activity(root), before)
                assert before is not None
                self.assertEqual(before["invocation_id"], first.invocation_id)

    def test_failed_operation_releases_lock_and_records_previous_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "analysis"

            with self.assertRaisesRegex(RuntimeError, "injected"):
                with AnalysisOperationLock(root, command="first"):
                    raise RuntimeError("injected")

            failed = load_analysis_activity(root)
            self.assertIsNotNone(failed)
            assert failed is not None
            self.assertFalse(failed["is_running"])
            self.assertEqual(failed["result"], "failed")

            with AnalysisOperationLock(root, command="second"):
                current = load_analysis_activity(root)
                self.assertIsNotNone(current)
                assert current is not None
                self.assertEqual(current["previous"]["result"], "failed")

    def test_owner_process_crash_releases_kernel_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "analysis"
            script = """
import sys
from pathlib import Path
from repository_analysis.locking import AnalysisOperationLock

with AnalysisOperationLock(Path(sys.argv[1]), command="child"):
    print("ready", flush=True)
    sys.stdin.read()
"""
            child = subprocess.Popen(
                [sys.executable, "-c", script, str(root)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.addCleanup(self._stop_child, child)
            assert child.stdout is not None
            self.assertEqual(child.stdout.readline().strip(), "ready")
            with self.assertRaises(AnalysisBusyError):
                with AnalysisOperationLock(root, command="contender"):
                    self.fail("contender acquired a live child lock")

            child.kill()
            child.communicate(timeout=5)
            with AnalysisOperationLock(root, command="recovery"):
                activity = load_analysis_activity(root)
                assert activity is not None
                self.assertEqual(activity["previous"]["result"], "interrupted")

    @staticmethod
    def _stop_child(child: subprocess.Popen) -> None:
        if child.poll() is None:
            child.kill()
        child.communicate()


if __name__ == "__main__":
    unittest.main()
