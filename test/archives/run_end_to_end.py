#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


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


def find_case_dirs(archives_root: Path) -> list[Path]:
    out: list[Path] = []

    for child in sorted(archives_root.iterdir()):
        if not child.is_dir():
            continue

        if (child / "original").is_dir() and (child / "modified").is_dir():
            out.append(child)

    return out


def load_expected_move_count(case_dir: Path) -> int:
    oracle_path = case_dir / "oracle.json"
    if not oracle_path.is_file():
        raise RuntimeError(f"missing oracle.json: {oracle_path}")

    with oracle_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if "move_count" not in data:
        raise RuntimeError(f"oracle.json missing 'move_count': {oracle_path}")

    move_count = data["move_count"]
    if not isinstance(move_count, int):
        raise RuntimeError(
            f"oracle.json field 'move_count' is not an int: {oracle_path}"
        )

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
    case_dir: Path, repo_root: Path, srcdiff_bin: str, srcmove_bin: str
) -> CaseResult:
    name = case_dir.name
    original_dir = case_dir / "original"
    modified_dir = case_dir / "modified"
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
        str(original_dir),
        str(modified_dir),
        "-o",
        str(diff_xml),
    ]
    srcdiff_result = run_command(srcdiff_cmd, cwd=repo_root)

    if srcdiff_result.returncode != 0:
        return CaseResult(
            name=name,
            ok=False,
            expected_move_count=expected_move_count,
            actual_move_count=None,
            message="srcdiff failed",
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

    case_dirs = find_case_dirs(archives_root)
    if not case_dirs:
        print(f"error: no archive cases found under {archives_root}", file=sys.stderr)
        return 1

    print(f"Found {len(case_dirs)} archive case(s)")

    results: list[CaseResult] = []

    for case_dir in case_dirs:
        result = run_case(
            case_dir=case_dir,
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
