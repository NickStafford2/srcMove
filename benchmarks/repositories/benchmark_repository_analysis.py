#!/usr/bin/env python3
"""Run one fresh, end-to-end repository_analysis benchmark trial."""

from __future__ import annotations

import argparse
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
TESTS_ROOT = REPO_ROOT / "tests"
for import_root in (REPO_ROOT, TESTS_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from benchmarks.corpus import DEFAULT_EXCLUDED_SUFFIXES
from benchmarks.process import write_json_atomic
from benchmarks.provenance import (
    observe_executable,
    observe_file,
    observe_repository,
    utc_now,
)
from benchmarks.repositories.run_case import (
    ensure_repo,
    load_case_config,
    resolve_commit,
    update_repo,
    validate_storage_name,
)
from repository_analysis import (
    AnalysisConfiguration,
    AnalysisTarget,
    RepositoryIdentity,
    analyze_repository,
)
from support.tooling import find_srcdiff, find_srcmove


BENCHMARK_SCHEMA_VERSION = 1


def _resolve_start(
    repository: Path,
    revision: str,
    *,
    offline: bool,
    repository_updated: bool,
) -> str:
    """Resolve one revision, fetching once when normal online setup needs it."""

    try:
        return resolve_commit(repository, revision)
    except RuntimeError as error:
        if offline:
            raise RuntimeError(
                f"start revision is unavailable in the offline cache: {revision}"
            ) from error
        if repository_updated:
            raise
    update_repo(repository)
    return resolve_commit(repository, revision)


def _state_directory(repository: Path, case: str) -> tuple[str, Path]:
    benchmark_id = f"repository-analysis-{utc_now().replace(':', '')}-{uuid.uuid4().hex}"
    state_name = f".srcmove-benchmark-{case}-{uuid.uuid4().hex[:12]}"
    state = repository / state_name
    state.mkdir(exist_ok=False)
    return benchmark_id, state


def _directory_size(directory: Path) -> int:
    return sum(
        path.stat().st_size
        for path in directory.rglob("*")
        if path.is_file() and not path.is_symlink()
    )


def run_trial(args: argparse.Namespace) -> tuple[Path, dict[str, Any]]:
    """Prepare a configured repository and measure one fresh analysis."""

    case = validate_storage_name(args.case, "case")
    case_directory = SCRIPT_DIR / case
    configuration_path = case_directory / "info.json"
    if not configuration_path.is_file():
        raise FileNotFoundError(f"repository case not found: {configuration_path}")

    case_configuration = load_case_config(configuration_path)
    repository = case_directory / "work" / "repo"
    repository_updated = ensure_repo(
        case_configuration["github"],
        repository,
        offline=args.offline,
        update=args.fetch,
    )

    requested_start = args.start or case_configuration["new_rev"]
    if requested_start is None:
        raise ValueError(
            f"case {case!r} has no new_rev; provide an immutable --start revision"
        )
    resolved_start = _resolve_start(
        repository,
        requested_start,
        offline=args.offline,
        repository_updated=repository_updated,
    )

    srcdiff = find_srcdiff(REPO_ROOT, args.srcdiff)
    srcmove = find_srcmove(REPO_ROOT, args.srcmove)
    if srcdiff is None:
        raise FileNotFoundError("srcdiff executable not found; provide --srcdiff")
    if srcmove is None:
        raise FileNotFoundError("srcMove executable not found; provide --srcmove")

    benchmark_id, analysis_root = _state_directory(repository, case)
    frozen_configuration = AnalysisConfiguration(
        selected_directory=case_configuration["directory"],
        excluded_suffixes=DEFAULT_EXCLUDED_SUFFIXES,
        srcdiff_timeout_seconds=args.srcdiff_timeout,
        srcmove_timeout_seconds=args.srcmove_timeout,
    )
    record: dict[str, Any] = {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "benchmark_id": benchmark_id,
        "status": "running",
        "started_at": utc_now(),
        "case": {
            "name": case,
            "configuration_path": str(configuration_path.resolve()),
            "repository_url": case_configuration["github"],
            "repository_path": str(repository.resolve()),
            "selected_directory": case_configuration["directory"],
        },
        "workload": {
            "requested_start": requested_start,
            "resolved_start": resolved_start,
            "pairs": args.pairs,
            "jobs": args.jobs,
            "repetition": 1,
        },
        "analysis_root": str(analysis_root.resolve()),
        "configuration": frozen_configuration.record(),
        "observation": {
            "implementation": {
                "benchmark": observe_file(Path(__file__)),
                "srcMove_repository": observe_repository(REPO_ROOT),
            },
            "executables": {
                "srcdiff": observe_executable(srcdiff),
                "srcmove": observe_executable(srcmove),
            },
        },
    }

    started = time.monotonic()
    try:
        result = analyze_repository(
            analysis_root=analysis_root,
            target=AnalysisTarget("total_pairs", args.pairs),
            jobs=args.jobs,
            repository=repository,
            start=resolved_start,
            repository_identity=RepositoryIdentity(case),
            configuration=frozen_configuration,
            srcdiff_path=srcdiff,
            srcmove_path=srcmove,
        )
    except BaseException as error:
        record.update(
            {
                "status": "failed",
                "completed_at": utc_now(),
                "wall_seconds": time.monotonic() - started,
                "error": f"{type(error).__name__}: {error}",
                "state_bytes": _directory_size(analysis_root),
            }
        )
        write_json_atomic(analysis_root / "benchmark.json", record)
        raise

    wall_seconds = time.monotonic() - started
    covered = int(result.summary["completed_pair_count"])
    failures = int(result.summary["failed"])
    record.update(
        {
            "status": "completed" if failures == 0 else "completed_with_failures",
            "completed_at": utc_now(),
            "wall_seconds": wall_seconds,
            "throughput_pairs_per_second": (
                covered / wall_seconds if wall_seconds else None
            ),
            "state_bytes": _directory_size(analysis_root),
            "result": result.summary,
        }
    )
    output = analysis_root / "benchmark.json"
    write_json_atomic(output, record)
    return output, record


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Measure one fresh repository_analysis run using an existing "
            "benchmarks/repositories case."
        )
    )
    parser.add_argument("case", help="repository case directory containing info.json")
    parser.add_argument("--pairs", type=int, required=True)
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument(
        "--start",
        help="newest revision; defaults to the case's new_rev and is resolved exactly",
    )
    network = parser.add_mutually_exclusive_group()
    network.add_argument("--fetch", action="store_true")
    network.add_argument("--offline", action="store_true")
    parser.add_argument("--srcdiff", type=Path)
    parser.add_argument("--srcmove", type=Path)
    parser.add_argument("--srcdiff-timeout", type=float, default=1800.0)
    parser.add_argument("--srcmove-timeout", type=float, default=300.0)
    args = parser.parse_args(argv)
    if args.pairs <= 0:
        parser.error("--pairs must be positive")
    if args.jobs <= 0:
        parser.error("--jobs must be positive")
    if args.srcdiff_timeout <= 0 or args.srcmove_timeout <= 0:
        parser.error("timeouts must be positive")
    return args


def print_summary(path: Path, record: dict[str, Any]) -> None:
    result = record["result"]
    print("\nRepository analysis benchmark")
    print(f"  Status:     {record['status'].replace('_', ' ')}")
    print(f"  Case:       {record['case']['name']}")
    print(
        f"  Workload:   {record['workload']['pairs']} pairs, "
        f"{record['workload']['jobs']} jobs"
    )
    print(f"  Covered:    {result['completed_pair_count']} pairs")
    print(f"  Failures:   {result['failed']}")
    print(f"  Wall time:  {record['wall_seconds']:.3f}s")
    print(f"  Throughput: {record['throughput_pairs_per_second']:.3f} pairs/s")
    print(f"  State:      {record['analysis_root']}")
    print(f"  Record:     {path.resolve()}")


def main(argv: Sequence[str] | None = None) -> int:
    output, record = run_trial(parse_args(argv))
    print_summary(output, record)
    return 0 if record["status"] == "completed" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
