"""Deterministic thesis-oriented reporting for repository analyses."""

from __future__ import annotations

import json
import math
import re
import statistics
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .database import (
    AnalysisDatabase,
    DATABASE_SCHEMA_VERSION,
    TERMINAL_PAIR_STATUSES,
)


_FILENAME_PATTERNS = (
    re.compile(r"/src:unit\[@filename='([^']+)'\]"),
    re.compile(r'/src:unit\[@filename="([^"]+)"\]'),
)


@dataclass(frozen=True, slots=True)
class CommitPairMaximum:
    number: int
    old_commit: str
    new_commit: str
    moves: int


@dataclass(frozen=True, slots=True)
class ReportSnapshot:
    repository_name: str
    repository: Path
    analysis_root: Path
    newest_commit: str
    oldest_commit: str | None
    newest_date: str
    oldest_date: str | None
    total_history_commit_pairs: int
    covered_commit_pairs: int
    compared_commit_pairs: int
    no_analyzable_change_commit_pairs: int
    failures: tuple[tuple[str, int], ...]
    changed_paths: int
    analyzable_paths: int
    move_groups: int
    move_bearing_commit_pairs: int
    match_kinds: tuple[tuple[str, int], ...]
    within_file_moves: int
    cross_file_moves: int
    unclassified_location_moves: int
    group_kinds: tuple[tuple[str, int], ...]
    mean_moves: float
    median_moves: float
    p95_moves: float
    maximum: CommitPairMaximum | None
    cumulative_wall_seconds: float
    srcdiff_seconds: float
    srcmove_seconds: float
    mean_commit_pair_seconds: float
    median_commit_pair_seconds: float
    p95_commit_pair_seconds: float
    maximum_commit_pair_seconds: float
    exclusion_counts: tuple[tuple[str, int], ...]
    selected_directory: str | None
    excluded_suffixes: tuple[str, ...]
    use_position: bool
    source_encoding: str
    srcdiff_sha256: str
    srcmove_sha256: str
    fingerprint_schemas: tuple[tuple[str, int], ...]
    history_exhausted: bool


