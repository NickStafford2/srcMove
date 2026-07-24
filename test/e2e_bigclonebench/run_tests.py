#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
TEST_ROOT = SCRIPT_DIR.parent
REPO_ROOT = TEST_ROOT.parent
CASES_DIR = SCRIPT_DIR / "cases"
GENERATOR = REPO_ROOT / "scripts" / "generate_bigclonebench_move_cases.py"


SummaryRow = dict[str, str | int | bool]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run generated BigCloneBench Type-1 or Type-2 srcMove tests."
    )
    type_group = parser.add_mutually_exclusive_group()
    type_group.add_argument(
        "--clone-type",
        choices=("type1", "type2"),
        default="type1",
        help="BigCloneBench clone type to generate. Default: type1.",
    )
    type_group.add_argument(
        "--syntactic-type",
        type=int,
        choices=(1, 2),
        help="BigCloneBench syntactic_type to generate. Alias for --clone-type.",
    )
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--min-tokens", type=int, default=50)
    parser.add_argument("--out-dir", type=Path, default=CASES_DIR)
    parser.add_argument("--srcmove", type=Path, default=REPO_ROOT / "build" / "srcMove")
    parser.add_argument("--srcdiff", type=Path)
    args = parser.parse_args()
    if args.syntactic_type is not None:
        args.clone_type = f"type{args.syntactic_type}"
    args.syntactic_type = int(args.clone_type.removeprefix("type"))
    return args


