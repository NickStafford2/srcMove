# test/testlib.py
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET


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
    required_move_keys = (
        "move_id",
        "from_xpaths",
        "to_xpaths",
        "from_raw_texts",
        "to_raw_texts",
    )

    for key in required_move_keys:
        if key not in expected:
            return False, f"expected move missing required field {key!r}"

    if actual["move_id"] != expected["move_id"]:
        return (
            False,
            f"move_id: expected {expected['move_id']!r}, got {actual['move_id']!r}",
        )

    for key in ("from_xpaths", "to_xpaths", "from_raw_texts", "to_raw_texts"):
        expected_list = sorted(str(v) for v in expected[key])
        actual_list = actual[key]

        if actual_list != expected_list:
            return False, f"{key}: expected {expected_list!r}, got {actual_list!r}"

    return True, ""


def check_summary_fields(
    results_json: dict[str, Any], expected: dict[str, Any]
) -> list[str]:
    failures: list[str] = []

    required_top_level_keys = (
        "move_count",
        "moves",
        "annotated_regions",
        "regions_total",
        "candidates_total",
        "groups_total",
    )

    for key in required_top_level_keys:
        if key not in expected:
            failures.append(f"expected.json missing required field {key!r}")
        if key not in results_json:
            failures.append(f"results.json missing required field {key!r}")

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

    if "moves" not in expected:
        failures.append("expected.json missing required field 'moves'")
        return failures

    if "moves" not in results:
        failures.append("results.json missing required field 'moves'")
        return failures

    expected_moves = expected["moves"]
    actual_moves_raw = results["moves"]

    if not isinstance(expected_moves, list):
        failures.append("expected.json field 'moves' is not a list")
        return failures

    if not isinstance(actual_moves_raw, list):
        failures.append("results.json field 'moves' is not a list")
        return failures

    if len(actual_moves_raw) != len(expected_moves):
        failures.append(
            f"moves length: expected {len(expected_moves)}, got {len(actual_moves_raw)}"
        )

    actual_moves = [normalize_move_record(m) for m in actual_moves_raw]
    used_indices: set[int] = set()

    for expected_index, expected_move in enumerate(expected_moves, start=1):
        if not isinstance(expected_move, dict):
            failures.append(f"expected.json moves[{expected_index}] is not an object")
            continue

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


def assert_no_inline_xmlns(xml_path: Path) -> list[str]:
    tree = ET.parse(xml_path)
    root = tree.getroot()

    failures: list[str] = []

    for node in root.iter():
        tag = node.tag.split("}")[-1]

        if tag in ("delete", "insert") and "xmlns" in node.attrib:
            failures.append(f"{tag} node contains inline xmlns")

    return failures


def compare_xml_files_exact(expected_xml: Path, actual_xml: Path) -> list[str]:
    if not expected_xml.exists():
        return [f"missing expected xml file: {expected_xml.name}"]

    if not actual_xml.exists():
        return [f"missing generated xml file: {actual_xml.name}"]

    expected_text = expected_xml.read_text(encoding="utf-8")
    actual_text = actual_xml.read_text(encoding="utf-8")

    if expected_text == actual_text:
        return []

    failures: list[str] = ["generated xml does not exactly match expected xml"]

    expected_lines = expected_text.splitlines()
    actual_lines = actual_text.splitlines()
    max_lines = max(len(expected_lines), len(actual_lines))

    for i in range(max_lines):
        e = expected_lines[i] if i < len(expected_lines) else "<missing>"
        a = actual_lines[i] if i < len(actual_lines) else "<missing>"
        if e != a:
            failures.append(f"first difference at line {i + 1}")
            failures.append(f"expected: {e}")
            failures.append(f"actual:   {a}")
            break

    return failures
