#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
TEST_ROOT = SCRIPT_DIR.parent
if str(TEST_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_ROOT))

from testlib import (
    format_process_failure,
    load_json,
    run_command,
    validate_results,
)


def run_case(srcmove_path: Path, xml_file: Path, out_dir: Path):
    base = xml_file.stem
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

    xml_files = sorted(
        p for p in script_dir.glob("*.xml") if not p.name.endswith(".out.xml")
    )

    if not xml_files:
        print(f"No .xml test files found in {script_dir}.")
        return 0

    total = 0
    passed = 0
    failed = 0
    skipped = 0

    for xml_file in xml_files:
        total += 1
        expected_path = xml_file.with_suffix(".expected.json")

        if not expected_path.exists():
            print(f"SKIP  {xml_file.name}  (missing {expected_path.name})")
            skipped += 1
            continue

        proc, out_xml, out_json = run_case(srcmove_path, xml_file, out_dir)

        if proc.returncode != 0:
            print(f"FAIL  {xml_file.name}")
            for line in format_process_failure("srcMove", proc).splitlines():
                print(f"  {line}")
            failed += 1
            continue

        if not out_json.exists():
            print(f"FAIL  {xml_file.name}")
            print("  missing output results json")
            failed += 1
            continue

        try:
            expected = load_json(expected_path)
            results_json = load_json(out_json)
            failures = validate_results(expected, results_json)

            from testlib import assert_no_inline_xmlns

            failures.extend(assert_no_inline_xmlns(out_xml))
        except Exception as e:
            print(f"FAIL  {xml_file.name}")
            print(f"  exception while validating: {e}")
            failed += 1
            continue

        if failures:
            print(f"FAIL  {xml_file.name}")
            for msg in failures:
                print(f"  - {msg}")
            failed += 1
        else:
            print(f"PASS  {xml_file.name}")
            passed += 1

    print()
    print(f"total={total} passed={passed} failed={failed} skipped={skipped}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
