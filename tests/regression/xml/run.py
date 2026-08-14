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


def run_case(srcmove_path: Path, xml_file: Path, out_root: Path):
    case_name = xml_file.parent.name
    case_out_dir = out_root / case_name
    case_out_dir.mkdir(parents=True, exist_ok=True)

    out_xml = case_out_dir / "output.xml"
    out_json = case_out_dir / "results.json"

    cmd = [
        str(srcmove_path),
        str(xml_file),
        str(out_xml),
        "--results",
        str(out_json),
    ]
    proc = run_command(cmd)
    return proc, out_xml, out_json


def is_input_xml(path: Path) -> bool:
    if path.suffix != ".xml":
        return False

    excluded_suffixes = (
        ".out.xml",
        ".expected.xml",
    )

    return not any(path.name.endswith(suffix) for suffix in excluded_suffixes)


def main() -> int:
    args = parse_args()
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parents[2]
    out_dir = script_dir / "test_out"

    cases_dir = script_dir / "cases"
    if not cases_dir.is_dir():
        print(f"error: cases directory not found: {cases_dir}", file=sys.stderr)
        return 2

    case_dirs = sorted(p for p in cases_dir.iterdir() if p.is_dir())

    if not case_dirs:
        print(f"No test case directories found in {cases_dir}.")
        return 0

    if args.list:
        for case_dir in case_dirs:
            print(case_dir.name)
        return 0

    if args.cases:
        available = {case_dir.name: case_dir for case_dir in case_dirs}
        unknown = [name for name in args.cases if name not in available]
        if unknown:
            print(f"error: unknown case(s): {', '.join(unknown)}", file=sys.stderr)
            return 2
        case_dirs = [available[name] for name in dict.fromkeys(args.cases)]

    srcmove_path = find_srcmove(repo_root, args.srcmove or args.legacy_srcmove)
    if srcmove_path is None:
        print("error: srcMove not found", file=sys.stderr)
        return 2

    out_dir.mkdir(exist_ok=True)

    total = 0
    passed = 0
    failed = 0
    skipped = 0

    for case_dir in case_dirs:
        total += 1

        case_name = case_dir.name
        xml_file = case_dir / "input.xml"
        expected_json_path = case_dir / "expected.json"
        expected_xml_path = case_dir / "expected.xml"

        missing_files: list[str] = []
        if not xml_file.exists():
            missing_files.append("input.xml")
        if not expected_json_path.exists():
            missing_files.append("expected.json")
        if not expected_xml_path.exists():
            missing_files.append("expected.xml")

        if missing_files:
            print(f"SKIP  {case_name}  (missing {', '.join(missing_files)})")
            skipped += 1
            continue

        proc, out_xml, out_json = run_case(srcmove_path, xml_file, out_dir)

        if proc.returncode != 0:
            print(f"FAIL  {case_name}")
            for line in format_process_failure("srcMove", proc).splitlines():
                print(f"  {line}")
            failed += 1
            continue

        if not out_json.exists():
            print(f"FAIL  {case_name}")
            print("  missing output results json")
            failed += 1
            continue

        if not out_xml.exists():
            print(f"FAIL  {case_name}")
            print("  missing output xml")
            failed += 1
            continue

        try:
            expected_json = load_json(expected_json_path)
            results_json = load_json(out_json)

            from support.validation import assert_no_inline_xmlns

            failures: list[str] = []
            failures.extend(validate_results(expected_json, results_json))
            failures.extend(assert_no_inline_xmlns(out_xml))
            failures.extend(compare_xml_files_exact(expected_xml_path, out_xml))
        except Exception as e:
            print(f"FAIL  {case_name}")
            print(f"  exception while validating: {e}")
            failed += 1
            continue

        if failures:
            print(f"FAIL  {case_name}")
            for msg in failures:
                print(f"  - {msg}")
            failed += 1
        else:
            print(f"PASS  {case_name}")
            passed += 1

    print()
    print(f"total={total} passed={passed} failed={failed} skipped={skipped}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
