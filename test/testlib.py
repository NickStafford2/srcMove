from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def run_command(
    cmd: list[str], cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd is not None else None,
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


def compare_scalar(actual: Any, expected: Any, key: str, failures: list[str]) -> None:
    if actual != expected:
        failures.append(f"{key}: expected {expected!r}, got {actual!r}")


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


def normalize_move_record(move: dict[str, Any]) -> dict[str, list[str] | int | None]:
    from_xpaths = normalize_xpath_list(move.get("from_xpaths"))
    to_xpaths = normalize_xpath_list(move.get("to_xpaths"))

    return {
        "move_id": move.get("move_id"),
        "from_xpaths": from_xpaths,
        "to_xpaths": to_xpaths,
        "from_files": xpaths_to_files(from_xpaths),
        "to_files": xpaths_to_files(to_xpaths),
        "from_raw_texts": sorted(str(v) for v in move.get("from_raw_texts", [])),
        "to_raw_texts": sorted(str(v) for v in move.get("to_raw_texts", [])),
    }


def move_matches_expectation(
    actual: dict[str, list[str] | int | None], expected: dict[str, Any]
) -> tuple[bool, str]:
    scalar_keys = ("move_id",)
    list_keys = (
        "from_files",
        "to_files",
        "from_xpaths",
        "to_xpaths",
        "from_raw_texts",
        "to_raw_texts",
    )

    for key in scalar_keys:
        if key not in expected:
            continue

        if actual[key] != expected[key]:
            return False, f"{key}: expected {expected[key]!r}, got {actual[key]!r}"

    for key in list_keys:
        if key not in expected:
            continue

        expected_list = sorted(str(v) for v in expected[key])
        actual_list = actual[key]

        if actual_list != expected_list:
            return False, f"{key}: expected {expected_list!r}, got {actual_list!r}"

    return True, ""


def check_summary_fields(
    results_json: dict[str, Any], expected: dict[str, Any]
) -> list[str]:
    failures: list[str] = []

    summary_checks = {
        "move_count": results_json.get("move_count"),
        "annotated_regions": results_json.get("annotated_regions"),
        "regions_total": results_json.get("regions_total"),
        "candidates_total": results_json.get("candidates_total"),
        "groups_total": results_json.get("groups_total"),
    }

    for key, actual_value in summary_checks.items():
        if key in expected:
            compare_scalar(actual_value, expected[key], key, failures)

    return failures


def validate_moves(expected: dict[str, Any], results: dict[str, Any]) -> list[str]:
    failures: list[str] = []

    expected_moves = expected.get("moves")
    if expected_moves is None:
        return failures

    actual_moves_raw = results.get("moves", [])
    if not isinstance(actual_moves_raw, list):
        failures.append("results.json field 'moves' is not a list")
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
            failures.append(f"expected move {expected_index} not found: {details}")
            continue

        used_indices.add(match_index)

    return failures


def validate_results(
    expected: dict[str, Any], results_json: dict[str, Any]
) -> list[str]:
    failures: list[str] = []
    failures.extend(check_summary_fields(results_json, expected))
    failures.extend(validate_moves(expected, results_json))
    return failures
