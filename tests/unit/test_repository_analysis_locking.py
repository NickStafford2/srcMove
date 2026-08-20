from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from repository_analysis.locking import (
    AnalysisBusyError,
    AnalysisOperationLock,
    load_analysis_activity,
)


class AnalysisOperationLockTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
