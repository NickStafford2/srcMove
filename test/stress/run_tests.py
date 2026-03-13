#!/usr/bin/env python3
# test/stress/diff_and_move_repo.py

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
RUNNER = SCRIPT_DIR / "diff_and_move_repo.py"

TESTS = [
    [sys.executable, str(RUNNER), "sqlite"],
    # [sys.executable, str(RUNNER), "opencv"],
    # [sys.executable, str(RUNNER), "firefox"],
]


def run_test(cmd: list[str]) -> int:
    print(f"running: {' '.join(cmd)}")

    result = subprocess.run(cmd, cwd=SCRIPT_DIR)

    if result.returncode == 0:
        print("  PASS\n")
    else:
        print(f"  FAIL (exit code {result.returncode})\n")

    return result.returncode


def main() -> int:
    failures = 0

    for cmd in TESTS:
        rc = run_test(cmd)
        if rc != 0:
            failures += 1

    print("================================")
    print(f"tests run : {len(TESTS)}")
    print(f"failures  : {failures}")

    if failures == 0:
        print("ALL TESTS PASSED")
        return 0

    print("TESTS FAILED")
    return 1


if __name__ == "__main__":
    sys.exit(main())
