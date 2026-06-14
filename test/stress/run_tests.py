#!/usr/bin/env python3
# test/stress/run_diff_and_move_repo_tests.py

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
RUNNER = SCRIPT_DIR / "diff_and_move_repo.py"

TESTS = [
    # [sys.executable, str(RUNNER), "sqlite"],
    # [sys.executable, str(RUNNER), "opencv"],
    # [sys.executable, str(RUNNER), "firefox"],
    # [sys.executable, str(RUNNER), "opencv"],
    [sys.executable, str(RUNNER), "notepadpp"],
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    _ = parser.add_argument(
        "--position",
        action="store_true",
        help="Pass --position through to diff_and_move_repo.py.",
    )
    return parser.parse_args()


def build_test_command(cmd: list[str], *, use_position: bool) -> list[str]:
    if not use_position:
        return cmd

    return [*cmd, "--position"]


def run_test(cmd: list[str]) -> int:
    print(f"running: {' '.join(cmd)}")

    result = subprocess.run(cmd, cwd=SCRIPT_DIR)

    if result.returncode == 0:
        print("  PASS\n")
    else:
        print(f"  FAIL (exit code {result.returncode})\n")

    return result.returncode


def main() -> int:
    args = parse_args()
    failures = 0

    for base_cmd in TESTS:
        cmd = build_test_command(base_cmd, use_position=args.position)
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