def build_report(analysis_root: Path) -> ReportSnapshot:
    """Read one committed analysis snapshot and enrich it from frozen Git history."""

    with AnalysisDatabase.open(analysis_root, read_only=True) as database:
        with database.read_snapshot():
            state = database.analysis()
            manifest = database.initial_manifest()
            rows = database.connection.execute(
                """
                SELECT p.distance_from_newest, p.old_commit, p.new_commit,
                       p.status, p.changed_path_count, p.analyzable_path_count,
                       p.metrics_json, p.timings_json
                FROM pairs AS p
                JOIN batches AS b ON b.batch_id = p.batch_id
                WHERE b.status = 'completed'
                ORDER BY p.distance_from_newest
                """
            ).fetchall()
            move_rows = database.connection.execute(
                """
                SELECT m.match_kind, m.from_xpaths_json, m.to_xpaths_json
                FROM moves AS m
                JOIN batches AS b ON b.batch_id = m.batch_id
                WHERE b.status = 'completed'
                ORDER BY m.batch_id, m.batch_sequence, m.move_ordinal
                """
            ).fetchall()
            cumulative_wall_seconds = database.cumulative_wall_seconds()
            resolved_analysis_root = database.root

    statuses: Counter[str] = Counter()
    group_kinds: Counter[str] = Counter()
    exclusions: Counter[str] = Counter()
    move_counts: list[int] = []
    commit_pair_seconds: list[float] = []
    changed_paths = 0
    analyzable_paths = 0
    srcdiff_seconds = 0.0
    srcmove_seconds = 0.0
    maximum: CommitPairMaximum | None = None

    for row in rows:
        status = _text(row["status"], "commit pair status")
        if status not in TERMINAL_PAIR_STATUSES:
            raise ValueError(f"unknown stored commit pair status: {status!r}")
        statuses[status] += 1
        changed_paths += _count(row["changed_path_count"], "changed paths")
        analyzable_paths += _count(
            row["analyzable_path_count"], "analyzable paths"
        )
        metrics = _object(row["metrics_json"], "commit pair metrics")
        timings = _object(row["timings_json"], "commit pair timings")
        moves = _count(metrics.get("move_group_count", 0), "move groups")
        _add_counts(group_kinds, metrics.get("group_kinds", {}), "group kinds")
        _add_counts(
            exclusions, metrics.get("path_exclusion_counts", {}), "path exclusions"
        )
        srcdiff_seconds += _optional_seconds(timings.get("srcdiff_seconds"))
        srcmove_seconds += _optional_seconds(timings.get("srcmove_seconds"))
        if status == "completed":
            move_counts.append(moves)
            commit_pair_seconds.append(
                _seconds(timings.get("pair_seconds", 0.0))
            )
            number = (
                _count(row["distance_from_newest"], "commit pair distance")
                + 1
            )
            old_commit = _text(row["old_commit"], "old commit")
            new_commit = _text(row["new_commit"], "new commit")
            if moves > 0:
                candidate = CommitPairMaximum(
                    number=number,
                    old_commit=old_commit,
                    new_commit=new_commit,
                    moves=moves,
                )
                if maximum is None or candidate.moves > maximum.moves:
                    maximum = candidate

    match_kinds: Counter[str] = Counter()
    within_file = 0
    cross_file = 0
    unclassified = 0
    for row in move_rows:
        match_kinds[_text(row["match_kind"], "move match kind")] += 1
        sources = _filenames(_array(row["from_xpaths_json"], "source XPaths"))
        destinations = _filenames(
            _array(row["to_xpaths_json"], "destination XPaths")
        )
        if sources is None or destinations is None:
            unclassified += 1
        elif len(sources) == 1 and sources == destinations:
            within_file += 1
        else:
            cross_file += 1

    move_groups = len(move_rows)
    if len(rows) != state.completed_pair_count:
        raise ValueError("report commit pair coverage drifts from stored results")
    if sum(move_counts) != move_groups:
        raise ValueError("report move rows drift from stored move-group counts")

    repository = manifest.repository
    newest = state.newest_commit
    oldest = state.oldest_completed_commit
    total_commits = _positive_git_count(repository, newest)
    return ReportSnapshot(
        repository_name=_repository_name(repository),
        repository=repository,
        analysis_root=resolved_analysis_root,
        newest_commit=newest,
        oldest_commit=oldest,
        newest_date=_commit_date(repository, newest),
        oldest_date=None if oldest is None else _commit_date(repository, oldest),
        total_history_commit_pairs=max(total_commits - 1, 0),
        covered_commit_pairs=state.completed_pair_count,
        compared_commit_pairs=statuses["completed"],
        no_analyzable_change_commit_pairs=statuses["no_analyzable_change"],
        failures=tuple(
            sorted(
                (name, count)
                for name, count in statuses.items()
                if name.endswith("_failed")
            )
        ),
        changed_paths=changed_paths,
        analyzable_paths=analyzable_paths,
        move_groups=move_groups,
        move_bearing_commit_pairs=sum(count > 0 for count in move_counts),
        match_kinds=tuple(sorted(match_kinds.items())),
        within_file_moves=within_file,
        cross_file_moves=cross_file,
        unclassified_location_moves=unclassified,
        group_kinds=tuple(sorted(group_kinds.items())),
        mean_moves=_mean(move_counts),
        median_moves=_median(move_counts),
        p95_moves=_percentile(move_counts, 0.95),
        maximum=maximum,
        cumulative_wall_seconds=cumulative_wall_seconds,
        srcdiff_seconds=srcdiff_seconds,
        srcmove_seconds=srcmove_seconds,
        mean_commit_pair_seconds=_mean(commit_pair_seconds),
        median_commit_pair_seconds=_median(commit_pair_seconds),
        p95_commit_pair_seconds=_percentile(commit_pair_seconds, 0.95),
        maximum_commit_pair_seconds=max(commit_pair_seconds, default=0.0),
        exclusion_counts=tuple(
            sorted(exclusions.items(), key=lambda item: (-item[1], item[0]))
        ),
        selected_directory=manifest.configuration.selected_directory,
        excluded_suffixes=manifest.configuration.excluded_suffixes,
        use_position=manifest.configuration.use_position,
        source_encoding=manifest.configuration.source_encoding,
        srcdiff_sha256=manifest.srcdiff.sha256,
        srcmove_sha256=manifest.srcmove.sha256,
        fingerprint_schemas=tuple(sorted(manifest.schema_versions.record().items())),
        history_exhausted=state.history_exhausted,
    )


