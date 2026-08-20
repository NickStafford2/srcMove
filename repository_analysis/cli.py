"""Minimal production command line for frozen repository-history analysis."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .git import (
    retain_history,
    retained_history_ref,
    select_first_parent_history,
    verify_frozen_commits,
)
from .inputs import (
    FROZEN_ANALYSIS_MANIFEST_NAME,
    AnalysisConfiguration,
    RepositoryIdentity,
    build_pair_work_items,
    freeze_analysis_inputs,
    load_frozen_manifest,
    observe_executable,
    persist_frozen_manifest,
    verify_resume_inputs,
)
from .resume import ResumeStats, resume_pairs
from .retention import RetentionPolicy
from .worker import PairExecutor


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m repository_analysis",
        description="Run deterministic srcDiff/srcMove analysis over Git history.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    start = commands.add_parser("start", help="freeze and start a new analysis")
    start.add_argument("--repository", type=Path, required=True)
    start.add_argument("--start", default="HEAD")
    start.add_argument("--count", type=int, required=True, metavar="PAIRS")
    _add_frozen_arguments(start)
    _add_runtime_arguments(start)

    resume = commands.add_parser("resume", help="verify and resume an analysis")
    _add_frozen_arguments(resume)
    _add_runtime_arguments(resume)
    return parser


def _add_frozen_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--analysis-root", type=Path, required=True)
    parser.add_argument("--repository-id", required=True)
    parser.add_argument("--srcdiff", type=Path, required=True)
    parser.add_argument("--srcmove", type=Path, required=True)
    parser.add_argument("--directory")
    parser.add_argument(
        "--exclude-suffix", action="append", default=[], metavar=".SUFFIX"
    )
    parser.add_argument("--no-archive", action="store_true")
    parser.add_argument("--position", action="store_true")
    parser.add_argument("--encoding", default="UTF-8")
    parser.add_argument("--srcdiff-timeout", type=float, default=1800.0)
    parser.add_argument("--srcmove-timeout", type=float, default=300.0)


def _add_runtime_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--retain-positive-xml", action="store_true")


def _configuration(arguments: argparse.Namespace) -> AnalysisConfiguration:
    return AnalysisConfiguration(
        selected_directory=arguments.directory,
        excluded_suffixes=tuple(arguments.exclude_suffix),
        use_archive=not arguments.no_archive,
        use_position=arguments.position,
        source_encoding=arguments.encoding,
        srcdiff_timeout_seconds=arguments.srcdiff_timeout,
        srcmove_timeout_seconds=arguments.srcmove_timeout,
    )


def _execute(
    manifest, *, analysis_root: Path, jobs: int, retain_positive_xml: bool
) -> ResumeStats:
    executor = PairExecutor(analysis_root)
    return resume_pairs(
        build_pair_work_items(manifest),
        executor,
        analysis_root=analysis_root,
        worker_count=jobs,
        acknowledge_pair=executor.acknowledge,
        retention_policy=RetentionPolicy(
            retain_positive_xml=retain_positive_xml
        ),
    )


def start_analysis(arguments: argparse.Namespace) -> ResumeStats:
    """Freeze and persist all inputs before opening any worker sessions."""

    if arguments.jobs <= 0:
        raise ValueError("jobs must be positive")
    requested_root = arguments.analysis_root.expanduser().absolute()
    if requested_root.is_symlink():
        raise ValueError(f"analysis root must not be a symbolic link: {requested_root}")
    if requested_root.exists() and any(requested_root.iterdir()):
        raise ValueError(f"analysis root is not empty: {requested_root}")
    manifest_path = requested_root.resolve() / FROZEN_ANALYSIS_MANIFEST_NAME
    if manifest_path.exists() or manifest_path.is_symlink():
        raise ValueError(f"analysis manifest already exists: {manifest_path}")
    history = select_first_parent_history(
        arguments.repository, arguments.start, arguments.count
    )
    srcdiff = observe_executable(arguments.srcdiff)
    srcmove = observe_executable(arguments.srcmove)
    manifest = freeze_analysis_inputs(
        repository=arguments.repository,
        repository_identity=RepositoryIdentity(arguments.repository_id),
        commits=history.commits,
        configuration=_configuration(arguments),
        srcdiff=srcdiff,
        srcmove=srcmove,
    )
    ref = retained_history_ref(manifest.canonical_bytes())
    retain_history(manifest.repository, ref, history.resolved_start)
    persist_frozen_manifest(arguments.analysis_root, manifest)
    return _execute(
        manifest,
        analysis_root=arguments.analysis_root,
        jobs=arguments.jobs,
        retain_positive_xml=arguments.retain_positive_xml,
    )


def resume_analysis(arguments: argparse.Namespace) -> ResumeStats:
    """Load immutable state, verify current tools/commits, and run its suffix."""

    frozen = load_frozen_manifest(arguments.analysis_root)
    srcdiff = observe_executable(arguments.srcdiff)
    srcmove = observe_executable(arguments.srcmove)
    manifest = verify_resume_inputs(
        frozen,
        repository_identity=RepositoryIdentity(arguments.repository_id),
        configuration=_configuration(arguments),
        srcdiff=srcdiff,
        srcmove=srcmove,
    )
    verify_frozen_commits(
        manifest.repository,
        manifest.commits,
        retained_ref=retained_history_ref(frozen.canonical_bytes()),
    )
    return _execute(
        manifest,
        analysis_root=arguments.analysis_root,
        jobs=arguments.jobs,
        retain_positive_xml=arguments.retain_positive_xml,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    try:
        stats = (
            start_analysis(arguments)
            if arguments.command == "start"
            else resume_analysis(arguments)
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(stats.summary, sort_keys=True, separators=(",", ":")))
    return 1 if stats.summary["failed"] else 0
