from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.progress import ProgressDisplay


class ProgressDisplayTests(unittest.TestCase):
    def test_redirected_output_is_sparse_and_durable(self) -> None:
        output = io.StringIO()
        with ProgressDisplay(
            "srcMove",
            total=10,
            detail="starting",
            stream=output,
            refresh_seconds=10,
        ) as progress:
            for completed in range(1, 11):
                progress.update(completed, detail=f"case-{completed}")
            progress.finish("10 completed, 0 failed")

        lines = output.getvalue().splitlines()
        self.assertEqual(lines[0], "[srcMove] started: 0/10   0% 00:00 — starting")
        self.assertIn("[srcMove] progress: 10/10 100%", lines[-2])
        self.assertIn("[srcMove] complete: 10/10 100%", lines[-1])
        self.assertLessEqual(len(lines), 12)

    def test_failure_event_names_the_current_case(self) -> None:
        output = io.StringIO()
        with ProgressDisplay("srcDiff", total=2, stream=output) as progress:
            progress.update(0, detail="case-bad")
            progress.event("case-bad failed; continuing")
            progress.update(2, detail="case-good")
            progress.finish("1 accepted, 1 failed")

        self.assertIn("! srcDiff: case-bad failed; continuing", output.getvalue())
        self.assertIn("1 accepted, 1 failed", output.getvalue())


if __name__ == "__main__":
    unittest.main()
