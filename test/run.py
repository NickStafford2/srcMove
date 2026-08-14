#!/usr/bin/env python3
"""Unified entry point for deterministic srcMove correctness tests."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path


TEST_ROOT = Path(__file__).resolve().parent
REPO_ROOT = TEST_ROOT.parent
if str(TEST_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_ROOT))

from tooling import command_text, find_srcdiff, find_srcmove, run_command


SUITE_DESCRIPTIONS = {
    "unit": "Python unit tests for test and benchmark infrastructure",
    "xml": "checked-in srcDiff XML regression fixtures",
    "source": "checked-in source pairs regenerated through srcdiff",
}
REGRESSION_CASE_ROOTS = {
    "xml": TEST_ROOT / "e2e_custom" / "cases",
    "source": TEST_ROOT / "e2e_generated",
}


@dataclass(frozen=True)
class TestStep:
    name: str
    command: list[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build and run srcMove's deterministic correctness tests."
    )
    parser.add_argument(
        "--build",
        action="store_true",
        help="Configure and build build/srcMove before testing.",
    )
    parser.add_argument(
        "--suite",
        action="append",
        choices=tuple(SUITE_DESCRIPTIONS),
        help="Run only this suite; repeat to select multiple suites.",
    )
    parser.add_argument(
        "--case",
        action="append",
        dest="cases",
        metavar="NAME",
        help="Run one regression case; repeat to select multiple cases.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List suites and regression cases without running them.",
    )
    parser.add_argument(
        "--srcmove",
        type=Path,
        help="srcMove executable; overrides SRCMOVE_BIN and workspace discovery.",
    )
    parser.add_argument(
        "--srcdiff",
        type=Path,
        help="srcdiff executable; overrides SRCDIFF_BIN and workspace discovery.",
    )
    return parser.parse_args()


def discover_cases(suite: str) -> list[str]:
    root = REGRESSION_CASE_ROOTS[suite]
    if not root.is_dir():
        return []

    if suite == "xml":
        return sorted(path.name for path in root.iterdir() if path.is_dir())

    names: list[str] = []
    for path in root.iterdir():
        if not path.is_dir() or path.name == "__pycache__":
            continue
        if (path / "original").is_dir() and (path / "modified").is_dir():
            names.append(path.name)
            continue
        children = [child for child in path.iterdir() if child.is_file()]
        if any(child.stem == "original" for child in children) and any(
            child.stem == "modified" for child in children
        ):
            names.append(path.name)
    return sorted(names)


def print_inventory() -> None:
    for suite, description in SUITE_DESCRIPTIONS.items():
        if suite == "unit":
            print(f"{suite}: {description}")
            continue

        cases = discover_cases(suite)
        print(f"{suite}: {description} ({len(cases)} cases)")
        for case_name in cases:
            print(f"  {case_name}")


def select_regression_cases(
    suites: list[str], requested_cases: list[str]
) -> dict[str, list[str]]:
    available = {
        suite: set(discover_cases(suite))
        for suite in REGRESSION_CASE_ROOTS
        if suite in suites
    }
    selected = {suite: [] for suite in available}

    for case_name in requested_cases:
        matches = [suite for suite, cases in available.items() if case_name in cases]
        if not matches:
            raise ValueError(
                f"case not found in selected regression suites: {case_name}"
            )
        if len(matches) > 1:
            joined = ", ".join(matches)
            raise ValueError(
                f"case name is ambiguous across suites ({joined}): {case_name}; "
                "select one suite with --suite"
            )
        selected[matches[0]].append(case_name)

    return {suite: cases for suite, cases in selected.items() if cases}


def run_step(step: TestStep) -> bool:
    print()
    print(f"=== {step.name} ===", flush=True)
    print(command_text(step.command), flush=True)
    result = run_command(step.command, cwd=REPO_ROOT, capture_output=False)
    if result.returncode == 0:
        print(f"PASS {step.name}")
        return True
    print(f"FAIL {step.name} (exit code {result.returncode})")
    return False


def build_steps(
    args: argparse.Namespace,
    suites: list[str],
    selected_cases: dict[str, list[str]],
    srcmove: Path | None,
    srcdiff: Path | None,
) -> list[TestStep]:
    steps: list[TestStep] = []
    if args.build:
        steps.extend(
            [
                TestStep("configure", ["cmake", "-S", ".", "-B", "build", "-G", "Ninja"]),
                TestStep("build", ["ninja", "-C", "build"]),
            ]
        )

    if not args.cases and "unit" in suites:
        steps.append(
            TestStep(
                "unit",
                [
                    sys.executable,
                    "-m",
                    "unittest",
                    "discover",
                    "-s",
                    "test",
                    "-p",
                    "test_*.py",
                ],
            )
        )

    if "xml" in suites and (not args.cases or "xml" in selected_cases):
        assert srcmove is not None
        command = [
            sys.executable,
            "test/e2e_custom/run_tests.py",
            "--srcmove",
            str(srcmove),
        ]
        for case_name in selected_cases.get("xml", []):
            command.extend(["--case", case_name])
        steps.append(TestStep("xml regression", command))

    if "source" in suites and (not args.cases or "source" in selected_cases):
        assert srcmove is not None
        assert srcdiff is not None
        command = [
            sys.executable,
            "test/e2e_generated/run_tests.py",
            "--srcmove",
            str(srcmove),
            "--srcdiff",
            str(srcdiff),
        ]
        for case_name in selected_cases.get("source", []):
            command.extend(["--case", case_name])
        steps.append(TestStep("source regression", command))

    return steps


def main() -> int:
    args = parse_args()
    if args.list:
        print_inventory()
        return 0

    suites = list(dict.fromkeys(args.suite or SUITE_DESCRIPTIONS))
    if args.cases and "unit" in suites:
        suites.remove("unit")

    try:
        selected_cases = select_regression_cases(suites, args.cases or [])
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    needs_srcmove = any(suite in suites for suite in ("xml", "source"))
    needs_srcdiff = "source" in suites

    srcmove: Path | None = None
    if needs_srcmove:
        srcmove = (
            REPO_ROOT / "build" / "srcMove"
            if args.build
            else find_srcmove(REPO_ROOT, args.srcmove)
        )
        if not args.build and srcmove is None:
            print("error: srcMove not found; build it or pass --srcmove", file=sys.stderr)
            return 2

    srcdiff = find_srcdiff(REPO_ROOT, args.srcdiff) if needs_srcdiff else None
    if needs_srcdiff and srcdiff is None:
        print("error: srcdiff not found; build it or pass --srcdiff", file=sys.stderr)
        return 2

    if srcdiff is not None:
        print(f"using srcdiff: {srcdiff}")
    if srcmove is not None:
        print(f"using srcMove: {srcmove}")

    steps = build_steps(args, suites, selected_cases, srcmove, srcdiff)
    failures = sum(not run_step(step) for step in steps)

    print()
    print("=== Test Summary ===")
    print(f"steps run: {len(steps)}")
    print(f"failures : {failures}")
    print("benchmarks: excluded; run BigCloneBench or repository benchmarks separately")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
