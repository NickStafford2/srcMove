#!/usr/bin/env python3
"""Run srcMove --profile over existing fixture cases and write CSV results.

This script records only timings emitted by srcMove's internal profiler. It does
not use subprocess wall time, so Python startup, BigCloneBench database loading,
case generation, and process launch overhead are not included in metric columns.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import shutil
import re
import statistics
import sys
import tempfile
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
TEST_ROOT = REPO_ROOT / "test"
if str(TEST_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_ROOT))

from tooling import find_srcmove, run_command

PROFILE_LINE_RE = re.compile(r"^profile\.([A-Za-z0-9_.]+)_ms=([0-9]+(?:\.[0-9]+)?)$")
OPENCV_DIFF = (
    REPO_ROOT
    / "examples"
    / "opencv"
    / "opencv.1_2.v000001-to-v000002.e46e13a77579-to-5e38cf8042d1.position.diff.xml"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Profile srcMove over existing fixture inputs. The CSV contains "
            "only srcMove internal --profile timings, not test runner startup."
        )
    )
    parser.add_argument(
        "--suite",
        choices=("custom", "bigclonebench", "opencv", "dir"),
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
            "srcMove executable to profile. Defaults to SRCMOVE_BIN, the workspace build, or PATH."
        ),
    )
    parser.add_argument(
        "--out",
        type=Path,
        help=(
            "CSV output path. Default: "
            "profile-results/runs/<timestamp>_<suite>.csv."
        ),
    )
    parser.add_argument(
        "--label",
        default="",
        help="Optional run label written to CSV metadata and default filename.",
    )
    parser.add_argument(
        "--no-latest",
        action="store_true",
        help="Do not update profile-results/latest.csv after writing the run CSV.",
    )
    parser.add_argument("--repeats", type=int, default=3)
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
        default=1000,
        help="Limit passed to BigCloneBench preparation. Default: 1000.",
    )
    args = parser.parse_args()

    if args.repeats < 1:
        parser.error("--repeats must be at least 1")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    if args.suite == "dir" and args.cases_dir is None:
        parser.error("--cases-dir is required with --suite dir")

    return args


def default_label(args: argparse.Namespace, case_count: int | None = None) -> str:
    if args.suite == "bigclonebench":
        label = f"bigclonebench-{args.clone_type}-request{args.bigclonebench_limit}"
        if case_count is not None:
            label += f"-cases{case_count}"
        return f"{label}-r{args.repeats}"
    if args.suite == "opencv":
        return f"opencv-large-r{args.repeats}"
    return f"{args.suite}-r{args.repeats}"


def case_root_for_suite(args: argparse.Namespace) -> Path:
    if args.suite == "custom":
        return REPO_ROOT / "test" / "e2e_custom" / "cases"
    if args.suite == "bigclonebench":
        return REPO_ROOT / "test" / "e2e_bigclonebench" / "cases"
    if args.suite == "opencv":
        return OPENCV_DIFF.parent
    return args.cases_dir.resolve()


def git_commit() -> str:
    proc = run_command(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=REPO_ROOT,
    )
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def prepare_bigclonebench(args: argparse.Namespace) -> None:
    syntactic_type = 1 if args.clone_type == "type1" else 2
    manifest_path = (
        REPO_ROOT
        / "test"
        / "e2e_bigclonebench"
        / "cases"
        / f"bcb_t{syntactic_type}_manifest.json"
    )
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
    proc = run_command(cmd, cwd=REPO_ROOT, capture_output=False)
    if proc.returncode != 0:
        if manifest_path.is_file():
            print(
                "warning: BigCloneBench preparation reported validation failures, "
                "but generated an active manifest; continuing with profiling",
                file=sys.stderr,
            )
            return
        raise SystemExit(proc.returncode)


def suite_input_name(suite: str) -> str:
    if suite == "bigclonebench":
        return "diff.xml"
    if suite == "opencv":
        return OPENCV_DIFF.name
    return "input.xml"


def find_cases(
    cases_root: Path,
    limit: int | None,
    suite: str,
    clone_type: str,
) -> list[Path]:
    if not cases_root.is_dir():
        message = f"error: cases directory not found: {cases_root}"
        if suite == "bigclonebench":
            message += "\nrerun with --prepare-bigclonebench to generate cases first"
        raise SystemExit(message)

    if suite == "bigclonebench":
        syntactic_type = 1 if clone_type == "type1" else 2
        manifest_path = cases_root / f"bcb_t{syntactic_type}_manifest.json"
        try:
            with manifest_path.open("r", encoding="utf-8") as f:
                manifest = json.load(f)
            case_names = manifest["cases"]
        except (OSError, KeyError, json.JSONDecodeError) as e:
            raise SystemExit(
                f"error: failed to read BigCloneBench manifest {manifest_path}: {e}\n"
                "rerun with --prepare-bigclonebench to generate the active manifest"
            ) from e
        if not isinstance(case_names, list) or not all(
            isinstance(name, str) for name in case_names
        ):
            raise SystemExit(
                f"error: invalid cases list in BigCloneBench manifest {manifest_path}"
            )
        cases = [cases_root / name for name in case_names]
    elif suite == "opencv":
        cases = [cases_root]
    else:
        input_name = suite_input_name(suite)
        cases = sorted(path.parent for path in cases_root.glob(f"*/{input_name}"))

    if limit is not None:
        cases = cases[:limit]

    input_name = suite_input_name(suite)
    cases = [case for case in cases if (case / input_name).is_file()]
    if not cases:
        message = f"error: no {input_name} case files found under {cases_root}"
        if suite == "bigclonebench":
            message += "\nrerun with --prepare-bigclonebench to generate cases first"
        raise SystemExit(message)
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
    input_name: str,
    repeat: int,
    temp_root: Path,
) -> tuple[int, dict[str, float], str]:
    case_name = case_dir.name
    out_dir = temp_root / case_name / f"repeat_{repeat}"
    out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(srcmove),
        str(case_dir / input_name),
        str(out_dir / "output.xml"),
        "--results",
        str(out_dir / "results.json"),
        "--profile",
    ]
    proc = run_command(
        cmd,
        cwd=REPO_ROOT,
    )
    metrics = parse_profile_output(proc.stdout + "\n" + proc.stderr)
    failure = ""
    if proc.returncode != 0:
        failure = (proc.stderr or proc.stdout).strip()
    elif not metrics:
        failure = "srcMove completed but emitted no profile metrics"
    return proc.returncode, metrics, failure


def safe_filename_part(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    return cleaned.strip("-")


def default_output_path(args: argparse.Namespace) -> Path:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    parts = ["srcmove-profile", stamp, args.suite]
    label = safe_filename_part(args.label)
    if label:
        parts.append(label)
    return REPO_ROOT / "profile-results" / "runs" / ("_".join(parts) + ".csv")


def write_csv(path: Path, rows: list[dict[str, object]], metric_names: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "timestamp_utc",
        "git_commit",
        "label",
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


def summarize_metrics(rows: list[dict[str, object]], metric_names: list[str]) -> list[str]:
    lines: list[str] = []
    for name in metric_names:
        values: list[float] = []
        field = f"{name}_ms"
        for row in rows:
            value = row.get(field)
            if not isinstance(value, str) or not value:
                continue
            values.append(float(value))
        if not values:
            continue

        lines.append(
            f"{field}: n={len(values)} median={statistics.median(values):.3f} "
            f"avg={statistics.mean(values):.3f} min={min(values):.3f} "
            f"max={max(values):.3f}"
        )
    return lines


def write_metadata(
    path: Path,
    args: argparse.Namespace,
    rows: list[dict[str, object]],
    metric_names: list[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    failures = sum(1 for row in rows if row["returncode"] != 0 or row["failure"])
    with path.open("w", encoding="utf-8") as f:
        f.write(f"timestamp_utc={rows[0]['timestamp_utc'] if rows else ''}\n")
        f.write(f"git_commit={rows[0]['git_commit'] if rows else ''}\n")
        f.write(f"label={args.label}\n")
        f.write(f"suite={args.suite}\n")
        if args.suite == "bigclonebench":
            f.write(f"clone_type={args.clone_type}\n")
            f.write(f"bigclonebench_requested_limit={args.bigclonebench_limit}\n")
        if args.limit is not None:
            f.write(f"profile_case_limit={args.limit}\n")
        f.write(f"srcmove={args.srcmove}\n")
        f.write(f"rows={len(rows)}\n")
        f.write(f"profiled_cases={len({row['case'] for row in rows})}\n")
        f.write(f"failures={failures}\n")
        f.write("command=" + " ".join(sys.argv) + "\n")
        f.write("\n[timing_summary]\n")
        for line in summarize_metrics(rows, metric_names):
            f.write(line + "\n")


def main() -> int:
    args = parse_args()
    srcmove = find_srcmove(REPO_ROOT, args.srcmove)
    if srcmove is None:
        print("error: srcMove executable not found", file=sys.stderr)
        print("build srcMove or pass --srcmove <path>", file=sys.stderr)
        return 2
    args.srcmove = srcmove

    if args.prepare_bigclonebench:
        prepare_bigclonebench(args)

    cases_root = case_root_for_suite(args)
    cases = find_cases(cases_root, args.limit, args.suite, args.clone_type)
    if not args.label:
        args.label = default_label(args, len(cases))
    out_path = (args.out or default_output_path(args)).resolve()
    input_name = suite_input_name(args.suite)

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
                    args.srcmove, case_dir, input_name, repeat, temp_root
                )
                metric_names.update(metrics)

                row: dict[str, object] = {
                    "timestamp_utc": timestamp,
                    "git_commit": commit,
                    "label": args.label,
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
    metadata_path = out_path.with_suffix(".txt")
    write_metadata(metadata_path, args, rows, ordered_metrics)

    latest_path = REPO_ROOT / "profile-results" / "latest.csv"
    latest_metadata_path = REPO_ROOT / "profile-results" / "latest.txt"
    if not args.no_latest:
        latest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(out_path, latest_path)
        shutil.copyfile(metadata_path, latest_metadata_path)

    failures = sum(1 for row in rows if row["returncode"] != 0 or row["failure"])
    print(f"wrote {len(rows)} profile row(s) to {out_path}")
    print(f"wrote metadata to {metadata_path}")
    if not args.no_latest:
        print(f"updated {latest_path}")
        print(f"updated {latest_metadata_path}")
    if failures:
        print(f"failures={failures}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
