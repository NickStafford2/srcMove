"""Human-first command line for repository-history analysis."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Sequence

from .analysis import (
    AnalysisTarget,
    _ensure_state_gitignore,
    analysis_identity,
    analysis_list_pairs,
    analysis_pair_details,
    analysis_status,
    analyze_repository,
)
from .configuration import (
    HistoryConfiguration,
    create_history_configuration,
    load_history_configuration,
)
from .comparison import ComparisonResult, compare_commits, comparison_succeeded
from .database import AnalysisDatabase, analysis_database_exists
from .git import find_repository_root
from .inputs import AnalysisConfiguration, RepositoryIdentity
from .locking import AnalysisOperationLock, is_analysis_writer_locked
from .presentation import render_run, render_status
from .progress import TerminalAnalysisObserver


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="srcmove-history",
        description="Analyze moves across adjacent commits in a Git repository.",
    )
    parser.add_argument(
        "-C",
        type=Path,
        dest="working_directory",
        metavar="PATH",
        help="run as if started in PATH",
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        metavar="PATH",
        help="use a repository-local state directory other than .srcmove",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser(
        "init",
        help="create editable repository-analysis configuration",
        description=(
            "Initialize repository-local configuration without creating an "
            "analysis database or running tools."
        ),
    )

    run = commands.add_parser(
        "run",
        help="create, resume, or extend one repository analysis",
        description=(
            "Create, resume, or extend the repository's .srcmove analysis "
            "toward one absolute history coverage target. Existing analyses "
            "reuse their frozen definition."
        ),
    )
    target = run.add_mutually_exclusive_group(required=True)
    target.add_argument(
        "--pairs", type=int, metavar="N", help="cover the newest N pairs in total"
    )
    target.add_argument(
        "--through", metavar="COMMIT", help="cover through a full commit ID"
    )
    target.add_argument(
        "--all", action="store_true", dest="all_history", help="cover all history"
    )
    run.add_argument("--start", help="newest revision; creation only (default: HEAD)")
    run.add_argument("--name", help="stable repository name; defaults to checkout name")
    run.add_argument("--srcdiff", type=Path, help="srcdiff executable (default: PATH)")
    run.add_argument("--srcmove", type=Path, help="srcMove executable (default: PATH)")
    run.add_argument(
        "--jobs", type=int, help="override config.toml run.jobs for this invocation"
    )
    run.add_argument(
        "--progress",
        choices=("auto", "always", "never"),
        default="auto",
        help="stderr progress display (default: auto)",
    )
    _add_format(run)

    status = commands.add_parser("status", help="show durable coverage and state")
    _add_format(status)

    list_command = commands.add_parser("list", help="list durable pair outcomes")
    filters = list_command.add_mutually_exclusive_group()
    filters.add_argument("--failed", action="store_true")
    filters.add_argument("--moves", action="store_true")
    filters.add_argument(
        "--status",
        choices=(
            "completed",
            "no-analyzable-change",
            "export-failed",
            "srcdiff-failed",
            "srcmove-failed",
            "orchestration-failed",
        ),
    )
    list_command.add_argument("--limit", type=int, default=50, help="maximum rows")
    list_command.add_argument(
        "--after", type=int, metavar="PAIR", help="continue after displayed pair number"
    )
    list_command.add_argument(
        "--oldest-first",
        action="store_true",
        help="reverse the default newest-first order",
    )
    _add_format(list_command)

    show = commands.add_parser("show", help="show evidence for one durable pair")
    show.add_argument("pair", type=int, metavar="PAIR")
    _add_format(show)

    compare = commands.add_parser(
        "compare",
        help="save artifacts for one explicit commit pair",
        description=(
            "Analyze one explicit commit pair with the frozen analysis tools and "
            "configuration, saving selected artifacts without changing history "
            "coverage or canonical results."
        ),
    )
    compare.add_argument(
        "old",
        nargs="?",
        metavar="COMMIT_OR_OLD",
        help="commit to inspect, or the old revision when NEW is supplied",
    )
    compare.add_argument(
        "new",
        nargs="?",
        metavar="NEW",
        help="optional new revision; defaults to COMMIT_OR_OLD with its first parent",
    )
    compare.add_argument(
        "--pair",
        type=int,
        metavar="N",
        help="compare one durable analysis pair by its displayed number",
    )
    compare.add_argument(
        "--save",
        choices=("all", "srcdiff", "srcmove"),
        required=True,
        help="artifacts to retain under the analysis state directory",
    )
    _add_format(compare)
    return parser


def _add_format(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--format",
        choices=("human", "json"),
        default="human",
        dest="output_format",
        help="stdout format (default: human)",
    )


def _target(arguments: argparse.Namespace) -> AnalysisTarget:
    if arguments.pairs is not None:
        return AnalysisTarget("total_pairs", arguments.pairs)
    if arguments.through is not None:
        return AnalysisTarget("through", arguments.through)
    return AnalysisTarget("all", None)


def _discover_tool(path: Path | None, name: str) -> Path:
    if path is not None:
        return path
    discovered = shutil.which(name)
    if discovered is None:
        raise ValueError(
            f"cannot find {name} on PATH; provide --{name} for a new analysis"
        )
    return Path(discovered)


def _repository_and_analysis(arguments: argparse.Namespace) -> tuple[Path, Path]:
    working = (
        Path.cwd()
        if arguments.working_directory is None
        else arguments.working_directory
    )
    repository = find_repository_root(working)
    if arguments.state_dir is None:
        analysis = repository / ".srcmove"
    else:
        requested = arguments.state_dir.expanduser()
        analysis = requested if requested.is_absolute() else repository / requested
        analysis = analysis.absolute()
        if analysis.parent.resolve() != repository:
            raise ValueError(
                "state directory must be a direct child of the repository root"
            )
    return repository, analysis


def _run(
    arguments: argparse.Namespace, *, repository: Path, analysis: Path
) -> Mapping[str, Any]:
    configuration = load_history_configuration(analysis)
    creating = not analysis_database_exists(analysis)
    if not creating:
        supplied = []
        for option, value in (
            ("--start", arguments.start),
            ("--name", arguments.name),
            ("--srcdiff", arguments.srcdiff),
            ("--srcmove", arguments.srcmove),
        ):
            if value is not None:
                supplied.append(option)
        if supplied:
            raise ValueError(
                "existing analysis has a frozen definition; creation-only "
                f"options were supplied: {', '.join(supplied)}; rename or "
                f"remove {analysis.name} to create a different analysis"
            )
    repository_identity = (
        RepositoryIdentity(arguments.name)
        if arguments.name is not None
        else RepositoryIdentity(repository.name)
        if creating
        else None
    )
    srcdiff = (
        _discover_tool(arguments.srcdiff, "srcdiff")
        if creating
        else arguments.srcdiff
    )
    srcmove = (
        _discover_tool(arguments.srcmove, "srcmove")
        if creating
        else arguments.srcmove
    )
    progress_enabled = _progress_enabled(arguments)
    observer = TerminalAnalysisObserver(
        stream=sys.stderr,
        enabled=progress_enabled,
    )
    with observer:
        result = analyze_repository(
            analysis_root=analysis,
            target=_target(arguments),
            jobs=configuration.jobs if arguments.jobs is None else arguments.jobs,
            repository=repository,
            start=arguments.start,
            repository_identity=repository_identity,
            configuration=configuration.analysis,
            srcdiff_path=srcdiff,
            srcmove_path=srcmove,
            observer=observer,
        )
    summary = result.summary
    summary["writer_active"] = False
    summary["state"] = _state(summary)
    return summary


def _init(analysis: Path) -> str:
    with AnalysisOperationLock(analysis, command="init"):
        _ensure_state_gitignore(analysis)
        path = analysis / "config.toml"
        if path.exists() or path.is_symlink():
            load_history_configuration(analysis)
            return f"Already initialized: {path}"
        configuration = HistoryConfiguration(
            analysis=AnalysisConfiguration(excluded_suffixes=(".py",))
        )
        if analysis_database_exists(analysis):
            with AnalysisDatabase.open(analysis, read_only=True) as database:
                invocation = database.latest_invocation()
                configuration = HistoryConfiguration(
                    analysis=database.initial_manifest().configuration,
                    jobs=1 if invocation is None else invocation.jobs,
                )
        create_history_configuration(analysis, configuration)
        return f"Initialized repository analysis: {path}"


def _progress_enabled(arguments: argparse.Namespace) -> bool:
    return arguments.progress == "always" or (
        arguments.progress == "auto" and arguments.output_format == "human"
    )


def _status(analysis: Path) -> dict[str, Any]:
    summary = analysis_status(analysis)
    summary["writer_active"] = is_analysis_writer_locked(analysis)
    summary["state"] = _state(summary)
    return summary


def _state(summary: Mapping[str, Any]) -> str:
    if summary.get("writer_active"):
        return "running"
    invocation = summary.get("invocation")
    invocation = invocation if isinstance(invocation, Mapping) else {}
    result = invocation.get("result")
    if result == "failed" or invocation.get("error"):
        return "failed"
    if result in {"interrupted", "running"}:
        return "interrupted"
    durable = int(summary.get("durable_pair_count", 0))
    target_kind = invocation.get("target_kind")
    target_value = invocation.get("target_value")
    if target_kind == "total_pairs" and target_value is not None:
        target = int(target_value)
        if summary.get("history_exhausted") and durable < target:
            return "history_exhausted"
    if result == "target_reached_with_failures" or summary.get("failed"):
        return "target_reached_with_failures"
    if result == "target_reached":
        return "target_reached"
    return "idle"


def _status_document(summary: Mapping[str, Any]) -> dict[str, Any]:
    invocation_value = summary.get("invocation")
    invocation = (
        dict(invocation_value) if isinstance(invocation_value, Mapping) else None
    )
    target_kind = None if invocation is None else invocation.get("target_kind")
    target_value: Any = None if invocation is None else invocation.get("target_value")
    if target_kind == "total_pairs" and target_value is not None:
        target_kind = "pairs"
        target_value = int(target_value)
    if invocation is not None:
        invocation["target_kind"] = target_kind
        invocation["target_value"] = target_value
    statuses = dict(summary.get("statuses", {}))
    pending = summary.get("pending")
    if isinstance(pending, Mapping):
        pending = {key: value for key, value in pending.items() if key != "batch_id"}
    return {
        "schema_version": 1,
        "analysis": dict(summary.get("analysis", {})),
        "state": summary.get("state", "idle"),
        "target": {"kind": target_kind, "value": target_value},
        "coverage": {
            "target": target_value if target_kind == "pairs" else None,
            "committed": summary.get("completed_pair_count", 0),
            "checkpointed": summary.get("checkpointed_pair_count", 0),
            "durable": summary.get("durable_pair_count", 0),
        },
        "outcomes": {
            "analyzed": summary.get("completed", 0),
            "skipped": summary.get("no_analyzable_change", 0),
            "failed": summary.get("failed", 0),
            "by_status": statuses,
        },
        "moves": {
            "moves": summary.get("move_count", 0),
            "groups": summary.get("move_group_count", 0),
            "pairs": summary.get("move_pair_count", 0),
            "annotated_regions": summary.get("annotated_region_count", 0),
        },
        "history": {
            "newest_commit": summary.get("newest_commit"),
            "frontier_commit": summary.get("oldest_completed_commit"),
            "exhausted": bool(summary.get("history_exhausted")),
        },
        "timings": dict(summary.get("timings", {})),
        "pending": pending,
        "invocation": invocation,
    }


def _render_pair_list(page: Mapping[str, Any]) -> str:
    items = page.get("items", [])
    if not items:
        return "No matching pairs."
    lines = ["Pair  Commits               Status                  Paths   Moves   Time"]
    for item in items:
        old = str(item["old_commit"])[:8]
        new = str(item["new_commit"])[:8]
        status = str(item["status"]).replace("_", "-")
        paths = f"{item['analyzable_path_count']}/{item['changed_path_count']}"
        lines.append(
            f"{item['number']:>4}  {old} → {new}  {status:<22} "
            f"{paths:>7} {item['move_count']:>7} {item['elapsed_seconds']:>6.1f}s"
        )
    if page.get("next_cursor") is not None:
        lines.append(f"\nMore: --after {int(page['next_cursor']) + 1}")
    return "\n".join(lines)


def _render_pair(detail: Mapping[str, Any]) -> str:
    status = str(detail["status"]).replace("_", " ")
    lines = [
        f"Pair {detail['number']} — {status}",
        "",
        f"Commits    {str(detail['old_commit'])[:12]} → "
        f"{str(detail['new_commit'])[:12]}",
        f"Paths      {detail['analyzable_path_count']} analyzable / "
        f"{detail['changed_path_count']} changed",
    ]
    timings = detail.get("timings")
    if isinstance(timings, Mapping) and "pair_seconds" in timings:
        lines.append(f"Time       {float(timings['pair_seconds']):.1f}s pair work")
    metrics = detail.get("metrics")
    exclusion_counts = (
        metrics.get("path_exclusion_counts")
        if isinstance(metrics, Mapping)
        else None
    )
    if isinstance(exclusion_counts, Mapping) and exclusion_counts:
        exclusions = " · ".join(
            f"{int(count)} {reason}"
            for reason, count in sorted(exclusion_counts.items())
        )
        lines.append(f"Excluded   {exclusions}")
    if detail.get("error"):
        lines.extend(("", f"Failure: {detail['error']}"))
    moves = detail.get("moves")
    if moves:
        lines.extend(("", "Moves"))
        for index, move in enumerate(moves, start=1):
            if not isinstance(move, Mapping):
                continue
            kind = str(move.get("match_kind", "unknown"))
            sources = len(move.get("from_xpaths", ()))
            destinations = len(move.get("to_xpaths", ()))
            lines.append(
                f"  {index}. {kind} · {sources} source region"
                f"{'s' if sources != 1 else ''} → {destinations} destination region"
                f"{'s' if destinations != 1 else ''}"
            )
    else:
        lines.extend(("", "No moves detected."))
    return "\n".join(lines)


def _json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _comparison_document(result: ComparisonResult) -> dict[str, Any]:
    outcome = result.outcome
    return {
        "schema_version": 1,
        "comparison": {
            "old_commit": outcome.work_item.old_commit,
            "new_commit": outcome.work_item.new_commit,
            "status": outcome.status.value,
            "changed_path_count": len(outcome.changed_paths),
            "analyzable_path_count": len(outcome.analyzable_paths),
            "metrics": dict(outcome.metrics),
            "timings": dict(outcome.timings),
            "error": outcome.error,
            "saved_paths": [str(path) for path in result.saved_paths],
        },
    }


def _render_comparison(result: ComparisonResult) -> str:
    comparison = _comparison_document(result)["comparison"]
    status = str(comparison["status"]).replace("_", " ")
    lines = [
        f"Comparison — {status}",
        "",
        f"Commits    {str(comparison['old_commit'])[:12]} → "
        f"{str(comparison['new_commit'])[:12]}",
        f"Paths      {comparison['analyzable_path_count']} analyzable / "
        f"{comparison['changed_path_count']} changed",
    ]
    if comparison["error"]:
        lines.extend(("", f"Failure: {comparison['error']}"))
    paths = comparison["saved_paths"]
    if paths:
        lines.extend(("", "Saved"))
        lines.extend(f"  {path}" for path in paths)
    else:
        lines.extend(("", "No artifacts saved."))
    return "\n".join(lines)


def _pair_page_document(
    identity: Mapping[str, str], page: Mapping[str, Any]
) -> dict[str, Any]:
    cursor = page.get("next_cursor")
    return {
        "schema_version": 1,
        "analysis": dict(identity),
        "pairs": {
            "items": page.get("items", []),
            "next_after": None if cursor is None else int(cursor) + 1,
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    try:
        repository, analysis = _repository_and_analysis(arguments)
        if arguments.command == "init":
            output = _init(analysis)
            exit_status = 0
        elif arguments.command == "run":
            summary = _run(arguments, repository=repository, analysis=analysis)
            output = (
                render_run(summary)
                if arguments.output_format == "human"
                else _json(_status_document(summary))
            )
            exit_status = 1 if summary["failed"] else 0
        elif arguments.command == "status":
            summary = _status(analysis)
            output = (
                render_status(summary)
                if arguments.output_format == "human"
                else _json(_status_document(summary))
            )
            exit_status = 0
        elif arguments.command == "list":
            after_distance = None if arguments.after is None else arguments.after - 1
            page = analysis_list_pairs(
                analysis,
                status=(
                    None
                    if arguments.status is None
                    else arguments.status.replace("-", "_")
                ),
                failed=arguments.failed,
                with_moves=arguments.moves,
                limit=arguments.limit,
                after_distance=after_distance,
                oldest_first=arguments.oldest_first,
            )
            identity = analysis_identity(analysis)
            output = (
                _render_pair_list(page)
                if arguments.output_format == "human"
                else _json(_pair_page_document(identity, page))
            )
            exit_status = 0
        elif arguments.command == "show":
            detail = analysis_pair_details(analysis, arguments.pair - 1)
            identity = analysis_identity(analysis)
            output = (
                _render_pair(detail)
                if arguments.output_format == "human"
                else _json(
                    {
                        "schema_version": 1,
                        "analysis": identity,
                        "pair": detail,
                    }
                )
            )
            exit_status = 0
        else:
            if arguments.pair is not None and arguments.old is not None:
                raise ValueError("use either --pair or commit revisions, not both")
            if arguments.pair is None and arguments.old is None:
                raise ValueError("compare requires COMMIT, OLD NEW, or --pair N")
            result = compare_commits(
                analysis_root=analysis,
                repository=repository,
                old_revision=arguments.old,
                new_revision=arguments.new,
                pair_number=arguments.pair,
                save=arguments.save,
            )
            output = (
                _render_comparison(result)
                if arguments.output_format == "human"
                else _json(_comparison_document(result))
            )
            exit_status = 0 if comparison_succeeded(result) else 1
    except KeyboardInterrupt:
        if arguments.command != "run" or not _progress_enabled(arguments):
            print("interrupted", file=sys.stderr)
        return 130
    except (OSError, RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(output)
    return exit_status
