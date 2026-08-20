#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
TESTS_ROOT = REPO_ROOT / "tests"
CASES_DIR = SCRIPT_DIR / "cases"
GENERATOR = SCRIPT_DIR / "generate.py"
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from support.tooling import find_srcdiff, find_srcmove, print_process_failure, run_command


SummaryRow = dict[str, str | int | bool]
TextValidation = dict[str, str]


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
    parser.add_argument(
        "--candidate-limit",
        type=int,
        help=(
            "Maximum BigCloneBench rows for the generator to scan before dedupe. "
            "By default the generator scans all eligible Type-1/Type-2 rows."
        ),
    )
    parser.add_argument(
        "--dedupe",
        choices=("none", "raw-text-pair", "trimmed-text-pair"),
        default="raw-text-pair",
        help=(
            "Generate unique cases by extracted fragment text. "
            "raw-text-pair preserves whitespace/comment differences. Default: raw-text-pair."
        ),
    )
    parser.add_argument(
        "--text-change",
        choices=("any", "raw-different"),
        default="any",
        help=(
            "Filter generated pairs by whether the two extracted fragments differ "
            "as raw text. Default: any."
        ),
    )
    parser.add_argument("--out-dir", type=Path, default=CASES_DIR)
    parser.add_argument(
        "--srcmove",
        type=Path,
        help="srcMove executable; defaults to SRCMOVE_BIN, the workspace build, or PATH.",
    )
    parser.add_argument("--srcdiff", type=Path)
    args = parser.parse_args()
    if args.syntactic_type is not None:
        args.clone_type = f"type{args.syntactic_type}"
    args.syntactic_type = int(args.clone_type.removeprefix("type"))
    return args


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def trimmed_text(value: str) -> str:
    # Local audit key only. BigCloneBench Type-1 permits whitespace/comment
    # variation, so raw text remains the default dedupe and test-generation key.
    lines = value.strip().splitlines()
    return "\n".join(line.rstrip() for line in lines)


def stable_key(*parts: str) -> str:
    hasher = hashlib.sha256()
    for part in parts:
        encoded = part.encode("utf-8", errors="replace")
        hasher.update(len(encoded).to_bytes(8, byteorder="big"))
        hasher.update(encoded)
    return hasher.hexdigest()


def dedupe_keys(metadata: dict[str, Any]) -> dict[str, str]:
    dedupe = metadata.get("dedupe")
    if isinstance(dedupe, dict):
        raw_pair_key = dedupe.get("raw_text_pair_key")
        trimmed_pair_key = dedupe.get("trimmed_text_pair_key")
        if isinstance(raw_pair_key, str) and isinstance(trimmed_pair_key, str):
            return {
                "raw_text_pair_key": raw_pair_key,
                "trimmed_text_pair_key": trimmed_pair_key,
            }

    fragment_one = metadata.get("fragment_one")
    if not isinstance(fragment_one, dict):
        fragment_one = {}
    fragment_two = metadata.get("fragment_two")
    if not isinstance(fragment_two, dict):
        fragment_two = {}

    fragment1 = fragment_one.get("text")
    fragment2 = fragment_two.get("text")
    if not isinstance(fragment1, str) or not isinstance(fragment2, str):
        return {"raw_text_pair_key": "", "trimmed_text_pair_key": ""}

    return {
        "raw_text_pair_key": stable_key(fragment1, fragment2),
        "trimmed_text_pair_key": stable_key(
            trimmed_text(fragment1), trimmed_text(fragment2)
        ),
    }


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


def moved_position_ranges(srcmove_xml: Path) -> dict[str, list[tuple[int, int]]]:
    tree = ET.parse(srcmove_xml)
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


def normalize_moved_text(value: str) -> str:
    """Normalize wrapper indentation without hiding line content changes."""
    lines = value.strip().splitlines()
    return "\n".join(line.strip() for line in lines)


def has_encoding_damage(value: str) -> bool:
    return "\ufffd" in value or "ï¿½" in value


def normalize_encoding_damage(value: str) -> str:
    try:
        value = value.encode("latin-1").decode("utf-8")
    except UnicodeError:
        pass
    return value.replace("ï¿½", "\ufffd")


def text_matches_with_status(observed: str, expected: str) -> str | None:
    normalized_observed = normalize_moved_text(observed)
    normalized_expected = normalize_moved_text(expected)
    if normalized_observed == normalized_expected:
        return "strict"

    if has_encoding_damage(normalized_observed) or has_encoding_damage(
        normalized_expected
    ):
        tolerant_observed = normalize_encoding_damage(normalized_observed)
        tolerant_expected = normalize_encoding_damage(normalized_expected)
        if tolerant_observed == tolerant_expected:
            return "encoding_tolerant"

    return None


