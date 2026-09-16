from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "benchmark"
from benchmarking.contracts import (
    ProvenanceStatus,
    RunMode,
    TerminationStatus,
    XmlStatus,
)


class BenchmarkContractTests(unittest.TestCase):
    def test_status_vocabulary_is_stable(self) -> None:
        self.assertEqual(
            [mode.value for mode in RunMode], ["development", "publication"]
        )
        self.assertEqual(
            [status.value for status in ProvenanceStatus],
            ["verified", "stale", "unverified", "unavailable"],
        )
        self.assertEqual(
            [status.value for status in TerminationStatus],
            [
                "exited",
                "signaled",
                "timed_out",
                "spawn_failed",
                "orchestration_interrupted",
            ],
        )
        self.assertEqual(
            [status.value for status in XmlStatus],
            [
                "valid",
                "missing",
                "empty",
                "malformed",
                "invalid_structure",
                "not_checked",
            ],
        )
    def test_tiny_source_and_srcdiff_fixtures_are_checked_in(self) -> None:
        self.assertIn("int moved()", (FIXTURE_ROOT / "original.cpp").read_text())
        self.assertIn("int moved()", (FIXTURE_ROOT / "modified.cpp").read_text())
        self.assertIn("diff:delete", (FIXTURE_ROOT / "input.srcdiff.xml").read_text())

    def test_fake_tool_covers_success_nonzero_and_missing_output(self) -> None:
        fake_tool = FIXTURE_ROOT / "fake_tool.py"
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "output.xml"
            success = subprocess.run(
                [sys.executable, str(fake_tool), "success", "--output", str(output)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(success.returncode, 0)
            self.assertTrue(output.is_file())

            nonzero = subprocess.run(
                [sys.executable, str(fake_tool), "nonzero"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(nonzero.returncode, 23)

            missing_output = subprocess.run(
                [
                    sys.executable,
                    str(fake_tool),
                    "missing-output",
                    "--output",
                    str(Path(temporary_directory) / "missing.xml"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(missing_output.returncode, 0)
            self.assertFalse((Path(temporary_directory) / "missing.xml").exists())

if __name__ == "__main__":
    unittest.main()
