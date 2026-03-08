#!/usr/bin/env python3
from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
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


@dataclass
class CaseSpec:
    name: str
    case_dir: Path
    original: Path
    modified: Path
    is_archive: bool


@dataclass
class CaseResult:
    name: str
    ok: bool
    expected_move_count: int | None
    actual_move_count: int | None
    message: str = ""


def is_archive_case(case_dir: Path) -> bool:
    return (case_dir / "original").is_dir() and (case_dir / "modified").is_dir()


def find_single_file_pair(case_dir: Path) -> tuple[Path, Path] | None:
    originals: list[Path] = []
    modifieds: list[Path] = []

    for child in case_dir.iterdir():
        if not child.is_file():
            continue
        if child.stem == "original":
            originals.append(child)
        elif child.stem == "modified":
            modifieds.append(child)

    if len(originals) == 1 and len(modifieds) == 1:
        return originals[0], modifieds[0]

    if len(originals) == 0 and len(modifieds) == 0:
        return None

    raise RuntimeError(
        f"{case_dir}: expected exactly one original.* and one modified.* file"
    )


def find_cases(root: Path) -> list[CaseSpec]:
    out: list[CaseSpec] = []

    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        if child.name == "__pycache__":
            continue

        if is_archive_case(child):
            out.append(
                CaseSpec(
                    name=child.name,
                    case_dir=child,
                    original=child / "original",
                    modified=child / "modified",
                    is_archive=True,
                )
            )
            continue

        pair = find_single_file_pair(child)
        if pair is not None:
            out.append(
                CaseSpec(
                    name=child.name,
                    case_dir=child,
                    original=pair[0],
                    modified=pair[1],
                    is_archive=False,
                )
            )

    return out


def run_case(
    case: CaseSpec,
    repo_root: Path,
    srcdiff_bin: str,
    srcmove_bin: str,
) -> CaseResult:
    diff_xml = case.case_dir / "diff.xml"
    diff_new_xml = case.case_dir / "diff_new.xml"
    results_json = case.case_dir / "results.json"
    oracle_path = case.case_dir / "oracle.json"

    try:
        expected = load_json(oracle_path)
    except Exception as e:
        return CaseResult(
            name=case.name,
            ok=False,
            expected_move_count=None,
            actual_move_count=None,
            message=str(e),
        )

    expected_move_count = expected.get("move_count")

    for path in (diff_xml, diff_new_xml, results_json):
        if path.exists():
            path.unlink()

    srcdiff_cmd = [
        srcdiff_bin,
        str(case.original),
        str(case.modified),
        "-o",
        str(diff_xml),
    ]
    srcdiff_result = run_command(srcdiff_cmd, cwd=repo_root)

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

    if not diff_xml.is_file():
        return CaseResult(
            name=case.name,
            ok=False,
            expected_move_count=expected_move_count,
            actual_move_count=None,
            message="srcdiff did not create diff.xml",
        )

    srcmove_cmd = [
        srcmove_bin,
        str(diff_xml),
        str(diff_new_xml),
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
    script_path = Path(__file__).resolve()
    cases_root = script_path.parent
    repo_root = cases_root.parent.parent

    srcdiff_bin = shutil.which("srcdiff")
    if srcdiff_bin is None:
        print("error: srcdiff not found on PATH", file=sys.stderr)
        return 1

    srcmove_bin = repo_root / "build" / "srcMove"
    if not srcmove_bin.is_file():
        print(f"error: srcMove binary not found: {srcmove_bin}", file=sys.stderr)
        return 1

    try:
        cases = find_cases(cases_root)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if not cases:
        print(f"error: no test cases found under {cases_root}", file=sys.stderr)
        return 1

    print(f"Found {len(cases)} case(s)")

    results: list[CaseResult] = []

    for case in cases:
        result = run_case(
            case=case,
            repo_root=repo_root,
            srcdiff_bin=srcdiff_bin,
            srcmove_bin=str(srcmove_bin),
        )
        results.append(result)

        if result.ok:
            print(f"[PASS] {result.name}: move_count={result.actual_move_count}")
        else:
            print(
                f"[FAIL] {result.name}: {result.message} "
                f"(expected={result.expected_move_count}, actual={result.actual_move_count})"
            )

    failed = [r for r in results if not r.ok]

    print("\n=== SUMMARY ===")
    print(f"passed: {len(results) - len(failed)}")
    print(f"failed: {len(failed)}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