def find_srcdiff(explicit: Path | None) -> Path | None:
    if explicit is not None:
        return explicit if explicit.is_file() else None

    from_path = shutil.which("srcdiff")
    if from_path:
        return Path(from_path)

    candidates = [
        REPO_ROOT.parent / "srcDiff" / "build" / "bin" / "srcdiff",
        REPO_ROOT.parent / "srcDiff" / "build-release-check" / "bin" / "srcdiff",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def run_command(cmd: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, check=False)


def print_process_failure(label: str, proc: subprocess.CompletedProcess[str]) -> None:
    print(f"  {label} failed with exit code {proc.returncode}")
    if proc.stdout.strip():
        print("  stdout:")
        for line in proc.stdout.strip().splitlines():
            print(f"    {line}")
    if proc.stderr.strip():
        print("  stderr:")
        for line in proc.stderr.strip().splitlines():
            print(f"    {line}")


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def normalized_text(value: str) -> str:
    lines = value.strip().splitlines()
    return "\n".join(line.rstrip() for line in lines)


def attr_by_local_name(node: ET.Element, local_name: str) -> str | None:
    for key, value in node.attrib.items():
        if key == local_name or key.endswith("}" + local_name) or key.endswith(":" + local_name):
            return value
    return None


def parse_pos_line(value: str, kind: str) -> int | None:
    side = value.split("|")[0 if kind == "delete" else -1]
    line_text = side.split(":", 1)[0]
    try:
        return int(line_text)
    except ValueError:
        return None


def moved_position_ranges(diff_new_xml: Path) -> dict[str, list[tuple[int, int]]]:
    tree = ET.parse(diff_new_xml)
    ranges: dict[str, list[tuple[int, int]]] = {"delete": [], "insert": []}

    for node in tree.iter():
        move_id = attr_by_local_name(node, "id")
        if move_id is None:
            continue

        if attr_by_local_name(node, "to") is not None:
            kind = "delete"
        elif attr_by_local_name(node, "from") is not None:
            kind = "insert"
        else:
            continue

        pos_start = attr_by_local_name(node, "start")
        pos_end = attr_by_local_name(node, "end")
        if pos_start is None or pos_end is None:
            continue

        start_line = parse_pos_line(pos_start, kind)
        end_line = parse_pos_line(pos_end, kind)
        if start_line is None or end_line is None:
            continue

        ranges[kind].append((min(start_line, end_line), max(start_line, end_line)))

    return ranges


def ranges_overlap(left: tuple[int, int], right: tuple[int, int]) -> bool:
    return left[0] <= right[1] and right[0] <= left[1]


def validate_case(
    case_dir: Path, results_json: Path, diff_new_xml: Path, syntactic_type: int
) -> list[str]:
    failures: list[str] = []
    metadata = load_json(case_dir / "metadata.json")
    results = load_json(results_json)
    expected_match_kind = "exact" if syntactic_type == 1 else "type2"

    if metadata.get("syntactic_type") != syntactic_type:
        failures.append(
            f"metadata syntactic_type: expected {syntactic_type}, "
            f"got {metadata.get('syntactic_type')!r}"
        )

    if results.get("move_count") != 1:
        failures.append(f"move_count: expected 1, got {results.get('move_count')!r}")

    match_kinds = results.get("match_kinds")
    if not isinstance(match_kinds, dict) or match_kinds.get(expected_match_kind) != 1:
        failures.append(f"match_kinds.{expected_match_kind}: expected 1")

    moves = results.get("moves")
    if not isinstance(moves, list) or len(moves) != 1:
        failures.append("moves: expected exactly one move")
        return failures

    move = moves[0]
    if move.get("match_kind") != expected_match_kind:
        failures.append(
            f"match_kind: expected {expected_match_kind!r}, "
            f"got {move.get('match_kind')!r}"
        )

    from_texts = move.get("from_raw_texts")
    to_texts = move.get("to_raw_texts")
    if not isinstance(from_texts, list) or len(from_texts) != 1:
        failures.append("from_raw_texts: expected one text")
    if not isinstance(to_texts, list) or len(to_texts) != 1:
        failures.append("to_raw_texts: expected one text")

    if (
        isinstance(from_texts, list)
        and len(from_texts) == 1
        and isinstance(to_texts, list)
        and len(to_texts) == 1
    ):
        expected = metadata.get("expected")

        if not isinstance(expected, dict):
            failures.append("metadata expected field is missing or invalid")
            return failures

        expected_from_raw = expected.get("from_raw_text")
        expected_to_raw = expected.get("to_raw_text")
        if not isinstance(expected_from_raw, str):
            failures.append("metadata expected.from_raw_text is missing or invalid")
        if not isinstance(expected_to_raw, str):
            failures.append("metadata expected.to_raw_text is missing or invalid")

        if (
            syntactic_type == 1
            and isinstance(expected_from_raw, str)
            and isinstance(expected_to_raw, str)
            and normalized_text(expected_from_raw) != normalized_text(expected_to_raw)
        ):
            failures.append("metadata Type-1 expected fragments are not text-identical")

    expected = metadata.get("expected")
    if not isinstance(expected, dict):
        failures.append("metadata expected field is missing or invalid")
        return failures

    try:
        expected_from_range = (
            int(expected["from_start_line"]),
            int(expected["from_end_line"]),
        )
        expected_to_range = (
            int(expected["to_start_line"]),
            int(expected["to_end_line"]),
        )
    except (KeyError, TypeError, ValueError):
        failures.append("metadata expected synthetic line ranges are missing or invalid")
        return failures

    try:
        observed_ranges = moved_position_ranges(diff_new_xml)
    except ET.ParseError as e:
        failures.append(f"diff_new.xml parse error: {e}")
        return failures

    if not any(ranges_overlap(found, expected_from_range) for found in observed_ranges["delete"]):
        failures.append(
            "reported delete move does not overlap the expected BigCloneBench source line range"
        )

    if not any(ranges_overlap(found, expected_to_range) for found in observed_ranges["insert"]):
        failures.append(
            "reported insert move does not overlap the expected BigCloneBench target line range"
        )

    return failures


def generate_cases(args: argparse.Namespace) -> bool:
    cmd = [
        sys.executable,
        str(GENERATOR),
        "--limit",
        str(args.limit),
        "--syntactic-type",
        str(args.syntactic_type),
        "--min-tokens",
        str(args.min_tokens),
        "--out-dir",
        str(args.out_dir),
        "--overwrite",
    ]
    proc = run_command(cmd, cwd=REPO_ROOT)
    if proc.returncode != 0:
        print("FAIL generate")
        print_process_failure("generator", proc)
        return False
    if proc.stdout.strip():
        print(proc.stdout.strip())
    return True


def build_summary_row(
    case_dir: Path,
    metadata: dict[str, Any],
    results: dict[str, Any] | None,
    passed: bool,
    failures: list[str],
) -> SummaryRow:
    match_kinds = results.get("match_kinds") if isinstance(results, dict) else {}
    if not isinstance(match_kinds, dict):
        match_kinds = {}

    fragment_one = metadata.get("fragment_one")
    if not isinstance(fragment_one, dict):
        fragment_one = {}
    fragment_two = metadata.get("fragment_two")
    if not isinstance(fragment_two, dict):
        fragment_two = {}

    syntactic_type = metadata.get("syntactic_type", "")
    clone_type = f"type{syntactic_type}" if syntactic_type != "" else ""

    return {
        "case": case_dir.name,
        "passed": passed,
        "clone_type": clone_type,
        "syntactic_type": syntactic_type,
        "function_id_one": metadata.get("function_id_one", ""),
        "function_id_two": metadata.get("function_id_two", ""),
        "min_tokens": metadata.get("min_tokens", ""),
        "file1": fragment_one.get("file", ""),
        "file2": fragment_two.get("file", ""),
        "move_count": results.get("move_count", "") if isinstance(results, dict) else "",
        "exact_count": match_kinds.get("exact", ""),
        "type2_count": match_kinds.get("type2", ""),
        "failures": " | ".join(failures),
    }


def write_summary(path: Path, rows: list[SummaryRow]) -> None:
    fieldnames = [
        "case",
        "passed",
        "clone_type",
        "syntactic_type",
        "function_id_one",
        "function_id_two",
        "min_tokens",
        "file1",
        "file2",
        "move_count",
        "exact_count",
        "type2_count",
        "failures",
    ]

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def run_case(case_dir: Path, srcdiff: Path, srcmove: Path) -> tuple[bool, SummaryRow]:
    diff_xml = case_dir / "diff.xml"
    diff_new_xml = case_dir / "diff_new.xml"
    results_json = case_dir / "results.json"
    metadata = load_json(case_dir / "metadata.json")

    for path in (diff_xml, diff_new_xml, results_json):
        if path.exists():
            path.unlink()

    srcdiff_proc = run_command(
        [str(srcdiff), "original.java", "modified.java", "-o", str(diff_xml), "--position"],
        cwd=case_dir,
    )
    if srcdiff_proc.returncode != 0:
        print(f"FAIL {case_dir.name}")
        print_process_failure("srcdiff", srcdiff_proc)
        failures = [f"srcdiff failed with exit code {srcdiff_proc.returncode}"]
        return False, build_summary_row(case_dir, metadata, None, False, failures)

    srcmove_proc = run_command(
        [str(srcmove), str(diff_xml), str(diff_new_xml), "--results", str(results_json)],
        cwd=REPO_ROOT,
    )
    if srcmove_proc.returncode != 0:
        print(f"FAIL {case_dir.name}")
        print_process_failure("srcMove", srcmove_proc)
        failures = [f"srcMove failed with exit code {srcmove_proc.returncode}"]
        return False, build_summary_row(case_dir, metadata, None, False, failures)

    syntactic_type = int(metadata.get("syntactic_type"))
    results = load_json(results_json)
    failures = validate_case(case_dir, results_json, diff_new_xml, syntactic_type)
    if failures:
        print(f"FAIL {case_dir.name}")
        for failure in failures:
            print(f"  - {failure}")
        return False, build_summary_row(case_dir, metadata, results, False, failures)

    print(f"PASS {case_dir.name}")
    return True, build_summary_row(case_dir, metadata, results, True, [])


def main() -> int:
    args = parse_args()
    args.out_dir = args.out_dir.resolve()
    args.srcmove = args.srcmove.resolve()

    if not args.srcmove.is_file():
        print(f"error: srcMove not found: {args.srcmove}", file=sys.stderr)
        return 2

    srcdiff = find_srcdiff(args.srcdiff)
    if srcdiff is None:
        print("error: srcdiff not found", file=sys.stderr)
        return 2

    if not GENERATOR.is_file():
        print(f"error: generator not found: {GENERATOR}", file=sys.stderr)
        return 2

    if not generate_cases(args):
        return 1

    prefix = f"bcb_t{args.syntactic_type}_"
    case_dirs = sorted(path for path in args.out_dir.iterdir() if path.is_dir())
    case_dirs = [
        path
        for path in case_dirs
        if path.name.startswith(prefix) and (path / "metadata.json").is_file()
    ]
    case_dirs = case_dirs[: args.limit]

    if not case_dirs:
        print(
            f"error: no generated Type-{args.syntactic_type} cases found in {args.out_dir}",
            file=sys.stderr,
        )
        return 2

    failures = 0
    summary_rows: list[SummaryRow] = []
    for case_dir in case_dirs:
        passed, summary_row = run_case(case_dir, srcdiff.resolve(), args.srcmove)
        summary_rows.append(summary_row)
        if not passed:
            failures += 1

    summary_path = args.out_dir / "summary.csv"
    write_summary(summary_path, summary_rows)

    print()
    print(
        f"type={args.clone_type} total={len(case_dirs)} "
        f"passed={len(case_dirs) - failures} failed={failures}"
    )
    print(f"summary={summary_path}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
