#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


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


def run_command(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def is_archive_case(case_dir: Path) -> bool:
    return (case_dir / "original").is_dir() and (case_dir / "modified").is_dir()


def find_single_file_pair(case_dir: Path) -> tuple[Path, Path] | None:
    originals = []
    modifieds = []

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


def find_cases(archives_root: Path) -> list[CaseSpec]:
    out: list[CaseSpec] = []

    for child in sorted(archives_root.iterdir()):
        if not child.is_dir():
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
            original_file, modified_file = pair
            out.append(
                CaseSpec(
                    name=child.name,
                    case_dir=child,
                    original=original_file,
                    modified=modified_file,
                    is_archive=False,
                )
            )

    return out


def load_expected_move_count(case_dir: Path) -> int:
    oracle_path = case_dir / "oracle.json"
    if not oracle_path.is_file():
        raise RuntimeError(f"missing oracle.json: {oracle_path}")

    with oracle_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    move_count = None

    if "move_count" in data:
        move_count = data["move_count"]
    elif "moves" in data:
        move_count = data["moves"]
    else:
        raise RuntimeError(
            f"oracle.json missing 'move_count' or legacy 'moves': {oracle_path}"
        )

    if not isinstance(move_count, int):
        raise RuntimeError(f"oracle.json move count field is not an int: {oracle_path}")

    return move_count


def load_actual_move_count(results_path: Path) -> int:
    if not results_path.is_file():
        raise RuntimeError(f"missing results file: {results_path}")

    with results_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if "move_count" not in data:
        raise RuntimeError(f"results.json missing 'move_count': {results_path}")

    move_count = data["move_count"]
    if not isinstance(move_count, int):
        raise RuntimeError(
            f"results.json field 'move_count' is not an int: {results_path}"
        )

    return move_count


def run_case(
    case: CaseSpec, repo_root: Path, srcdiff_bin: str, srcmove_bin: str
) -> CaseResult:
    name = case.name
    case_dir = case.case_dir
    diff_xml = case_dir / "diff.xml"
    diff_new_xml = case_dir / "diff_new.xml"
    results_json = case_dir / "results.json"

    try:
        expected_move_count = load_expected_move_count(case_dir)
    except Exception as e:
        return CaseResult(
            name=name,
            ok=False,
            expected_move_count=None,
            actual_move_count=None,
            message=str(e),
        )

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
            name=name,
            ok=False,
            expected_move_count=expected_move_count,
            actual_move_count=None,
            message=f"srcdiff failed ({case_kind} case)",
        )

    if not diff_xml.is_file():
        return CaseResult(
            name=name,
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
            name=name,
            ok=False,
            expected_move_count=expected_move_count,
            actual_move_count=None,
            message="srcMove failed",
        )

    try:
        actual_move_count = load_actual_move_count(results_json)
    except Exception as e:
        return CaseResult(
            name=name,
            ok=False,
            expected_move_count=expected_move_count,
            actual_move_count=None,
            message=str(e),
        )

    if actual_move_count != expected_move_count:
        return CaseResult(
            name=name,
            ok=False,
            expected_move_count=expected_move_count,
            actual_move_count=actual_move_count,
            message="move count mismatch",
        )

    return CaseResult(
        name=name,
        ok=True,
        expected_move_count=expected_move_count,
        actual_move_count=actual_move_count,
        message="",
    )


def main() -> int:
    script_path = Path(__file__).resolve()
    archives_root = script_path.parent
    repo_root = archives_root.parent.parent

    srcdiff_bin = shutil.which("srcdiff")
    if srcdiff_bin is None:
        print("error: srcdiff not found on PATH", file=sys.stderr)
        return 1

    srcmove_bin = repo_root / "build" / "srcMove"
    if not srcmove_bin.is_file():
        print(f"error: srcMove binary not found: {srcmove_bin}", file=sys.stderr)
        return 1

    try:
        cases = find_cases(archives_root)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if not cases:
        print(f"error: no test cases found under {archives_root}", file=sys.stderr)
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
                f"[FAIL] {result.name}: {result.message}"
                f" (expected={result.expected_move_count}, actual={result.actual_move_count})"
            )

    failed = [r for r in results if not r.ok]

    print("\n=== SUMMARY ===")
    print(f"passed: {len(results) - len(failed)}")
    print(f"failed: {len(failed)}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
