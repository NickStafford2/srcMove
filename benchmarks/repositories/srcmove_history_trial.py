#!/usr/bin/env python3
"""Run one isolated srcMove History analysis for a scaling study."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.contracts import canonical_json
from benchmarks.process import write_json_atomic
from srcmove_history import (
    AnalysisConfiguration,
    AnalysisTarget,
    RepositoryIdentity,
    analysis_pair_details,
    analyze_repository,
)


TRIAL_RESULT_SCHEMA_VERSION = 1


def normalized_analysis_result(
    summary: Mapping[str, Any], details: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Build a portable semantic result independent of timing and paths."""

    pairs = [
        {
            key: detail.get(key)
            for key in (
                "distance_from_newest",
                "old_commit",
                "new_commit",
                "pair_fingerprint",
                "status",
                "changed_path_count",
                "analyzable_path_count",
                "metrics",
                "results_observation",
                "moves",
            )
        }
        for detail in details
    ]
    definition = [
        {
            key: pair[key]
            for key in (
                "distance_from_newest",
                "old_commit",
                "new_commit",
                "pair_fingerprint",
            )
        }
        for pair in pairs
    ]
    normalized = {
        "schema_version": TRIAL_RESULT_SCHEMA_VERSION,
        "summary": {
            key: summary.get(key)
            for key in (
                "completed_pair_count",
                "completed",
                "no_analyzable_change",
                "failed",
            )
        },
        "pairs": pairs,
    }
    return {
        **normalized,
        "definition_fingerprint_sha256": hashlib.sha256(
            canonical_json(definition)
        ).hexdigest(),
        "normalized_results_sha256": hashlib.sha256(
            canonical_json(normalized)
        ).hexdigest(),
    }


def run_trial(args: argparse.Namespace) -> dict[str, Any]:
    configuration = AnalysisConfiguration(
        selected_directory=args.directory,
        excluded_suffixes=(".py",),
        use_position=args.position,
        source_encoding=args.src_encoding,
        srcdiff_timeout_seconds=args.srcdiff_timeout,
        srcmove_timeout_seconds=args.srcmove_timeout,
    )
    result = analyze_repository(
        analysis_root=args.analysis_root,
        target=AnalysisTarget("total_pairs", args.count),
        jobs=args.jobs,
        repository=args.repository,
        start=args.start,
        repository_identity=RepositoryIdentity(args.name),
        configuration=configuration,
        srcdiff_path=args.srcdiff,
        srcmove_path=args.srcmove,
    )
    summary = result.summary
    details = [
        analysis_pair_details(args.analysis_root, distance)
        for distance in range(int(summary["completed_pair_count"]))
    ]
    return normalized_analysis_result(summary, details)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one isolated srcMove History scaling trial."
    )
    parser.add_argument("--analysis-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--jobs", type=int, required=True)
    parser.add_argument("--directory")
    parser.add_argument("--srcdiff", type=Path, required=True)
    parser.add_argument("--srcmove", type=Path, required=True)
    parser.add_argument("--srcdiff-timeout", type=float, required=True)
    parser.add_argument("--srcmove-timeout", type=float, required=True)
    parser.add_argument("--src-encoding", required=True)
    parser.add_argument("--position", action="store_true")
    args = parser.parse_args(argv)
    if args.count <= 0 or args.jobs <= 0:
        parser.error("--count and --jobs must be positive")
    if args.srcdiff_timeout <= 0 or args.srcmove_timeout <= 0:
        parser.error("timeouts must be positive")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    result = run_trial(args)
    write_json_atomic(args.output, result)
    return 1 if result["summary"]["failed"] else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(2)