def render_report(report: ReportSnapshot) -> str:
    """Render a stable plain-text report suitable for shell redirection."""

    failure_count = sum(count for _, count in report.failures)
    coverage = _ratio(
        report.covered_commit_pairs, report.total_history_commit_pairs
    )
    analyzable_share = _ratio(report.analyzable_paths, report.changed_paths)
    move_commit_pair_share = _ratio(
        report.move_bearing_commit_pairs, report.compared_commit_pairs
    )
    match_kinds = dict(report.match_kinds)
    group_kinds = dict(report.group_kinds)

    lines = ["Repository History Move Analysis", "=" * 32, "", "Scope"]
    lines.extend(
        (
            _field("Repository", report.repository_name),
            _field("History model", "first-parent"),
            _field(
                "Newest commit",
                _commit_label(report.newest_commit, report.newest_date),
            ),
            _field(
                "Oldest analyzed",
                _commit_label(report.oldest_commit, report.oldest_date),
            ),
            _field(
                "Coverage",
                f"{report.covered_commit_pairs:,} of "
                f"{report.total_history_commit_pairs:,} "
                f"commit pairs ({coverage})",
            ),
        )
    )

    lines.extend(("", "Processing"))
    lines.extend(
        (
            _field("Compared commit pairs", f"{report.compared_commit_pairs:,}"),
            _field(
                "Without analyzable changes",
                f"{report.no_analyzable_change_commit_pairs:,}",
            ),
            _field("Failed commit pairs", f"{failure_count:,}"),
            _field("Changed paths", f"{report.changed_paths:,} observations"),
            _field(
                "Analyzable paths",
                f"{report.analyzable_paths:,} observations "
                f"({analyzable_share} of changed)",
            ),
        )
    )
    if report.failures:
        lines.append(
            _field(
                "Failure types",
                " · ".join(
                    f"{_status_label(name)} {count:,}"
                    for name, count in report.failures
                ),
            )
        )

    lines.extend(("", "Move prevalence"))
    lines.extend(
        (
            _field("Detected moves", f"{report.move_groups:,}"),
            _field(
                "Commit pairs with ≥1 move",
                f"{report.move_bearing_commit_pairs:,} of "
                f"{report.compared_commit_pairs:,} ({move_commit_pair_share})",
            ),
        )
    )

    lines.extend(("", "Match classification"))
    for name in ("type1", "type2", "type3"):
        count = match_kinds.pop(name, 0)
        lines.append(
            _field(
                _match_label(name),
                f"{count:,} ({_ratio(count, report.move_groups)})",
            )
        )
    for name, count in sorted(match_kinds.items()):
        lines.append(_field(name, f"{count:,} ({_ratio(count, report.move_groups)})"))

    lines.extend(("", "Location"))
    lines.extend(
        (
            _field(
                "Within-file",
                f"{report.within_file_moves:,} "
                f"({_ratio(report.within_file_moves, report.move_groups)})",
            ),
            _field(
                "Cross-file",
                f"{report.cross_file_moves:,} "
                f"({_ratio(report.cross_file_moves, report.move_groups)})",
            ),
        )
    )
    if report.unclassified_location_moves:
        lines.append(
            _field("Unclassified", f"{report.unclassified_location_moves:,}")
        )

    lines.extend(("", "Group topology"))
    for name in ("move_1_to_1", "moves_many", "copy_or_repeat", "ambiguous"):
        lines.append(_field(_group_label(name), f"{group_kinds.get(name, 0):,}"))

    lines.extend(("", "Distribution across compared commit pairs"))
    lines.extend(
        (
            _field("Mean moves", f"{report.mean_moves:.2f}"),
            _field("Median moves", _number(report.median_moves)),
            _field("95th percentile moves", _number(report.p95_moves)),
            _field("Maximum moves", _maximum_label(report.maximum)),
        )
    )

    lines.extend(("", "Performance"))
    lines.extend(
        (
            _field("Total wall time", _duration(report.cumulative_wall_seconds)),
            _field("srcDiff work time", _duration(report.srcdiff_seconds)),
            _field("srcMove work time", _duration(report.srcmove_seconds)),
            _field(
                "Mean compared commit pair",
                _duration(report.mean_commit_pair_seconds),
            ),
            _field(
                "Median compared commit pair",
                _duration(report.median_commit_pair_seconds),
            ),
            _field("95th percentile", _duration(report.p95_commit_pair_seconds)),
            _field(
                "Slowest commit pair",
                _duration(report.maximum_commit_pair_seconds),
            ),
        )
    )

    if report.exclusion_counts:
        lines.extend(("", "Most common path exclusions (observations)"))
        lines.extend(
            _exclusion_field(_exclusion_label(reason), count)
            for reason, count in report.exclusion_counts[:10]
        )

    lines.extend(("", "Analysis definition"))
    lines.extend(
        (
            _field("Selected directory", report.selected_directory or "."),
            _field(
                "Excluded suffixes",
                ", ".join(report.excluded_suffixes) or "none",
            ),
            _field("Use positions", "yes" if report.use_position else "no"),
            _field("Source encoding", report.source_encoding),
            _field("Database schema", str(DATABASE_SCHEMA_VERSION)),
            _field(
                "Fingerprint schemas",
                ", ".join(
                    f"{_fingerprint_schema_label(name)}={value}"
                    for name, value in report.fingerprint_schemas
                ),
            ),
            _field("srcDiff SHA-256", report.srcdiff_sha256),
            _field("srcMove SHA-256", report.srcmove_sha256),
            _field("State directory", str(report.analysis_root)),
        )
    )

    lines.extend(("", "Methodological notes"))
    lines.append(
        "  - Results are srcMove detections, not manually validated ground truth."
    )
    lines.append(
        "  - Each detected move is one srcMove result and may contain multiple "
        "source or destination regions."
    )
    lines.append(
        "  - Within-file and cross-file locations come from filenames in the "
        "retained XPath evidence."
    )
    lines.append(
        "  - Path exclusion counts are observations across commit pairs, not "
        "counts of unique paths."
    )
    lines.append(
        "  - History traversal follows first-parent commit pairs from the "
        "frozen newest commit."
    )
    lines.append(
        "  - Tool work times sum processing across commit pairs and may exceed "
        "wall time when workers run in parallel."
    )
    lines.append(
        "  - Total wall time sums finalized run invocations, including no-op "
        "and failed or interrupted runs whose durations were recorded."
    )
    if report.covered_commit_pairs < report.total_history_commit_pairs:
        lines.append(
            f"  - Coverage is limited to {report.covered_commit_pairs:,} of "
            f"{report.total_history_commit_pairs:,} first-parent commit pairs "
            f"({coverage})."
        )
    elif report.history_exhausted:
        lines.append("  - Coverage reached the complete frozen first-parent history.")
    if report.maximum is not None and report.move_groups:
        lines.append(
            f"  - Commit pair {report.maximum.number} contributes "
            f"{report.maximum.moves:,} "
            f"of {report.move_groups:,} detections "
            f"({_ratio(report.maximum.moves, report.move_groups)})."
        )
    type3 = dict(report.match_kinds).get("type3", 0)
    if type3:
        lines.append(
            f"  - Type 3 approximate matches account for {type3:,} of "
            f"{report.move_groups:,} detections ({_ratio(type3, report.move_groups)})."
        )
    if failure_count:
        lines.append(
            f"  - {failure_count:,} failed commit pairs may make detection "
            "totals incomplete."
        )
    else:
        lines.append(
            "  - No commit pair processing failures occurred in the analyzed range."
        )
    return "\n".join(lines)