def expected_generated_text(expected: dict[str, Any], side: str) -> str | None:
    generated_key = f"{side}_generated_text"
    generated_text = expected.get(generated_key)
    if isinstance(generated_text, str):
        return generated_text

    # Backward-compatible fallback for metadata generated before the exact
    # wrapped fragment text was recorded.
    raw_key = f"{side}_raw_text"
    raw_text = expected.get(raw_key)
    return raw_text if isinstance(raw_text, str) else None


def validate_reported_text(
    failures: list[str],
    text_validation: TextValidation,
    observed: str,
    expected: dict[str, Any],
    side: str,
) -> None:
    expected_text = expected_generated_text(expected, side)
    if expected_text is None:
        failures.append(f"metadata expected.{side}_generated_text is missing or invalid")
        text_validation[side] = "failed"
        return

    status = text_matches_with_status(observed, expected_text)
    if status is None:
        failures.append(
            f"{side}_raw_texts[0] does not match the expected generated fragment text"
        )
        text_validation[side] = "failed"
        return

    text_validation[side] = status


def validate_case(
    case_dir: Path,
    results_json: Path,
    srcmove_xml: Path,
    syntactic_type: int,
    metadata: dict[str, Any] | None = None,
) -> tuple[list[str], TextValidation]:
    failures: list[str] = []
    text_validation: TextValidation = {"from": "not_checked", "to": "not_checked"}
    if metadata is None:
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
        return failures, text_validation

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

    if isinstance(from_texts, list) and len(from_texts) == 1 and isinstance(
        to_texts, list
    ) and len(to_texts) == 1:
        expected = metadata.get("expected")

        if not isinstance(expected, dict):
            failures.append("metadata expected field is missing or invalid")
            return failures, text_validation

        expected_from_raw = expected.get("from_raw_text")
        expected_to_raw = expected.get("to_raw_text")
        if not isinstance(expected_from_raw, str):
            failures.append("metadata expected.from_raw_text is missing or invalid")
        if not isinstance(expected_to_raw, str):
            failures.append("metadata expected.to_raw_text is missing or invalid")
        if isinstance(from_texts[0], str):
            validate_reported_text(
                failures, text_validation, from_texts[0], expected, "from"
            )
        else:
            failures.append("from_raw_texts[0]: expected string text")
            text_validation["from"] = "failed"
        if isinstance(to_texts[0], str):
            validate_reported_text(
                failures, text_validation, to_texts[0], expected, "to"
            )
        else:
            failures.append("to_raw_texts[0]: expected string text")
            text_validation["to"] = "failed"

    expected = metadata.get("expected")
    if not isinstance(expected, dict):
        failures.append("metadata expected field is missing or invalid")
        return failures, text_validation

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
        return failures, text_validation

    try:
        observed_ranges = moved_position_ranges(srcmove_xml)
    except ET.ParseError as e:
        failures.append(f"srcmove.xml parse error: {e}")
        return failures, text_validation

    if not any(ranges_overlap(found, expected_from_range) for found in observed_ranges["delete"]):
        failures.append(
            "reported delete move does not overlap the expected BigCloneBench source line range"
        )

    if not any(ranges_overlap(found, expected_to_range) for found in observed_ranges["insert"]):
        failures.append(
            "reported insert move does not overlap the expected BigCloneBench target line range"
        )

    return failures, text_validation


def move_points_to_anchor(move: dict[str, Any]) -> bool:
    values: list[str] = []
    for field in ("from_xpaths", "to_xpaths", "from_raw_texts", "to_raw_texts"):
        field_value = move.get(field)
        if isinstance(field_value, list):
            values.extend(value for value in field_value if isinstance(value, str))

    haystack = "\n".join(values)
    return any(
        anchor in haystack
        for anchor in ("beforeAnchor", "middleAnchor", "targetAnchor", "afterAnchor")
    )


def move_points_inside_expected_payload(move: dict[str, Any]) -> bool:
    values: list[str] = []
    for field in ("from_xpaths", "to_xpaths"):
        field_value = move.get(field)
        if isinstance(field_value, list):
            values.extend(value for value in field_value if isinstance(value, str))

    haystack = "\n".join(values)
    return (
        "diff:delete[1]/diff:delete[1]" in haystack
        or "diff:insert[1]/diff:insert[1]" in haystack
    )


