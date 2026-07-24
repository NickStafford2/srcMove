#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
TEST_ROOT = SCRIPT_DIR.parent
REPO_ROOT = TEST_ROOT.parent
CASES_DIR = SCRIPT_DIR / "cases"
GENERATOR = REPO_ROOT / "scripts" / "generate_bigclonebench_move_cases.py"


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


def validate_case(case_dir: Path, results_json: Path, syntactic_type: int) -> list[str]:
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
        texts_match = normalized_text(str(from_texts[0])) == normalized_text(str(to_texts[0]))
        if syntactic_type == 1 and not texts_match:
            failures.append("from_raw_texts and to_raw_texts differ for Type-1 case")

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


def run_case(case_dir: Path, srcdiff: Path, srcmove: Path) -> bool:
    diff_xml = case_dir / "diff.xml"
    diff_new_xml = case_dir / "diff_new.xml"
    results_json = case_dir / "results.json"

    for path in (diff_xml, diff_new_xml, results_json):
        if path.exists():
            path.unlink()

    srcdiff_proc = run_command(
        [str(srcdiff), "original.java", "modified.java", "-o", str(diff_xml)],
        cwd=case_dir,
    )
    if srcdiff_proc.returncode != 0:
        print(f"FAIL {case_dir.name}")
        print_process_failure("srcdiff", srcdiff_proc)
        return False

    srcmove_proc = run_command(
        [str(srcmove), str(diff_xml), str(diff_new_xml), "--results", str(results_json)],
        cwd=REPO_ROOT,
    )
    if srcmove_proc.returncode != 0:
        print(f"FAIL {case_dir.name}")
        print_process_failure("srcMove", srcmove_proc)
        return False

    metadata = load_json(case_dir / "metadata.json")
    syntactic_type = int(metadata.get("syntactic_type"))
    failures = validate_case(case_dir, results_json, syntactic_type)
    if failures:
        print(f"FAIL {case_dir.name}")
        for failure in failures:
            print(f"  - {failure}")
        return False

    print(f"PASS {case_dir.name}")
    return True


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
    for case_dir in case_dirs:
        if not run_case(case_dir, srcdiff.resolve(), args.srcmove):
            failures += 1

    print()
    print(
        f"type={args.clone_type} total={len(case_dirs)} "
        f"passed={len(case_dirs) - failures} failed={failures}"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
