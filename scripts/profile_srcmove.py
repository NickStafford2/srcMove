#!/usr/bin/env python3
"""Run srcMove --profile over existing input.xml cases and write CSV results.

This script records only timings emitted by srcMove's internal profiler. It does
not use subprocess wall time, so Python startup, BigCloneBench database loading,
case generation, and process launch overhead are not included in metric columns.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import re
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
PROFILE_LINE_RE = re.compile(r"^profile\.([A-Za-z0-9_.]+)_ms=([0-9]+(?:\.[0-9]+)?)$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Profile srcMove over existing input.xml fixtures. The CSV contains "
            "only srcMove internal --profile timings, not test runner startup."
        )
    )
    parser.add_argument(
        "--suite",
        choices=("custom", "bigclonebench", "dir"),
        default="bigclonebench",
        help="Case source shortcut. Default: bigclonebench.",
    )
    parser.add_argument(
        "--cases-dir",
        type=Path,
        help="Directory containing case subdirectories with input.xml. Required for --suite dir.",
    )
    parser.add_argument(
        "--srcmove",
        type=Path,
        help=(
            "srcMove executable to profile. Defaults to build-release/srcMove."
        ),
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="CSV output path. Default: profile-results/srcmove-profile-<timestamp>.csv.",
    )
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument(
        "--limit",
        type=int,
        help="Profile at most this many cases after sorting by case name.",
    )
    parser.add_argument(
        "--prepare-bigclonebench",
        action="store_true",
        help=(
            "Generate/run the BigCloneBench fixture set before profiling. This "
            "setup time is not included in the CSV timing columns."
        ),
    )
    parser.add_argument(
        "--clone-type",
        choices=("type1", "type2"),
        default="type1",
        help="Clone type passed to BigCloneBench preparation. Default: type1.",
    )
    parser.add_argument(
        "--bigclonebench-limit",
        type=int,
        default=10,
        help="Limit passed to BigCloneBench preparation. Default: 10.",
    )
    args = parser.parse_args()

    if args.repeats < 1:
        parser.error("--repeats must be at least 1")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    if args.suite == "dir" and args.cases_dir is None:
        parser.error("--cases-dir is required with --suite dir")

    return args


def default_srcmove_path() -> Path:
    return REPO_ROOT / "build-release" / "srcMove"


def case_root_for_suite(args: argparse.Namespace) -> Path:
    if args.suite == "custom":
        return REPO_ROOT / "test" / "e2e_custom" / "cases"
    if args.suite == "bigclonebench":
        return REPO_ROOT / "test" / "e2e_bigclonebench" / "cases"
    return args.cases_dir.resolve()


def git_commit() -> str:
    proc = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def prepare_bigclonebench(args: argparse.Namespace) -> None:
    cmd = [
        sys.executable,
        str(REPO_ROOT / "test" / "e2e_bigclonebench" / "run_tests.py"),
        "--clone-type",
        args.clone_type,
        "--limit",
        str(args.bigclonebench_limit),
        "--srcmove",
        str(args.srcmove),
    ]
    print("Preparing BigCloneBench cases outside profiled measurements:", file=sys.stderr)
    print("  " + " ".join(cmd), file=sys.stderr)
    proc = subprocess.run(cmd, cwd=REPO_ROOT, text=True, check=False)
    if proc.returncode != 0:
        raise SystemExit(proc.returncode)


def find_cases(cases_root: Path, limit: int | None) -> list[Path]:
    if not cases_root.is_dir():
        raise SystemExit(f"error: cases directory not found: {cases_root}")

    cases = sorted(path.parent for path in cases_root.glob("*/input.xml"))
    if limit is not None:
        cases = cases[:limit]
    if not cases:
        raise SystemExit(f"error: no input.xml case files found under {cases_root}")
    return cases


def parse_profile_output(text: str) -> dict[str, float]:
    metrics: dict[str, float] = {}
    for line in text.splitlines():
        match = PROFILE_LINE_RE.match(line.strip())
        if match is None:
            continue
        metrics[match.group(1)] = float(match.group(2))
    return metrics


def run_profile_case(
    srcmove: Path,
    case_dir: Path,
    repeat: int,
    temp_root: Path,
) -> tuple[int, dict[str, float], str]:
    case_name = case_dir.name
    out_dir = temp_root / case_name / f"repeat_{repeat}"
    out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(srcmove),
        str(case_dir / "input.xml"),
        str(out_dir / "output.xml"),
        "--results",
        str(out_dir / "results.json"),
        "--profile",
    ]
    proc = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    metrics = parse_profile_output(proc.stdout + "\n" + proc.stderr)
    failure = ""
    if proc.returncode != 0:
        failure = (proc.stderr or proc.stdout).strip()
    elif not metrics:
        failure = "srcMove completed but emitted no profile metrics"
    return proc.returncode, metrics, failure


def default_output_path() -> Path:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return REPO_ROOT / "profile-results" / f"srcmove-profile-{stamp}.csv"


def write_csv(path: Path, rows: list[dict[str, object]], metric_names: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "timestamp_utc",
        "git_commit",
        "suite",
        "cases_root",
        "case",
        "repeat",
        "srcmove",
        "returncode",
        "failure",
    ]
    fields.extend(f"{name}_ms" for name in metric_names)

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main() -> int:
    args = parse_args()
    args.srcmove = (args.srcmove or default_srcmove_path()).resolve()
    if not args.srcmove.is_file():
        print(f"error: srcMove executable not found: {args.srcmove}", file=sys.stderr)
        return 2

    if args.prepare_bigclonebench:
        prepare_bigclonebench(args)

    cases_root = case_root_for_suite(args)
    cases = find_cases(cases_root, args.limit)
    out_path = (args.out or default_output_path()).resolve()

    rows: list[dict[str, object]] = []
    metric_names: set[str] = set()
    commit = git_commit()
    timestamp = dt.datetime.now(dt.timezone.utc).isoformat()

    with tempfile.TemporaryDirectory(prefix="srcmove-profile-") as temp_name:
        temp_root = Path(temp_name)
        total_runs = len(cases) * args.repeats
        run_index = 0

        for case_dir in cases:
            for repeat in range(1, args.repeats + 1):
                run_index += 1
                print(
                    f"[{run_index}/{total_runs}] profiling {case_dir.name} repeat {repeat}",
                    file=sys.stderr,
                )
                returncode, metrics, failure = run_profile_case(
                    args.srcmove, case_dir, repeat, temp_root
                )
                metric_names.update(metrics)

                row: dict[str, object] = {
                    "timestamp_utc": timestamp,
                    "git_commit": commit,
                    "suite": args.suite,
                    "cases_root": str(cases_root),
                    "case": case_dir.name,
                    "repeat": repeat,
                    "srcmove": str(args.srcmove),
                    "returncode": returncode,
                    "failure": failure,
                }
                for name, value in metrics.items():
                    row[f"{name}_ms"] = f"{value:.3f}"
                rows.append(row)

    ordered_metrics = sorted(metric_names)
    write_csv(out_path, rows, ordered_metrics)

    failures = sum(1 for row in rows if row["returncode"] != 0 or row["failure"])
    print(f"wrote {len(rows)} profile row(s) to {out_path}")
    if failures:
        print(f"failures={failures}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
