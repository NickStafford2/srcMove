#!/usr/bin/env python3
# test/e2e_custom/run_tests.py

from __future__ import annotations

import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
TEST_ROOT = SCRIPT_DIR.parent
if str(TEST_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_ROOT))

from testlib import (
    compare_xml_files_exact,
    format_process_failure,
    load_json,
    run_command,
    validate_results,
)


def run_case(srcmove_path: Path, xml_file: Path, out_dir: Path):
    base = xml_file.parent.name
    out_xml = out_dir / f"{base}.out.xml"
    out_json = out_dir / f"{base}.results.json"

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
    script_dir = Path(__file__).resolve().parent
    out_dir = script_dir / "test_out"

    if len(sys.argv) > 1:
        srcmove_path = Path(sys.argv[1]).resolve()
    else:
        srcmove_path = (Path(os.getcwd()) / "build" / "srcMove").resolve()

    if not srcmove_path.exists():
        print(f"error: srcMove not found at {srcmove_path}", file=sys.stderr)
        return 2

    out_dir.mkdir(exist_ok=True)

    cases_dir = script_dir / "cases"
    if not cases_dir.is_dir():
        print(f"error: cases directory not found: {cases_dir}", file=sys.stderr)
        return 2

    case_dirs = sorted(p for p in cases_dir.iterdir() if p.is_dir())

    if not case_dirs:
        print(f"No test case directories found in {cases_dir}.")
        return 0

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

            from testlib import assert_no_inline_xmlns

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
