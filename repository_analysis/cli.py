"""Target-driven command line for repository-history analysis."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .analysis import (
    AnalysisTarget,
    analysis_pair_details,
    analysis_status,
    analyze_repository,
)
from .inputs import AnalysisConfiguration, RepositoryIdentity


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m repository_analysis",
        description="Analyze Git history toward one deterministic coverage target.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    analyze = commands.add_parser(
        "analyze", help="create, resume, or extend one repository analysis"
    )
    analyze.add_argument("--analysis-root", type=Path, required=True)
    target = analyze.add_mutually_exclusive_group(required=True)
    target.add_argument("--total-pairs", type=int, metavar="PAIRS")
    target.add_argument("--through", metavar="COMMIT")
    target.add_argument("--all", action="store_true", dest="all_history")
    analyze.add_argument("--repository", type=Path)
    analyze.add_argument("--start")
    analyze.add_argument("--repository-id")
    analyze.add_argument("--srcdiff", type=Path)
    analyze.add_argument("--srcmove", type=Path)
    analyze.add_argument("--directory")
    analyze.add_argument("--exclude-suffix", action="append", metavar=".SUFFIX")
    analyze.add_argument("--no-archive", action="store_true", default=None)
    analyze.add_argument("--position", action="store_true", default=None)
    analyze.add_argument("--encoding")
    analyze.add_argument("--srcdiff-timeout", type=float)
    analyze.add_argument("--srcmove-timeout", type=float)
    analyze.add_argument("--jobs", type=int, default=1)

    status = commands.add_parser("status", help="show durable coverage and progress")
    status.add_argument("--analysis-root", type=Path, required=True)

    inspect = commands.add_parser(
        "inspect", help="show compact evidence for one durable pair"
    )
    inspect.add_argument("--analysis-root", type=Path, required=True)
    inspect.add_argument("--distance-from-newest", type=int, required=True)
    return parser


def _target(arguments: argparse.Namespace) -> AnalysisTarget:
    if arguments.total_pairs is not None:
        return AnalysisTarget("total_pairs", arguments.total_pairs)
    if arguments.through is not None:
        return AnalysisTarget("through", arguments.through)
    return AnalysisTarget("all", None)


def _configuration_arguments_present(arguments: argparse.Namespace) -> bool:
    return any(
        value is not None
        for value in (
            arguments.directory,
            arguments.exclude_suffix,
            arguments.no_archive,
            arguments.position,
            arguments.encoding,
            arguments.srcdiff_timeout,
            arguments.srcmove_timeout,
        )
    )


def _new_configuration(arguments: argparse.Namespace) -> AnalysisConfiguration:
    return AnalysisConfiguration(
        selected_directory=arguments.directory,
        excluded_suffixes=tuple(arguments.exclude_suffix or ()),
        use_archive=not bool(arguments.no_archive),
        use_position=bool(arguments.position),
        source_encoding=arguments.encoding or "UTF-8",
        srcdiff_timeout_seconds=(
            1800.0
            if arguments.srcdiff_timeout is None
            else arguments.srcdiff_timeout
        ),
        srcmove_timeout_seconds=(
            300.0
            if arguments.srcmove_timeout is None
            else arguments.srcmove_timeout
        ),
    )


def _run_analyze(arguments: argparse.Namespace):
    return analyze_repository(
        analysis_root=arguments.analysis_root,
        target=_target(arguments),
        jobs=arguments.jobs,
        repository=arguments.repository,
        start=arguments.start,
        repository_identity=(
            None
            if arguments.repository_id is None
            else RepositoryIdentity(arguments.repository_id)
        ),
        configuration=(
            _new_configuration(arguments)
            if _configuration_arguments_present(arguments)
            else None
        ),
        srcdiff_path=arguments.srcdiff,
        srcmove_path=arguments.srcmove,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "status":
            summary = analysis_status(arguments.analysis_root)
        elif arguments.command == "inspect":
            summary = analysis_pair_details(
                arguments.analysis_root, arguments.distance_from_newest
            )
        else:
            summary = _run_analyze(arguments).summary
    except (OSError, RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 1 if arguments.command == "analyze" and summary["failed"] else 0