def _git(repository: Path, *arguments: str) -> str:
    process = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if process.returncode != 0:
        detail = process.stderr.strip()
        raise RuntimeError(
            "Git could not provide repository report metadata"
            + (f": {detail}" if detail else "")
        )
    return process.stdout.strip()


def _repository_name(repository: Path) -> str:
    try:
        origin = _git(repository, "remote", "get-url", "origin")
    except RuntimeError:
        return repository.name
    candidate = origin.rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1]
    if candidate.endswith(".git"):
        candidate = candidate[:-4]
    return candidate or repository.name


def _positive_git_count(repository: Path, commit: str) -> int:
    value = _git(repository, "rev-list", "--first-parent", "--count", commit)
    try:
        count = int(value)
    except ValueError as error:
        raise RuntimeError("Git returned a malformed first-parent count") from error
    if count <= 0:
        raise RuntimeError("Git returned an empty first-parent history")
    return count


def _commit_date(repository: Path, commit: str) -> str:
    value = _git(repository, "show", "-s", "--format=%cI", commit)
    if len(value) < 10:
        raise RuntimeError("Git returned a malformed commit date")
    return value[:10]


def _object(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, bytes):
        raise ValueError(f"stored {context} is malformed")
    try:
        parsed = json.loads(value)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"stored {context} is unreadable") from error
    if not isinstance(parsed, dict):
        raise ValueError(f"stored {context} is not an object")
    return parsed


