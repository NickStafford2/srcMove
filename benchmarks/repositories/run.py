#!/usr/bin/env python3
# benchmarks/repositories/run.py

from __future__ import annotations

import argparse
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
TESTS_ROOT = REPO_ROOT / "tests"
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from support.tooling import command_text, run_command

RUNNER = SCRIPT_DIR / "run_case.py"

BENCHMARKS = [
    [sys.executable, str(RUNNER), "notepadpp"],
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    _ = parser.add_argument(
        "--position",
        action="store_true",
        help="Pass --position through to run_case.py.",
    )
    return parser.parse_args()


def build_benchmark_command(cmd: list[str], *, use_position: bool) -> list[str]:
    if not use_position:
        return cmd

    return [*cmd, "--position"]


def run_benchmark(cmd: list[str]) -> int:
    print(f"running: {command_text(cmd)}")

    result = run_command(cmd, cwd=SCRIPT_DIR, capture_output=False)

    if result.returncode == 0:
        print("  PASS\n")
    else:
        print(f"  FAIL (exit code {result.returncode})\n")

    return result.returncode


def main() -> int:
    args = parse_args()
    failures = 0

    for base_cmd in BENCHMARKS:
        cmd = build_benchmark_command(base_cmd, use_position=args.position)
        rc = run_benchmark(cmd)

        if rc != 0:
            failures += 1

    print("================================")
    print(f"benchmarks run: {len(BENCHMARKS)}")
    print(f"failures  : {failures}")

    if failures == 0:
        print("ALL BENCHMARKS COMPLETED")
        return 0

    print("BENCHMARKS FAILED")
    return 1


if __name__ == "__main__":
    sys.exit(main())
