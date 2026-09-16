#!/usr/bin/env python3
"""Measure srcMove builds over named, pre-existing srcDiff XML workloads."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
TESTS_ROOT = REPO_ROOT / "tests"
for import_root in (REPO_ROOT, TESTS_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from benchmarks.contracts import RunMode
from performance.benchmark import (
    load_workloads,
    parse_named_path,
    run_performance,
)
from benchmarks.paths import DEFAULT_RESULTS_ROOT
from support.tooling import find_srcmove


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    variants = parser.add_mutually_exclusive_group(required=True)
    variants.add_argument(
        "--variant",
        action="append",
        metavar="NAME=PATH",
        help="Named srcMove build; repeat to compare builds.",
    )
    variants.add_argument(
        "--srcmove",
        type=Path,
        help="Single srcMove build, recorded as variant 'current'.",
    )
    parser.add_argument(
        "--workload",
        action="append",
        required=True,
        metavar="NAME=PATH",
        help="Named srcDiff XML workload; repeat to measure multiple workloads.",
    )
    parser.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    parser.add_argument("--run-id", help="Explicit unique run identifier.")
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument(
        "--cache-policy",
        default="uncontrolled_os_cache",
        help="Declared cache policy recorded verbatim in the run manifest.",
    )
    parser.add_argument(
        "--mode",
        choices=[mode.value for mode in RunMode],
        default=RunMode.DEVELOPMENT.value,
    )
    args = parser.parse_args()
    if args.warmups < 0:
        parser.error("--warmups must be nonnegative")
    if args.repetitions < 1:
        parser.error("--repetitions must be positive")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    return args


def main() -> int:
    args = parse_args()
    try:
        if args.variant:
            parsed_variants = [
                parse_named_path(value, "variant") for value in args.variant
            ]
            if len({name for name, _ in parsed_variants}) != len(parsed_variants):
                raise ValueError("variant names must be unique")
            variants = dict(parsed_variants)
        else:
            executable = find_srcmove(REPO_ROOT, args.srcmove)
            if executable is None:
                raise ValueError("srcMove executable not found; pass --srcmove")
            variants = {"current": executable}

        workloads = load_workloads(args.workload)
        run_dir, _, summary = run_performance(
            output_root=args.results_root.expanduser().resolve() / "performance",
            variants=variants,
            workloads=workloads,
            warmups=args.warmups,
            repetitions=args.repetitions,
            seed=args.seed,
            timeout_seconds=args.timeout,
            cache_policy=args.cache_policy,
            mode=RunMode(args.mode),
            run_id=args.run_id,
        )
    except (FileExistsError, FileNotFoundError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    print(f"run_id={run_dir.name}")
    print(f"directory={run_dir}")
    print(f"summary={run_dir / 'summary.json'}")
    return 1 if summary["counts"]["measured_failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
