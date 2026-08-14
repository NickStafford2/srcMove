#!/usr/bin/env python3
# tests/regression/source/run.py
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
TESTS_ROOT = SCRIPT_DIR.parents[1]
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from support.cases import CaseDefinitionError, SourceCaseSpec, discover_source_cases
from support.validation import (
    assert_no_inline_xmlns,
    load_json,
    print_case_fail,
    print_case_pass,
    validate_results,
)
from support.tooling import find_srcdiff, find_srcmove, format_process_failure, run_command


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run source-pair regression cases.")
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
    parser.add_argument(
        "--case",
        action="append",
        dest="cases",
        metavar="NAME",
        help="Run one case; repeat to select multiple cases.",
    )
    parser.add_argument("--list", action="store_true", help="List cases and exit.")
    return parser.parse_args()


@dataclass
class CaseResult:
    name: str
    ok: bool
    expected_move_count: int | None
    actual_move_count: int | None
    message: str = ""


def prepare_srcdiff_inputs(case: SourceCaseSpec) -> tuple[str, str, Path | None]:
    if case.is_archive:
        return str(case.original), str(case.modified), None

    return case.original.name, case.modified.name, case.case_dir


def run_case(
    case: SourceCaseSpec,
    repo_root: Path,
    srcdiff_bin: str,
    srcmove_bin: str,
) -> CaseResult:
    srcdiff_xml = case.case_dir / "srcdiff.xml"
    srcmove_xml = case.case_dir / "srcmove.xml"
    results_json = case.case_dir / "results.json"

    try:
        expected = load_json(case.oracle_json)
    except Exception as e:
        return CaseResult(
            name=case.name,
            ok=False,
            expected_move_count=None,
            actual_move_count=None,
            message=str(e),
        )

    expected_move_count = expected.get("move_count")

    for path in (srcdiff_xml, srcmove_xml, results_json):
        if path.exists():
            path.unlink()

    try:
        (
            srcdiff_original,
            srcdiff_modified,
            srcdiff_cwd,
        ) = prepare_srcdiff_inputs(case)
        srcdiff_cmd = [
            srcdiff_bin,
            srcdiff_original,
            srcdiff_modified,
            "-o",
            str(srcdiff_xml),
        ]
        srcdiff_result = run_command(srcdiff_cmd, cwd=srcdiff_cwd or repo_root)
    except Exception as e:
        return CaseResult(
            name=case.name,
            ok=False,
            expected_move_count=expected_move_count,
            actual_move_count=None,
            message=str(e),
        )

    if srcdiff_result.returncode != 0:
        case_kind = "archive" if case.is_archive else "single-file"
        return CaseResult(
            name=case.name,
            ok=False,
            expected_move_count=expected_move_count,
            actual_move_count=None,
            message=format_process_failure(
                "srcdiff",
                srcdiff_result,
                extra=f"case type: {case_kind}",
            ),
        )

    if not srcdiff_xml.is_file():
        return CaseResult(
            name=case.name,
            ok=False,
            expected_move_count=expected_move_count,
            actual_move_count=None,
            message="srcdiff did not create srcdiff.xml",
        )

    srcmove_cmd = [
        srcmove_bin,
        str(srcdiff_xml),
        str(srcmove_xml),
        "--results",
        str(results_json),
    ]
    srcmove_result = run_command(srcmove_cmd, cwd=repo_root)

    if srcmove_result.returncode != 0:
        return CaseResult(
            name=case.name,
            ok=False,
            expected_move_count=expected_move_count,
            actual_move_count=None,
            message=format_process_failure("srcMove", srcmove_result),
        )

    try:
        results = load_json(results_json)
        failures = validate_results(expected, results)
        failures.extend(assert_no_inline_xmlns(srcmove_xml))
    except Exception as e:
        return CaseResult(
            name=case.name,
            ok=False,
            expected_move_count=expected_move_count,
            actual_move_count=None,
            message=str(e),
        )

    actual_move_count = results.get("move_count")

    if failures:
        return CaseResult(
            name=case.name,
            ok=False,
            expected_move_count=expected_move_count,
            actual_move_count=actual_move_count,
            message=" | ".join(failures),
        )

    return CaseResult(
        name=case.name,
        ok=True,
        expected_move_count=expected_move_count,
        actual_move_count=actual_move_count,
    )


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[3]

    try:
        cases = discover_source_cases()
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

    srcdiff_bin = find_srcdiff(repo_root, args.srcdiff)
    if srcdiff_bin is None:
        print("error: srcdiff not found", file=sys.stderr)
        return 2

    srcmove_bin = find_srcmove(repo_root, args.srcmove)
    if srcmove_bin is None:
        print("error: srcMove not found", file=sys.stderr)
        return 2

    print(f"Found {len(cases)} case(s)")

    results: list[CaseResult] = []

    for case in cases:
        result = run_case(
            case=case,
            repo_root=repo_root,
            srcdiff_bin=str(srcdiff_bin),
            srcmove_bin=str(srcmove_bin),
        )
        results.append(result)

        if result.ok:
            print_case_pass(result.name, result.actual_move_count)
        else:
            print_case_fail(
                result.name,
                result.message,
                expected=result.expected_move_count,
                actual=result.actual_move_count,
            )

    failed = [r for r in results if not r.ok]

    print("\n=== SUMMARY ===")
    print(f"passed: {len(results) - len(failed)}")
    print(f"failed: {len(failed)}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
