#!/usr/bin/env python3
"""Compare fresh repository_analysis runs across worker counts."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
import sys
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
TESTS_ROOT = REPO_ROOT / "tests"
for import_root in (REPO_ROOT, TESTS_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from benchmarks.process import write_json_atomic
from benchmarks.provenance import utc_now
from benchmarks.repositories.benchmark_repository_analysis import run_trial
from benchmarks.repositories.run_case import DEFAULT_DATA_ROOT, validate_storage_name
from repository_analysis import analysis_list_pairs, analysis_pair_details


SCALING_SCHEMA_VERSION = 1
DEFAULT_JOBS = (1, 2, 3, 4, 6, 12, 24)
TRIAL_COLUMNS = (
    "sequence",
    "repetition",
    "jobs",
    "status",
    "wall_seconds",
    "throughput_pairs_per_second",
    "state_bytes",
    "normalized_outcomes_sha256",
    "analysis_root",
    "benchmark_record",
)
SUMMARY_COLUMNS = (
    "jobs",
    "successful_trials",
    "failed_trials",
    "wall_seconds_median",
    "throughput_pairs_per_second_median",
    "state_bytes_median",
    "speedup",
    "parallel_efficiency",
    "normalized_outcomes_equivalent",
)


def parse_jobs(value: str) -> list[int]:
    try:
        jobs = [int(item.strip()) for item in value.split(",") if item.strip()]
    except ValueError as error:
        raise argparse.ArgumentTypeError("--jobs must contain integers") from error
    if not jobs:
        raise argparse.ArgumentTypeError("--jobs must not be empty")
    if any(jobs_count <= 0 for jobs_count in jobs):
        raise argparse.ArgumentTypeError("--jobs values must be positive")
    if len(jobs) != len(set(jobs)):
        raise argparse.ArgumentTypeError("--jobs values must be unique")
    return jobs


def build_schedule(jobs: Sequence[int], repetitions: int) -> list[dict[str, int]]:
    """Interleave ascending and descending sweeps to reduce ordering bias."""

    schedule = []
    sequence = 0
    for repetition in range(1, repetitions + 1):
        order = list(jobs) if repetition % 2 else list(reversed(jobs))
        for jobs_count in order:
            sequence += 1
            schedule.append(
                {
                    "sequence": sequence,
                    "repetition": repetition,
                    "jobs": jobs_count,
                }
            )
    return schedule


def normalized_outcomes(analysis_root: Path) -> tuple[str, list[dict[str, Any]]]:
    """Hash durable pair results while excluding timing and invocation identity."""

    pairs: list[dict[str, Any]] = []
    after_distance: int | None = None
    while True:
        page = analysis_list_pairs(
            analysis_root,
            limit=1000,
            after_distance=after_distance,
        )
        for item in page["items"]:
            detail = analysis_pair_details(
                analysis_root, int(item["distance_from_newest"])
            )
            pairs.append(
                {
                    "distance_from_newest": detail["distance_from_newest"],
                    "old_commit": detail["old_commit"],
                    "new_commit": detail["new_commit"],
                    "pair_fingerprint": detail["pair_fingerprint"],
                    "status": detail["status"],
                    "changed_path_count": detail["changed_path_count"],
                    "analyzable_path_count": detail["analyzable_path_count"],
                    "metrics": detail["metrics"],
                    "error": detail["error"],
                    "results_observation": detail["results_observation"],
                    "moves": detail["moves"],
                }
            )
        after_distance = page["next_cursor"]
        if after_distance is None:
            break
    encoded = json.dumps(
        pairs,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest(), pairs


def _median(rows: Sequence[Mapping[str, Any]], key: str) -> float | None:
    values = [float(row[key]) for row in rows if row.get(key) is not None]
    return statistics.median(values) if values else None


def build_summary(
    rows: Sequence[Mapping[str, Any]], jobs: Sequence[int]
) -> dict[str, Any]:
    successful = [row for row in rows if row["status"] == "completed"]
    hashes = {
        str(row["normalized_outcomes_sha256"])
        for row in successful
        if row.get("normalized_outcomes_sha256")
    }
    baseline_jobs = min(jobs)
    baseline_rows = [row for row in successful if row["jobs"] == baseline_jobs]
    baseline_wall = _median(baseline_rows, "wall_seconds")
    variants: dict[str, Any] = {}
    for jobs_count in jobs:
        selected = [row for row in successful if row["jobs"] == jobs_count]
        wall = _median(selected, "wall_seconds")
        speedup = (
            baseline_wall / wall
            if baseline_wall is not None and wall not in (None, 0)
            else None
        )
        variants[str(jobs_count)] = {
            "jobs": jobs_count,
            "successful_trials": len(selected),
            "failed_trials": sum(
                row["jobs"] == jobs_count and row["status"] != "completed"
                for row in rows
            ),
            "wall_seconds_median": wall,
            "throughput_pairs_per_second_median": _median(
                selected, "throughput_pairs_per_second"
            ),
            "state_bytes_median": _median(selected, "state_bytes"),
            "speedup": speedup,
            "parallel_efficiency": (
                speedup / (jobs_count / baseline_jobs)
                if speedup is not None
                else None
            ),
        }
    return {
        "schema_version": SCALING_SCHEMA_VERSION,
        "baseline_jobs": baseline_jobs,
        "total_trials": len(rows),
        "successful_trials": len(successful),
        "failed_trials": len(rows) - len(successful),
        "normalized_outcomes_equivalent": len(hashes) == 1,
        "normalized_outcomes_sha256": (
            next(iter(hashes)) if len(hashes) == 1 else None
        ),
        "observed_outcome_hashes": sorted(hashes),
        "jobs": variants,
    }


def _write_csv(
    path: Path, columns: Sequence[str], rows: Sequence[Mapping[str, Any]]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(columns), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _trial_arguments(
    arguments: argparse.Namespace, jobs: int, *, fetch: bool
) -> argparse.Namespace:
    return argparse.Namespace(
        case=arguments.case,
        pairs=arguments.pairs,
        jobs=jobs,
        start=arguments.start,
        fetch=fetch,
        offline=arguments.offline,
        srcdiff=arguments.srcdiff,
        srcmove=arguments.srcmove,
        srcdiff_timeout=arguments.srcdiff_timeout,
        srcmove_timeout=arguments.srcmove_timeout,
    )


def run_study(arguments: argparse.Namespace) -> tuple[Path, dict[str, Any]]:
    case = validate_storage_name(arguments.case, "case")
    study_id = (
        f"repository-analysis-scaling-{case}-"
        f"{utc_now().replace(':', '')}-{uuid.uuid4().hex}"
    )
    study_directory = (
        arguments.data_root.expanduser().resolve()
        / "repository-analysis-scaling"
        / study_id
    )
    study_directory.mkdir(parents=True, exist_ok=False)
    schedule = build_schedule(arguments.jobs, arguments.repetitions)
    study: dict[str, Any] = {
        "schema_version": SCALING_SCHEMA_VERSION,
        "study_id": study_id,
        "status": "running",
        "created_at": utc_now(),
        "case": case,
        "pairs": arguments.pairs,
        "jobs": arguments.jobs,
        "repetitions": arguments.repetitions,
        "schedule": schedule,
        "trials": [],
    }
    write_json_atomic(study_directory / "study.json", study)

    rows: list[dict[str, Any]] = []
    try:
        for entry in schedule:
            print(
                f"[{entry['sequence']}/{len(schedule)}] "
                f"repetition {entry['repetition']}, jobs={entry['jobs']}"
            )
            record_path, record = run_trial(
                _trial_arguments(
                    arguments,
                    entry["jobs"],
                    fetch=arguments.fetch and entry["sequence"] == 1,
                )
            )
            outcome_hash, _ = normalized_outcomes(Path(record["analysis_root"]))
            row = {
                **entry,
                "status": record["status"],
                "wall_seconds": record["wall_seconds"],
                "throughput_pairs_per_second": record[
                    "throughput_pairs_per_second"
                ],
                "state_bytes": record["state_bytes"],
                "normalized_outcomes_sha256": outcome_hash,
                "analysis_root": record["analysis_root"],
                "benchmark_record": str(record_path.resolve()),
            }
            rows.append(row)
            study["trials"].append(row)
            write_json_atomic(study_directory / "study.json", study)
            print(
                f"  {record['wall_seconds']:.3f}s, "
                f"{record['throughput_pairs_per_second']:.3f} pairs/s"
            )

        summary = build_summary(rows, arguments.jobs)
        _write_csv(study_directory / "trials.csv", TRIAL_COLUMNS, rows)
        summary_rows = []
        for value in summary["jobs"].values():
            summary_rows.append(
                {
                    **value,
                    "normalized_outcomes_equivalent": summary[
                        "normalized_outcomes_equivalent"
                    ],
                }
            )
        _write_csv(
            study_directory / "summary.csv", SUMMARY_COLUMNS, summary_rows
        )
        write_json_atomic(study_directory / "summary.json", summary)
        study.update(
            {
                "status": (
                    "completed"
                    if summary["failed_trials"] == 0
                    and summary["normalized_outcomes_equivalent"]
                    else "completed_with_failures"
                ),
                "completed_at": utc_now(),
                "summary": summary,
            }
        )
        write_json_atomic(study_directory / "study.json", study)
        return study_directory, study
    except BaseException as error:
        study.update(
            {
                "status": (
                    "interrupted" if isinstance(error, KeyboardInterrupt) else "failed"
                ),
                "completed_at": utc_now(),
                "error": f"{type(error).__name__}: {error}",
            }
        )
        write_json_atomic(study_directory / "study.json", study)
        raise


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark repository_analysis across worker counts."
    )
    parser.add_argument("case")
    parser.add_argument("--pairs", required=True, type=int)
    parser.add_argument(
        "--jobs",
        type=parse_jobs,
        default=list(DEFAULT_JOBS),
        help="comma-separated worker counts (default: 1,2,3,4,6,12,24)",
    )
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--start")
    network = parser.add_mutually_exclusive_group()
    network.add_argument("--fetch", action="store_true")
    network.add_argument("--offline", action="store_true")
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--srcdiff", type=Path)
    parser.add_argument("--srcmove", type=Path)
    parser.add_argument("--srcdiff-timeout", type=float, default=1800.0)
    parser.add_argument("--srcmove-timeout", type=float, default=300.0)
    arguments = parser.parse_args(argv)
    if arguments.pairs <= 0:
        parser.error("--pairs must be positive")
    if arguments.repetitions <= 0:
        parser.error("--repetitions must be positive")
    if arguments.srcdiff_timeout <= 0 or arguments.srcmove_timeout <= 0:
        parser.error("timeouts must be positive")
    return arguments


def print_summary(study_directory: Path, study: Mapping[str, Any]) -> None:
    summary = study["summary"]
    print("\nRepository analysis worker scaling")
    print("  Jobs   Median     Speedup   Efficiency   Throughput")
    for value in summary["jobs"].values():
        wall = value["wall_seconds_median"]
        speedup = value["speedup"]
        efficiency = value["parallel_efficiency"]
        throughput = value["throughput_pairs_per_second_median"]
        if None in (wall, speedup, efficiency, throughput):
            print(f"  {value['jobs']:>4}   insufficient successful trials")
            continue
        print(
            f"  {value['jobs']:>4}   {wall:>7.3f}s   {speedup:>7.2f}x   "
            f"{efficiency:>9.1%}   {throughput:>9.3f}/s"
        )
    equivalent = "yes" if summary["normalized_outcomes_equivalent"] else "NO"
    print(f"  Outcomes equivalent: {equivalent}")
    print(f"  Study: {study_directory.resolve()}")


def main(argv: Sequence[str] | None = None) -> int:
    study_directory, study = run_study(parse_args(argv))
    print_summary(study_directory, study)
    return 0 if study["status"] == "completed" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
