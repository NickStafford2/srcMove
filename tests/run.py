#!/usr/bin/env python3
"""Unified entry point for deterministic srcMove correctness tests."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path


TESTS_ROOT = Path(__file__).resolve().parent
REPO_ROOT = TESTS_ROOT.parent
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from support.cases import REGRESSION_SUITES, regression_case_names
from support.tooling import command_text, find_srcdiff, find_srcmove, run_command


SUITE_DESCRIPTIONS = {
    "unit": "all Python unit tests",
    "repository-analysis": "focused repository-analysis unit tests",
    "xml": "checked-in srcDiff XML regression fixtures",
    "source": "checked-in source pairs regenerated through srcdiff",
}

DEFAULT_SUITES = ("unit", "xml", "source")


@dataclass(frozen=True)
class TestStep:
    name: str
    command: list[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run srcMove's deterministic correctness tests."
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


def print_inventory() -> None:
    for suite, description in SUITE_DESCRIPTIONS.items():
        if suite not in REGRESSION_SUITES:
            print(f"{suite}: {description}")
            continue

        cases = regression_case_names(suite)
        print(f"{suite}: {description} ({len(cases)} cases)")
        for case_name in cases:
            print(f"  {case_name}")


def select_regression_cases(
    suites: list[str], requested_cases: list[str]
) -> dict[str, list[str]]:
    available = {
        suite: set(regression_case_names(suite))
        for suite in REGRESSION_SUITES
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


def test_steps(
    args: argparse.Namespace,
    suites: list[str],
    selected_cases: dict[str, list[str]],
    srcmove: Path | None,
    srcdiff: Path | None,
) -> list[TestStep]:
    steps: list[TestStep] = []
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
                    "tests/unit",
                    "-t",
                    ".",
                    "-p",
                    "test_*.py",
                ],
            )
        )

    if not args.cases and "repository-analysis" in suites:
        steps.append(
            TestStep(
                "repository-analysis unit",
                [
                    sys.executable,
                    "-m",
                    "unittest",
                    "discover",
                    "-s",
                    "tests/unit/repository_analysis",
                    "-t",
                    ".",
                    "-p",
                    "test_*.py",
                ],
            )
        )

    if "xml" in suites and (not args.cases or "xml" in selected_cases):
        assert srcmove is not None
        command = [
            sys.executable,
            "tests/regression/xml/run.py",
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
            "tests/regression/source/run.py",
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
        try:
            print_inventory()
            return 0
        except ValueError as error:
            print(f"error: {error}", file=sys.stderr)
            return 2

    suites = list(dict.fromkeys(args.suite or DEFAULT_SUITES))
    if args.cases:
        suites = [
            suite
            for suite in suites
            if suite not in ("unit", "repository-analysis")
        ]

    try:
        selected_cases = select_regression_cases(suites, args.cases or [])
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    needs_srcmove = any(suite in suites for suite in ("xml", "source"))
    needs_srcdiff = "source" in suites

    srcmove: Path | None = None
    if needs_srcmove:
        srcmove = find_srcmove(REPO_ROOT, args.srcmove)
        if srcmove is None:
            print("error: srcMove not found; run make build or pass --srcmove", file=sys.stderr)
            return 2

    srcdiff = find_srcdiff(REPO_ROOT, args.srcdiff) if needs_srcdiff else None
    if needs_srcdiff and srcdiff is None:
        print("error: srcdiff not found; build it or pass --srcdiff", file=sys.stderr)
        return 2

    if srcdiff is not None:
        print(f"using srcdiff: {srcdiff}")
    if srcmove is not None:
        print(f"using srcMove: {srcmove}")

    steps = test_steps(args, suites, selected_cases, srcmove, srcdiff)
    failures = sum(not run_step(step) for step in steps)

    print()
    print("=== Test Summary ===")
    print(f"steps run: {len(steps)}")
    print(f"failures : {failures}")
    print("benchmarks: excluded; run BigCloneBench or repository benchmarks separately")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
