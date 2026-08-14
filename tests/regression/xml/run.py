#!/usr/bin/env python3
# tests/regression/xml/run.py

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
TESTS_ROOT = SCRIPT_DIR.parents[1]
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from support.cases import (
    TEST_RESULTS_ROOT,
    CaseDefinitionError,
    XmlCaseSpec,
    discover_xml_cases,
)
from support.validation import (
    compare_xml_files_exact,
    load_json,
    validate_results,
)
from support.tooling import find_srcmove, format_process_failure, run_command


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run srcDiff XML regression cases.")
    parser.add_argument(
        "legacy_srcmove",
        nargs="?",
        type=Path,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--srcmove",
        type=Path,
        help="srcMove executable; overrides SRCMOVE_BIN and workspace discovery.",
    )
    parser.add_argument(
        "--case",
        action="append",
        dest="cases",
        metavar="NAME",
        help="Run one case; repeat to select multiple cases.",
    )
    parser.add_argument("--list", action="store_true", help="List cases and exit.")
    args = parser.parse_args()
    if args.legacy_srcmove is not None and args.srcmove is not None:
        parser.error("use either the legacy positional srcMove path or --srcmove, not both")
    return args


def run_case(srcmove_path: Path, case: XmlCaseSpec, out_root: Path):
    case_out_dir = out_root / case.name
    case_out_dir.mkdir(parents=True, exist_ok=True)

    srcmove_xml = case_out_dir / "srcmove.xml"
    results_json = case_out_dir / "results.json"

    cmd = [
        str(srcmove_path),
        str(case.input_xml),
        str(srcmove_xml),
        "--results",
        str(results_json),
    ]
    proc = run_command(cmd)
    return proc, srcmove_xml, results_json


def main() -> int:
    args = parse_args()
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parents[2]
    out_dir = TEST_RESULTS_ROOT / "xml"

    try:
        cases = discover_xml_cases()
    except CaseDefinitionError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    if args.list:
        for case in cases:
            print(case.name)
        return 0

    if args.cases:
        available = {case.name: case for case in cases}
        unknown = [name for name in args.cases if name not in available]
        if unknown:
            print(f"error: unknown case(s): {', '.join(unknown)}", file=sys.stderr)
            return 2
        cases = [available[name] for name in dict.fromkeys(args.cases)]

    srcmove_path = find_srcmove(repo_root, args.srcmove or args.legacy_srcmove)
    if srcmove_path is None:
        print("error: srcMove not found", file=sys.stderr)
        return 2

    out_dir.mkdir(parents=True, exist_ok=True)

    total = 0
    passed = 0
    failed = 0

    for case in cases:
        total += 1

        proc, srcmove_xml, results_json = run_case(srcmove_path, case, out_dir)

        if proc.returncode != 0:
            print(f"FAIL  {case.name}")
            for line in format_process_failure("srcMove", proc).splitlines():
                print(f"  {line}")
            failed += 1
            continue

        if not results_json.exists():
            print(f"FAIL  {case.name}")
            print("  missing output results json")
            failed += 1
            continue

        if not srcmove_xml.exists():
            print(f"FAIL  {case.name}")
            print("  missing output xml")
            failed += 1
            continue

        try:
            expected_json = load_json(case.expected_json)
            actual_results = load_json(results_json)

            from support.validation import assert_no_inline_xmlns

            failures: list[str] = []
            failures.extend(validate_results(expected_json, actual_results))
            failures.extend(assert_no_inline_xmlns(srcmove_xml))
            failures.extend(compare_xml_files_exact(case.expected_xml, srcmove_xml))
        except Exception as e:
            print(f"FAIL  {case.name}")
            print(f"  exception while validating: {e}")
            failed += 1
            continue

        if failures:
            print(f"FAIL  {case.name}")
            for msg in failures:
                print(f"  - {msg}")
            failed += 1
        else:
            print(f"PASS  {case.name}")
            passed += 1

    print()
    print(f"total={total} passed={passed} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
