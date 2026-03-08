#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


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


def run_command(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        text=True,
        capture_output=True,
    )


def format_process_failure(
    label: str, result: subprocess.CompletedProcess[str], extra: str = ""
) -> str:
    parts: list[str] = [f"{label} failed"]
    if extra:
        parts.append(extra)
    parts.append(f"exit code: {result.returncode}")

    stdout = result.stdout.strip()
    stderr = result.stderr.strip()

    if stdout:
        parts.append("stdout:")
        parts.extend(f"  {line}" for line in stdout.splitlines())

    if stderr:
        parts.append("stderr:")
        parts.extend(f"  {line}" for line in stderr.splitlines())

    return "\n".join(parts)


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


def expect_type(value: Any, expected_type: type, what: str) -> None:
    if not isinstance(value, expected_type):
        raise RuntimeError(f"{what} must be a {expected_type.__name__}")


def load_oracle(case_dir: Path) -> dict[str, Any]:
    oracle_path = case_dir / "oracle.json"
    if not oracle_path.is_file():
        raise RuntimeError(f"missing oracle.json: {oracle_path}")

    with oracle_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise RuntimeError(f"oracle.json root must be an object: {oracle_path}")

    if "move_count" in data and not isinstance(data["move_count"], int):
        raise RuntimeError(
            f"oracle.json field 'move_count' is not an int: {oracle_path}"
        )

    if "moves" in data:
        expect_type(data["moves"], list, f"{oracle_path}: 'moves'")
        for i, move in enumerate(data["moves"], start=1):
            expect_type(move, dict, f"{oracle_path}: moves[{i}]")

            for key in ("from_xpaths", "to_xpaths", "from_files", "to_files"):
                if key in move:
                    expect_type(move[key], list, f"{oracle_path}: moves[{i}].{key}")
                    for j, item in enumerate(move[key], start=1):
                        expect_type(
                            item,
                            str,
                            f"{oracle_path}: moves[{i}].{key}[{j}]",
                        )

    return data


def load_results(results_path: Path) -> dict[str, Any]:
    if not results_path.is_file():
        raise RuntimeError(f"missing results file: {results_path}")

    with results_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise RuntimeError(f"results.json root must be an object: {results_path}")

    if "move_count" not in data:
        raise RuntimeError(f"results.json missing 'move_count': {results_path}")

    if not isinstance(data["move_count"], int):
        raise RuntimeError(
            f"results.json field 'move_count' is not an int: {results_path}"
        )

    moves = data.get("moves", [])
    if not isinstance(moves, list):
        raise RuntimeError(f"results.json field 'moves' is not a list: {results_path}")

    return data


def normalize_xpath_list(values: list[str] | None) -> list[str]:
    if not values:
        return []
    return sorted(str(v) for v in values)


def xpaths_to_files(xpaths: list[str] | None) -> list[str]:
    if not xpaths:
        return []

    files: list[str] = []
    seen: set[str] = set()

    needle = '[@filename="'
    for xpath in xpaths:
        start = xpath.find(needle)
        if start == -1:
            continue
        start += len(needle)
        end = xpath.find('"]', start)
        if end == -1:
            continue
        filename = xpath[start:end]
        if filename not in seen:
            seen.add(filename)
            files.append(filename)

    return sorted(files)


def normalize_move_record(move: dict[str, Any]) -> dict[str, list[str]]:
    from_xpaths = normalize_xpath_list(move.get("from_xpaths"))
    to_xpaths = normalize_xpath_list(move.get("to_xpaths"))

    from_files = normalize_xpath_list(move.get("from_files"))
    to_files = normalize_xpath_list(move.get("to_files"))

    if not from_files:
        from_files = xpaths_to_files(from_xpaths)
    if not to_files:
        to_files = xpaths_to_files(to_xpaths)

    return {
        "from_xpaths": from_xpaths,
        "to_xpaths": to_xpaths,
        "from_files": from_files,
        "to_files": to_files,
    }


def move_matches_expectation(
    actual: dict[str, list[str]], expected: dict[str, Any]
) -> tuple[bool, str]:
    for key in ("from_files", "to_files", "from_xpaths", "to_xpaths"):
        if key not in expected:
            continue

        expected_list = sorted(str(v) for v in expected[key])
        actual_list = actual[key]

        if actual_list != expected_list:
            return (
                False,
                f"{key}: expected {expected_list!r}, got {actual_list!r}",
            )

    return True, ""


def validate_moves(oracle: dict[str, Any], results: dict[str, Any]) -> list[str]:
    failures: list[str] = []

    expected_move_count = oracle.get("move_count")
    actual_move_count = results.get("move_count")

    if expected_move_count is not None and actual_move_count != expected_move_count:
        failures.append(
            f"move_count mismatch: expected {expected_move_count}, got {actual_move_count}"
        )

    expected_moves = oracle.get("moves")
    actual_moves_raw = results.get("moves", [])

    if expected_moves is None:
        return failures

    actual_moves = [normalize_move_record(m) for m in actual_moves_raw]

    used_indices: set[int] = set()

    for expected_index, expected_move in enumerate(expected_moves, start=1):
        match_index = None
        mismatch_reasons: list[str] = []

        for actual_index, actual_move in enumerate(actual_moves):
            if actual_index in used_indices:
                continue

            ok, reason = move_matches_expectation(actual_move, expected_move)
            if ok:
                match_index = actual_index
                break
            mismatch_reasons.append(
                f"candidate actual move {actual_index + 1} mismatch: {reason}"
            )

        if match_index is None:
            details = (
                "; ".join(mismatch_reasons[:4]) if mismatch_reasons else "no moves"
            )
            failures.append(
                f"expected move {expected_index} not found"
                f"{': ' + details if details else ''}"
            )
            continue

        used_indices.add(match_index)

    return failures


def run_case(
    case: CaseSpec, repo_root: Path, srcdiff_bin: str, srcmove_bin: str
) -> CaseResult:
    name = case.name
    case_dir = case.case_dir
    diff_xml = case_dir / "diff.xml"
    diff_new_xml = case_dir / "diff_new.xml"
    results_json = case_dir / "results.json"

    try:
        oracle = load_oracle(case_dir)
    except Exception as e:
        return CaseResult(
            name=name,
            ok=False,
            expected_move_count=None,
            actual_move_count=None,
            message=str(e),
        )

    expected_move_count = oracle.get("move_count")

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
            message=format_process_failure(
                "srcdiff", srcdiff_result, extra=f"case type: {case_kind}"
            ),
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
            message=format_process_failure("srcMove", srcmove_result),
        )

    try:
        results = load_results(results_json)
        failures = validate_moves(oracle, results)
    except Exception as e:
        return CaseResult(
            name=name,
            ok=False,
            expected_move_count=expected_move_count,
            actual_move_count=None,
            message=str(e),
        )

    actual_move_count = results["move_count"]

    if failures:
        return CaseResult(
            name=name,
            ok=False,
            expected_move_count=expected_move_count,
            actual_move_count=actual_move_count,
            message=" | ".join(failures),
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
