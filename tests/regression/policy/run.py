#!/usr/bin/env python3
"""Run reviewer-editable move-policy catalogs through srcdiff and srcMove."""

from __future__ import annotations

import argparse
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
TESTS_ROOT = SCRIPT_DIR.parents[1]
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from support.cases import (
    TEST_RESULTS_ROOT,
    CaseDefinitionError,
    PolicyCaseSpec,
    discover_policy_cases,
)
from support.tooling import find_srcdiff, find_srcmove, format_process_failure, run_command
from support.validation import load_json


@dataclass(frozen=True)
class PolicyResult:
    case: PolicyCaseSpec
    ok: bool
    detected_moves: int | None
    message: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run srcMove policy catalog cases.")
    parser.add_argument("--srcmove", type=Path)
    parser.add_argument("--srcdiff", type=Path)
    parser.add_argument("--case", action="append", dest="cases", metavar="NAME")
    parser.add_argument("--list", action="store_true")
    return parser.parse_args()


def _text(lines: list[str]) -> str:
    return "\n".join(lines).strip()


def _write_lines(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _reset_case_directory(case_dir: Path, out_root: Path) -> None:
    resolved_root = out_root.resolve()
    resolved_case = case_dir.resolve()
    if resolved_case.parent != resolved_root or case_dir.is_symlink():
        raise RuntimeError(f"refusing to reset unsafe generated case path: {case_dir}")
    if case_dir.exists():
        shutil.rmtree(case_dir)
    case_dir.mkdir(parents=True)


def materialize_case(case: PolicyCaseSpec, case_dir: Path, out_root: Path) -> tuple[Path, Path]:
    _reset_case_directory(case_dir, out_root)
    original = case_dir / "original"
    modified = case_dir / "modified"

    definition = case.definition
    if case.scenario == "transfer":
        _write_lines(
            original / f"source{case.extension}", definition["from_lines"]
        )
        _write_lines(
            modified / f"destination{case.extension}", definition["to_lines"]
        )
    else:
        for relative_name, lines in definition["original_files"].items():
            _write_lines(original / relative_name, lines)
        for relative_name, lines in definition["modified_files"].items():
            _write_lines(modified / relative_name, lines)
    return original, modified


def _normalized_texts(move: dict[str, Any], field: str) -> list[str]:
    values = move.get(field)
    if not isinstance(values, list):
        return []
    return [str(value).strip() for value in values]


def evaluate(case: PolicyCaseSpec, results: dict[str, Any]) -> tuple[bool, str]:
    moves = results.get("moves")
    if not isinstance(moves, list):
        return False, "results.json field 'moves' is not a list"

    if not case.expect_move:
        if moves:
            samples = []
            for move in moves[:3]:
                if isinstance(move, dict):
                    raw = _normalized_texts(move, "from_raw_texts")
                    samples.append(f"{move.get('match_kind', '?')}:{raw!r}")
            return False, f"expected no moves; detected {len(moves)} ({', '.join(samples)})"
        return True, ""

    definition = case.definition
    expected_kind = definition["expected_match_kind"]
    expected_from = _text(definition["expected_from_lines"])
    expected_to = _text(definition["expected_to_lines"])
    matches = []
    for move in moves:
        if not isinstance(move, dict) or move.get("match_kind") != expected_kind:
            continue
        if expected_from not in _normalized_texts(move, "from_raw_texts"):
            continue
        if expected_to not in _normalized_texts(move, "to_raw_texts"):
            continue
        matches.append(move)

    if not matches:
        observed = [
            (
                move.get("match_kind"),
                _normalized_texts(move, "from_raw_texts"),
                _normalized_texts(move, "to_raw_texts"),
            )
            for move in moves[:3]
            if isinstance(move, dict)
        ]
        return False, f"expected {expected_kind} target move not found; observed {observed!r}"
    if len(moves) != 1:
        return False, f"target move found, but expected exactly 1 move and detected {len(moves)}"
    return True, ""


def run_case(
    case: PolicyCaseSpec,
    repo_root: Path,
    out_root: Path,
    srcdiff_bin: Path,
    srcmove_bin: Path,
) -> PolicyResult:
    case_dir = out_root / case.name
    try:
        original, modified = materialize_case(case, case_dir, out_root)
    except Exception as error:
        return PolicyResult(case, False, None, str(error))

    srcdiff_xml = case_dir / "srcdiff.xml"
    srcmove_xml = case_dir / "srcmove.xml"
    results_json = case_dir / "results.json"

    srcdiff_result = run_command(
        [str(srcdiff_bin), str(original), str(modified), "-o", str(srcdiff_xml)],
        cwd=repo_root,
    )
    if srcdiff_result.returncode != 0:
        return PolicyResult(
            case, False, None, format_process_failure("srcdiff", srcdiff_result)
        )
    if not srcdiff_xml.is_file():
        return PolicyResult(case, False, None, "srcdiff did not create srcdiff.xml")

    srcmove_result = run_command(
        [
            str(srcmove_bin),
            str(srcdiff_xml),
            str(srcmove_xml),
            "--results",
            str(results_json),
        ],
        cwd=repo_root,
    )
    if srcmove_result.returncode != 0:
        return PolicyResult(
            case, False, None, format_process_failure("srcMove", srcmove_result)
        )

    try:
        results = load_json(results_json)
        ok, message = evaluate(case, results)
        detected = results.get("move_count")
        if not isinstance(detected, int):
            return PolicyResult(case, False, None, "move_count is not an integer")
        return PolicyResult(case, ok, detected, message)
    except Exception as error:
        return PolicyResult(case, False, None, str(error))


def main() -> int:
    args = parse_args()
    repo_root = SCRIPT_DIR.parents[2]
    out_root = TEST_RESULTS_ROOT / "policy"

    try:
        cases = discover_policy_cases()
    except CaseDefinitionError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    if args.list:
        for case in cases:
            expectation = "move" if case.expect_move else "not-move"
            print(f"{case.name}\t{expectation}\t{case.language}\t{case.rationale}")
        return 0

    if args.cases:
        available = {case.name: case for case in cases}
        unknown = [name for name in args.cases if name not in available]
        if unknown:
            print(f"error: unknown case(s): {', '.join(unknown)}", file=sys.stderr)
            return 2
        cases = [available[name] for name in dict.fromkeys(args.cases)]

    srcdiff = find_srcdiff(repo_root, args.srcdiff)
    srcmove = find_srcmove(repo_root, args.srcmove)
    if srcdiff is None or srcmove is None:
        print("error: srcdiff and srcMove are required", file=sys.stderr)
        return 2

    out_root.mkdir(parents=True, exist_ok=True)
    results: list[PolicyResult] = []
    for case in cases:
        result = run_case(case, repo_root, out_root, srcdiff, srcmove)
        results.append(result)
        observed = (
            "ERROR" if result.detected_moves is None else f"moves={result.detected_moves}"
        )
        status = "PASS" if result.ok else "FAIL"
        expectation = "move" if case.expect_move else "not-move"
        print(f"{status}  {case.name}  expected={expectation}  {observed}")
        if result.message:
            print(f"  {result.message}")

    failed = sum(not result.ok for result in results)
    print()
    print("=== POLICY SUMMARY ===")
    groups = (
        ("main false positives", False, False, "quiet"),
        ("main real moves", True, False, "missed"),
        ("contextual false positives", False, True, "quiet"),
        ("contextual real moves", True, True, "missed"),
    )
    for label, expect_move, contextual, absent_label in groups:
        group = [
            result
            for result in results
            if result.case.expect_move == expect_move
            and result.case.contextual == contextual
        ]
        if not group:
            continue
        detected = sum((result.detected_moves or 0) > 0 for result in group)
        print(
            f"{label}: {len(group)} cases, {detected} detected, "
            f"{len(group) - detected} {absent_label}"
        )
    print(f"policy failures: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