def _array(value: Any, context: str) -> list[str]:
    if not isinstance(value, bytes):
        raise ValueError(f"stored {context} is malformed")
    try:
        parsed = json.loads(value)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"stored {context} is unreadable") from error
    if not isinstance(parsed, list) or not all(
        isinstance(item, str) for item in parsed
    ):
        raise ValueError(f"stored {context} is not a string array")
    return parsed


def _filenames(xpaths: list[str]) -> set[str] | None:
    filenames: set[str] = set()
    for xpath in xpaths:
        filename = next(
            (
                match.group(1)
                for pattern in _FILENAME_PATTERNS
                if (match := pattern.search(xpath))
            ),
            None,
        )
        if filename is None:
            return None
        filenames.add(filename)
    return filenames or None


def _add_counts(target: Counter[str], value: Any, context: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"stored {context} is malformed")
    for name, count in value.items():
        target[_text(name, context)] += _count(count, context)


def _text(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value or "\0" in value:
        raise ValueError(f"stored {context} is malformed")
    return value


def _count(value: Any, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"stored {context} is malformed")
    return value


def _seconds(value: Any) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError("stored report timing is malformed")
    return float(value)


def _optional_seconds(value: Any) -> float:
    return 0.0 if value is None else _seconds(value)


def _mean(values: list[int] | list[float]) -> float:
    return 0.0 if not values else float(statistics.fmean(values))


def _median(values: list[int] | list[float]) -> float:
    return 0.0 if not values else float(statistics.median(values))


def _percentile(values: list[int] | list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * fraction) - 1)
    return float(ordered[index])


def _field(label: str, value: str) -> str:
    return f"  {label:<27} {value}"


def _exclusion_field(label: str, count: int) -> str:
    return f"  {label:<34} {count:,}"


def _ratio(numerator: int, denominator: int) -> str:
    if denominator == 0:
        return "n/a"
    return f"{100.0 * numerator / denominator:.1f}%"


def _duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    rounded = int(seconds + 0.5)
    hours, remainder = divmod(rounded, 3600)
    minutes, remaining_seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {remaining_seconds:02d}s"
    return f"{minutes}m {remaining_seconds:02d}s"


def _number(value: float) -> str:
    return str(int(value)) if value.is_integer() else f"{value:.1f}"


def _commit_label(commit: str | None, date: str | None) -> str:
    if commit is None:
        return "none"
    return commit[:12] if date is None else f"{commit[:12]}  {date}"


def _maximum_label(maximum: CommitPairMaximum | None) -> str:
    if maximum is None or maximum.moves == 0:
        return "0"
    return (
        f"{maximum.moves:,} (commit pair {maximum.number}: "
        f"{maximum.old_commit[:8]} -> {maximum.new_commit[:8]})"
    )


def _match_label(name: str) -> str:
    return {"type1": "Type 1", "type2": "Type 2", "type3": "Type 3"}[name]


def _group_label(name: str) -> str:
    return {
        "move_1_to_1": "One-to-one moves",
        "moves_many": "Many-to-many moves",
        "copy_or_repeat": "Copy/repeat",
        "ambiguous": "Ambiguous",
    }[name]


def _fingerprint_schema_label(name: str) -> str:
    return {
        "pair_outcome": "commit pair outcome",
        "compact_pair": "compact commit pair",
    }.get(name, name.replace("_", " "))


def _exclusion_label(reason: str) -> str:
    prefixes = {
        "unsupported_srcml_extension: ": "{} (unsupported by srcML)",
        "configured_suffix: ": "{} (configured exclusion)",
        "unsupported_git_mode: ": "{} (unsupported Git mode)",
    }
    for prefix, template in prefixes.items():
        if reason.startswith(prefix):
            return template.format(reason.removeprefix(prefix))
    return reason.replace("_", " ")


def _status_label(name: str) -> str:
    return name.removesuffix("_failed").replace("_", " ")