def classify_result(
    metadata: dict[str, Any],
    results: dict[str, Any] | None,
    passed: bool,
    failures: list[str],
    text_validation: TextValidation,
) -> str:
    if passed:
        if "encoding_tolerant" in text_validation.values():
            return "pass_encoding_tolerant"
        return "pass_strict"

    if results is None:
        return "tool_failure"

    moves = results.get("moves")
    move_count = results.get("move_count")
    fragment_relation = metadata.get("fragment_relation")
    raw_identical = (
        isinstance(fragment_relation, dict)
        and fragment_relation.get("raw_text_identical") is True
    )

    if not isinstance(moves, list):
        return "invalid_results"

    if move_count == 0:
        return "no_move_raw_identical" if raw_identical else "no_move_raw_different"

    if any(status == "failed" for status in text_validation.values()):
        return "text_mismatch"

    if all(isinstance(move, dict) and move_points_to_anchor(move) for move in moves):
        return "anchor_only_false_positive"

    if all(
        isinstance(move, dict) and move_points_inside_expected_payload(move)
        for move in moves
    ):
        return "too_many_expected_child_moves"

    if any(isinstance(move, dict) and move_points_to_anchor(move) for move in moves):
        return "mixed_anchor_and_payload_moves"

    if failures:
        return "validation_failure"

    return "unknown_failure"


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
        "--dedupe",
        args.dedupe,
        "--text-change",
        args.text_change,
        "--overwrite",
    ]
    if args.candidate_limit is not None:
        cmd.extend(["--candidate-limit", str(args.candidate_limit)])
    proc = run_command(cmd, cwd=REPO_ROOT)
    if proc.returncode != 0:
        print("FAIL generate")
        print_process_failure("generator", proc)
        return False
    if proc.stdout.strip():
        print(proc.stdout.strip())
    return True


def generated_case_dirs(out_dir: Path, syntactic_type: int) -> list[Path]:
    manifest_path = out_dir / f"bcb_t{syntactic_type}_manifest.json"
    manifest = load_json(manifest_path)
    case_names = manifest.get("cases")
    if not isinstance(case_names, list):
        raise ValueError(f"manifest cases field is missing or invalid: {manifest_path}")

    case_dirs: list[Path] = []
    for name in case_names:
        if not isinstance(name, str):
            raise ValueError(f"manifest contains non-string case name: {manifest_path}")
        case_dir = out_dir / name
        if not case_dir.is_dir() or not (case_dir / "metadata.json").is_file():
            raise FileNotFoundError(f"generated case listed in manifest is missing: {case_dir}")
        case_dirs.append(case_dir)
    return case_dirs


