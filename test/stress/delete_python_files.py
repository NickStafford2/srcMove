#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve()
STRESS_ROOT = SCRIPT_PATH.parent
TEST_ROOT = STRESS_ROOT.parent.resolve()
REPO_ROOT = TEST_ROOT.parent.resolve()


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def require_safe_target(target: Path) -> Path:
    resolved = target.resolve()

    if not is_relative_to(SCRIPT_PATH, TEST_ROOT):
        raise RuntimeError(f"script must live under the test directory: {SCRIPT_PATH}")

    if not is_relative_to(resolved, TEST_ROOT):
        raise RuntimeError(f"refusing to delete files outside the test directory: {resolved}")

    if not is_relative_to(resolved, REPO_ROOT):
        raise RuntimeError(f"refusing to delete files outside the repository: {resolved}")

    if is_relative_to(SCRIPT_PATH, resolved):
        raise RuntimeError(f"refusing to delete a directory containing this script: {resolved}")

    if not resolved.is_dir():
        raise RuntimeError(f"target directory does not exist: {resolved}")

    return resolved


def delete_python_files(target: Path) -> int:
    safe_target = require_safe_target(target)
    deleted = 0

    # This preprocess step is needed because srcdiff does not work well with
    # Python files currently and can crash while diffing them.
    for path in safe_target.rglob("*.py"):
        if not path.is_file():
            continue

        path.unlink()
        deleted += 1

    return deleted


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Delete Python files below one or more test directories."
    )
    parser.add_argument("directories", nargs="+", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    total = 0
    directories = [require_safe_target(directory) for directory in args.directories]

    for directory in directories:
        deleted = delete_python_files(directory)
        print(f"deleted {deleted} Python files under {directory}")
        total += deleted

    print(f"deleted {total} Python files total")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        raise SystemExit(1)
