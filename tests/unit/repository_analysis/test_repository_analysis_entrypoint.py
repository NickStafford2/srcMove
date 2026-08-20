from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
ENTRYPOINT = REPOSITORY_ROOT / "bin" / "srcmove-history"


class RepositoryAnalysisEntrypointTests(unittest.TestCase):
    def test_entrypoint_runs_from_outside_the_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            result = subprocess.run(
                [str(ENTRYPOINT), "--help"],
                cwd=temporary_directory,
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("usage:", result.stdout)
        self.assertEqual(result.stderr, "")

    def test_entrypoint_is_executable(self) -> None:
        self.assertTrue(os.access(ENTRYPOINT, os.X_OK))


if __name__ == "__main__":
    unittest.main()