def build_summary_row(
    case_dir: Path,
    metadata: dict[str, Any],
    results: dict[str, Any] | None,
    passed: bool,
    failures: list[str],
    text_validation: TextValidation | None = None,
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
    keys = dedupe_keys(metadata)
    fragment_relation = metadata.get("fragment_relation")
    if not isinstance(fragment_relation, dict):
        fragment_relation = {}
    if text_validation is None:
        text_validation = {"from": "", "to": ""}
    failure_class = classify_result(
        metadata, results, passed, failures, text_validation
    )

    return {
        "case": case_dir.name,
        "passed": passed,
        "failure_class": failure_class,
        "clone_type": clone_type,
        "syntactic_type": syntactic_type,
        "function_id_one": metadata.get("function_id_one", ""),
        "function_id_two": metadata.get("function_id_two", ""),
        "min_tokens": metadata.get("min_tokens", ""),
        "file1": fragment_one.get("file", ""),
        "file2": fragment_two.get("file", ""),
        "raw_text_pair_key": keys["raw_text_pair_key"],
        "trimmed_text_pair_key": keys["trimmed_text_pair_key"],
        "raw_text_pair_group_size": "",
        "raw_text_pair_group_index": "",
        "trimmed_text_pair_group_size": "",
        "trimmed_text_pair_group_index": "",
        "raw_text_identical": fragment_relation.get("raw_text_identical", ""),
        "trimmed_text_identical": fragment_relation.get("trimmed_text_identical", ""),
        "move_count": results.get("move_count", "") if isinstance(results, dict) else "",
        "exact_count": match_kinds.get("exact", ""),
        "type2_count": match_kinds.get("type2", ""),
        "from_text_validation": text_validation.get("from", ""),
        "to_text_validation": text_validation.get("to", ""),
        "failures": " | ".join(failures),
    }


def annotate_duplicate_groups(rows: list[SummaryRow], key_field: str) -> None:
    keyed_rows: dict[str, list[SummaryRow]] = {}
    for row in rows:
        key = row.get(key_field)
        if isinstance(key, str) and key:
            keyed_rows.setdefault(key, []).append(row)

    size_field = key_field.removesuffix("_key") + "_group_size"
    index_field = key_field.removesuffix("_key") + "_group_index"
    for group in keyed_rows.values():
        group_size = len(group)
        for index, row in enumerate(group, start=1):
            row[size_field] = group_size
            row[index_field] = index


def write_summary(path: Path, rows: list[SummaryRow]) -> None:
    annotate_duplicate_groups(rows, "raw_text_pair_key")
    annotate_duplicate_groups(rows, "trimmed_text_pair_key")

    fieldnames = [
        "case",
        "passed",
        "failure_class",
        "clone_type",
        "syntactic_type",
        "function_id_one",
        "function_id_two",
        "min_tokens",
        "file1",
        "file2",
        "raw_text_pair_key",
        "raw_text_pair_group_size",
        "raw_text_pair_group_index",
        "trimmed_text_pair_key",
        "trimmed_text_pair_group_size",
        "trimmed_text_pair_group_index",
        "raw_text_identical",
        "trimmed_text_identical",
        "move_count",
        "exact_count",
        "type2_count",
        "from_text_validation",
        "to_text_validation",
        "failures",
    ]

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def run_case(case_dir: Path, srcdiff: Path, srcmove: Path) -> tuple[bool, SummaryRow]:
    srcdiff_xml = case_dir / "srcdiff.xml"
    srcmove_xml = case_dir / "srcmove.xml"
    results_json = case_dir / "results.json"
    metadata = load_json(case_dir / "metadata.json")

    for path in (srcdiff_xml, srcmove_xml, results_json):
        if path.exists():
            path.unlink()

    srcdiff_proc = run_command(
        [
            str(srcdiff),
            "original.java",
            "modified.java",
            "-o",
            str(srcdiff_xml),
            "--position",
        ],
        cwd=case_dir,
    )
    if srcdiff_proc.returncode != 0:
        print(f"FAIL {case_dir.name}")
        print_process_failure("srcdiff", srcdiff_proc)
        failures = [f"srcdiff failed with exit code {srcdiff_proc.returncode}"]
        return False, build_summary_row(case_dir, metadata, None, False, failures)

    srcmove_proc = run_command(
        [
            str(srcmove),
            str(srcdiff_xml),
            str(srcmove_xml),
            "--results",
            str(results_json),
        ],
        cwd=REPO_ROOT,
    )
    if srcmove_proc.returncode != 0:
        print(f"FAIL {case_dir.name}")
        print_process_failure("srcMove", srcmove_proc)
        failures = [f"srcMove failed with exit code {srcmove_proc.returncode}"]
        return False, build_summary_row(case_dir, metadata, None, False, failures)

    syntactic_type = int(metadata.get("syntactic_type"))
    results = load_json(results_json)
    failures, text_validation = validate_case(
        case_dir, results_json, srcmove_xml, syntactic_type
    )
    if failures:
        print(f"FAIL {case_dir.name}")
        for failure in failures:
            print(f"  - {failure}")
        return False, build_summary_row(
            case_dir, metadata, results, False, failures, text_validation
        )

    print(f"PASS {case_dir.name}")
    return True, build_summary_row(
        case_dir, metadata, results, True, [], text_validation
    )


def main() -> int:
    args = parse_args()
    args.out_dir = args.out_dir.resolve()
    srcmove = find_srcmove(REPO_ROOT, args.srcmove)
    if srcmove is None:
        print("error: srcMove not found", file=sys.stderr)
        return 2

    srcdiff = find_srcdiff(REPO_ROOT, args.srcdiff)
    if srcdiff is None:
        print("error: srcdiff not found", file=sys.stderr)
        return 2

    if not GENERATOR.is_file():
        print(f"error: generator not found: {GENERATOR}", file=sys.stderr)
        return 2

    if not generate_cases(args):
        return 1

    try:
        case_dirs = generated_case_dirs(args.out_dir, args.syntactic_type)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print(f"error: failed to read generated case manifest: {e}", file=sys.stderr)
        return 2

    if not case_dirs:
        print(
            f"error: no generated Type-{args.syntactic_type} cases found in {args.out_dir}",
            file=sys.stderr,
        )
        return 2

    failures = 0
    summary_rows: list[SummaryRow] = []
    for case_dir in case_dirs:
        passed, summary_row = run_case(case_dir, srcdiff, srcmove)
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
