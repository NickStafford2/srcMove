#!/usr/bin/env python3
"""Run repository benchmarks across adjacent first-parent commits."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence, TextIO

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
TESTS_ROOT = REPO_ROOT / "tests"
for import_root in (REPO_ROOT, TESTS_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from benchmarks.contracts import canonical_json
from benchmarks.corpus import DEFAULT_EXCLUDED_SUFFIXES
from benchmarks.process import write_json_atomic
from benchmarks.progress import ProgressDisplay
from benchmarks.provenance import sha256_file, utc_now
from benchmarks.repositories.run_case import (
    DEFAULT_DATA_ROOT,
    ensure_repo,
    load_case_config,
    normalize_repo_subdir,
    require_ok,
    resolve_commit,
    run_staged_repository_benchmark,
)
from support.tooling import find_srcdiff, find_srcmove, run_command as run


HISTORY_SCHEMA_VERSION = 2
TRAVERSAL_MODE = "first_parent"
INPUT_SCOPE = "changed_files"
SAFE_HISTORY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
REGULAR_GIT_MODES = {"100644", "100755"}


@dataclass(frozen=True)
class CommitMetadata:
    commit: str
    parents: tuple[str, ...]
    committer_time_iso8601: str
    subject: str

    @property
    def is_merge(self) -> bool:
        return len(self.parents) > 1

    def as_json(self) -> dict[str, Any]:
        return {
            "commit": self.commit,
            "parents": list(self.parents),
            "parent_count": len(self.parents),
            "committer_time_iso8601": self.committer_time_iso8601,
            "subject": self.subject,
            "is_merge": self.is_merge,
        }


@dataclass(frozen=True)
class ChangedPath:
    status: str
    path: str
    old_mode: str
    new_mode: str
    old_blob: str
    new_blob: str

    @property
    def exists_in_old(self) -> bool:
        return self.old_mode != "000000"

    @property
    def exists_in_new(self) -> bool:
        return self.new_mode != "000000"

    @property
    def content_changed(self) -> bool:
        return self.old_blob != self.new_blob

    def as_json(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "path": self.path,
            "old_mode": self.old_mode,
            "new_mode": self.new_mode,
            "old_blob": self.old_blob,
            "new_blob": self.new_blob,
        }


def select_first_parent_history(
    repo_dir: Path, start: str, pair_count: int
) -> tuple[str, list[CommitMetadata]]:
    """Return up to pair_count+1 commits in oldest-to-newest ancestry order."""
    if pair_count <= 0:
        raise ValueError("pair count must be positive")
    if not start:
        raise ValueError("start revision must not be empty")

    shallow = run(["git", "rev-parse", "--is-shallow-repository"], cwd=repo_dir)
    require_ok(shallow, "git shallow-repository check")
    if shallow.stdout.strip() == "true":
        raise RuntimeError(
            "historical repository analysis requires a complete, non-shallow clone"
        )

    resolved_start = resolve_commit(repo_dir, start)
    result = run(
        [
            "git",
            "log",
            "-z",
            "--first-parent",
            f"--max-count={pair_count + 1}",
            "--format=%H%x00%P%x00%cI%x00%s",
            resolved_start,
        ],
        cwd=repo_dir,
    )
    require_ok(result, f"git first-parent history from {start}")
    fields = result.stdout.split("\0")
    if fields and fields[-1] == "":
        fields.pop()
    if len(fields) % 4 != 0:
        raise RuntimeError("git returned malformed first-parent metadata")

    newest_first = [
        CommitMetadata(
            commit=fields[index],
            parents=tuple(fields[index + 1].split()) if fields[index + 1] else (),
            committer_time_iso8601=fields[index + 2],
            subject=fields[index + 3],
        )
        for index in range(0, len(fields), 4)
    ]
    if len(newest_first) < 2:
        raise RuntimeError(
            "the selected history has fewer than two commits; no adjacent pair exists"
        )
    return resolved_start, list(reversed(newest_first))


def retain_start_commit(repo_dir: Path, history_id: str, commit: str) -> str:
    if not SAFE_HISTORY_RE.fullmatch(history_id):
        raise ValueError(f"unsafe history ID: {history_id!r}")
    ref = f"refs/srcmove/repository-histories/{history_id}/start"
    result = run(["git", "update-ref", ref, commit], cwd=repo_dir)
    require_ok(result, f"retain history start as {ref}")
    return ref


def inventory_changed_paths(
    repo_dir: Path,
    old_commit: str,
    new_commit: str,
    directory: str | None,
    excluded_suffixes: Sequence[str],
) -> tuple[list[ChangedPath], list[ChangedPath]]:
    command = [
        "git",
        "diff",
        "--raw",
        "-z",
        "--no-abbrev",
        "--no-renames",
        old_commit,
        new_commit,
        "--",
    ]
    if directory:
        command.append(directory)
    result = run(command, cwd=repo_dir)
    require_ok(result, f"inventory changed paths for {old_commit}..{new_commit}")
    fields = result.stdout.split("\0")
    if fields and fields[-1] == "":
        fields.pop()
    if len(fields) % 2 != 0:
        raise RuntimeError("git returned malformed raw changed-path metadata")
    changed: list[ChangedPath] = []
    for index in range(0, len(fields), 2):
        header = fields[index]
        path = fields[index + 1]
        parts = header.removeprefix(":").split()
        if len(parts) != 5:
            raise RuntimeError(f"git returned malformed change header: {header!r}")
        old_mode, new_mode, old_blob, new_blob, status = parts
        changed.append(
            ChangedPath(
                status=status,
                path=path,
                old_mode=old_mode,
                new_mode=new_mode,
                old_blob=old_blob,
                new_blob=new_blob,
            )
        )
    excluded = {suffix.lower() for suffix in excluded_suffixes}
    analyzable = [
        change
        for change in changed
        if change.content_changed and Path(change.path).suffix.lower() not in excluded
    ]
    return changed, analyzable


def _validate_sparse_change(change: ChangedPath) -> None:
    path = Path(change.path)
    if path.is_absolute() or ".." in path.parts or not change.path:
        raise RuntimeError(f"unsafe changed path: {change.path!r}")
    for side, exists, mode in (
        ("old", change.exists_in_old, change.old_mode),
        ("new", change.exists_in_new, change.new_mode),
    ):
        if exists and mode not in REGULAR_GIT_MODES:
            raise RuntimeError(
                f"unsupported {side} Git object mode {mode} for {change.path}; "
                "historical sparse inputs accept only regular files"
            )


def export_changed_files(
    repo_dir: Path,
    old_commit: str,
    new_commit: str,
    changes: Sequence[ChangedPath],
    original_dir: Path,
    modified_dir: Path,
) -> None:
    """Export sparse old/new trees while retaining repository-relative paths."""
    for change in changes:
        _validate_sparse_change(change)

    for output in (original_dir, modified_dir):
        if output.is_symlink():
            raise RuntimeError(f"refusing to replace symbolic-link export path: {output}")
        if output.exists():
            shutil.rmtree(output)
        output.mkdir(parents=True, exist_ok=False)

    def export_side(commit: str, paths: Sequence[str], output: Path) -> None:
        if not paths:
            return
        archive = subprocess.Popen(
            ["git", "archive", commit, "--", *paths],
            cwd=repo_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        extract = subprocess.Popen(
            ["tar", "-x", "-C", str(output)],
            stdin=archive.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert archive.stdout is not None
        archive.stdout.close()
        _, extract_error = extract.communicate()
        _, archive_error = archive.communicate()
        if archive.returncode != 0:
            raise RuntimeError(
                f"git archive failed for sparse export {commit}\n"
                f"stderr:\n{archive_error.decode(errors='replace')}"
            )
        if extract.returncode != 0:
            raise RuntimeError(
                f"tar extract failed for sparse export {commit}\n"
                f"stderr:\n{extract_error.decode(errors='replace')}"
            )

    old_paths = [change.path for change in changes if change.exists_in_old]
    new_paths = [change.path for change in changes if change.exists_in_new]
    export_side(old_commit, old_paths, original_dir)
    export_side(new_commit, new_paths, modified_dir)


def _history_identifier(case_name: str) -> str:
    timestamp = utc_now().replace(":", "").replace("+", "-")
    return f"history-{timestamp}-{case_name}-{uuid.uuid4()}"


def _relative(path: Path, data_root: Path) -> str:
    return path.resolve().relative_to(data_root.resolve()).as_posix()


def _configuration_fingerprint(configuration: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(dict(configuration))).hexdigest()


def _aggregate(pairs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    statuses = [pair["status"] for pair in pairs]
    completed = [pair for pair in pairs if pair["status"] == "completed"]
    timing_keys = (
        "pair_seconds",
        "inventory_seconds",
        "export_seconds",
        "srcdiff_seconds",
        "srcmove_seconds",
        "orchestration_seconds",
    )
    timing_totals: dict[str, float] = {}
    for key in timing_keys:
        timing_totals[key] = sum(
            float(value)
            for pair in pairs
            if isinstance(
                (value := pair.get("timings", {}).get(key)), (int, float)
            )
        )
    return {
        "selected_pairs": len(pairs),
        "completed": statuses.count("completed"),
        "no_analyzable_change": statuses.count("no_analyzable_change"),
        "failed": sum(
            status
            in {
                "export_failed",
                "srcdiff_failed",
                "srcmove_failed",
                "orchestration_failed",
            }
            for status in statuses
        ),
        "pending": statuses.count("pending") + statuses.count("running"),
        "move_group_count": sum(
            pair.get("metrics", {}).get("move_group_count", 0) for pair in completed
        ),
        "move_pair_count": sum(
            pair.get("metrics", {}).get("move_pair_count", 0) for pair in completed
        ),
        "annotated_region_count": sum(
            pair.get("metrics", {}).get("annotated_region_count", 0)
            for pair in completed
        ),
        "timings": timing_totals,
    }


def _seconds(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


def _duration(seconds: float) -> str:
    whole = max(0, round(seconds))
    minutes, seconds = divmod(whole, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def _pair_identity(
    pair: Mapping[str, Any], commits: Mapping[str, Mapping[str, Any]]
) -> str:
    new_commit = pair["new_commit"]
    subject = commits[new_commit]["subject"]
    return f"{pair['old_commit'][:8]} → {new_commit[:8]}  {subject}"


def _entry_failure_detail(entry: Mapping[str, Any]) -> str:
    error = entry.get("error")
    if isinstance(error, Mapping) and error.get("message"):
        return str(error["message"])
    status = str(entry.get("status", "failed"))
    if status == "srcdiff_failed":
        xml_status = entry.get("srcdiff_attempt", {}).get("xml", {}).get("status")
        return f"srcDiff failed{f' ({xml_status})' if xml_status else ''}"
    if status == "srcmove_failed":
        return "srcMove failed"
    return status.replace("_", " ")


SUMMARY_COLUMNS = [
    "sequence",
    "old_commit",
    "new_commit",
    "new_committer_time_iso8601",
    "new_commit_subject_display",
    "is_merge",
    "status",
    "changed_paths",
    "analyzable_changed_paths",
    "included_files",
    "excluded_files",
    "move_group_count",
    "move_pair_count",
    "annotated_region_count",
    "regions_total",
    "moved_region_share",
    "match_kind_exact_group_count",
    "match_kind_type2_group_count",
    "pair_seconds",
    "inventory_seconds",
    "export_seconds",
    "benchmark_seconds",
    "srcdiff_seconds",
    "srcmove_seconds",
    "orchestration_seconds",
    "repository_benchmark_id",
]


def _spreadsheet_safe(value: str) -> str:
    return f"'{value}" if value.startswith(("=", "+", "-", "@")) else value


def write_history_artifacts(
    history_dir: Path, history: dict[str, Any], data_root: Path
) -> None:
    history["aggregates"] = _aggregate(history["pairs"])
    history["updated_at"] = utc_now()
    write_json_atomic(history_dir / "history.json", history)

    commits = {commit["commit"]: commit for commit in history["commits"]}
    summary_path = history_dir / "summary.csv"
    temporary = summary_path.with_name(f".{summary_path.name}.tmp-{uuid.uuid4().hex}")
    with temporary.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=SUMMARY_COLUMNS)
        writer.writeheader()
        for pair in history["pairs"]:
            metrics = pair.get("metrics", {})
            regions_total = metrics.get("regions_total")
            annotated = metrics.get("annotated_region_count")
            share = (
                annotated / regions_total
                if isinstance(annotated, int) and isinstance(regions_total, int) and regions_total
                else None
            )
            writer.writerow(
                {
                    "sequence": pair["sequence"],
                    "old_commit": pair["old_commit"],
                    "new_commit": pair["new_commit"],
                    "new_committer_time_iso8601": commits[pair["new_commit"]][
                        "committer_time_iso8601"
                    ],
                    "new_commit_subject_display": _spreadsheet_safe(
                        commits[pair["new_commit"]]["subject"]
                    ),
                    "is_merge": commits[pair["new_commit"]]["is_merge"],
                    "status": pair["status"],
                    "changed_paths": pair.get("changed_paths"),
                    "analyzable_changed_paths": pair.get("analyzable_changed_paths"),
                    "included_files": pair.get("counts", {}).get("included_files"),
                    "excluded_files": pair.get("counts", {}).get("excluded_files"),
                    "move_group_count": metrics.get("move_group_count"),
                    "move_pair_count": metrics.get("move_pair_count"),
                    "annotated_region_count": annotated,
                    "regions_total": regions_total,
                    "moved_region_share": share,
                    "match_kind_exact_group_count": metrics.get("match_kinds", {}).get(
                        "exact"
                    ),
                    "match_kind_type2_group_count": metrics.get("match_kinds", {}).get(
                        "type2"
                    ),
                    "pair_seconds": pair.get("timings", {}).get("pair_seconds"),
                    "inventory_seconds": pair.get("timings", {}).get(
                        "inventory_seconds"
                    ),
                    "export_seconds": pair.get("timings", {}).get("export_seconds"),
                    "benchmark_seconds": pair.get("timings", {}).get(
                        "benchmark_seconds"
                    ),
                    "srcdiff_seconds": pair.get("timings", {}).get("srcdiff_seconds"),
                    "srcmove_seconds": pair.get("timings", {}).get("srcmove_seconds"),
                    "orchestration_seconds": pair.get("timings", {}).get(
                        "orchestration_seconds"
                    ),
                    "repository_benchmark_id": pair.get("repository_benchmark_id"),
                }
            )
    temporary.replace(summary_path)


def run_history_start(args: argparse.Namespace) -> tuple[dict[str, Any], Path]:
    history_started = time.monotonic()
    benchmark_root = SCRIPT_DIR
    case_dir = benchmark_root / args.case
    info_json = case_dir / "info.json"
    if not info_json.is_file():
        raise RuntimeError(f"missing repository case configuration: {info_json}")

    config = load_case_config(info_json)
    selected_dir = (
        normalize_repo_subdir(args.directory, "--directory")
        if args.directory is not None
        else config["directory"]
    )
    repo_url = config["github"]
    work_root = case_dir / "work"
    clone_dir = work_root / "repo"
    ensure_repo(repo_url, clone_dir, offline=args.offline, update=args.fetch)

    resolved_start, commits = select_first_parent_history(
        clone_dir, args.start, args.count
    )
    srcdiff = find_srcdiff(REPO_ROOT, args.srcdiff)
    srcmove = find_srcmove(REPO_ROOT, args.srcmove)
    if srcdiff is None:
        raise RuntimeError("srcdiff not found")
    if srcmove is None:
        raise RuntimeError("srcMove binary not found")

    history_id = _history_identifier(args.case)
    retained_ref = retain_start_commit(clone_dir, history_id, resolved_start)
    data_root = args.data_root.expanduser().resolve()
    history_dir = data_root / "repository-histories" / history_id
    history_dir.mkdir(parents=True, exist_ok=False)
    excluded_suffixes = sorted(DEFAULT_EXCLUDED_SUFFIXES)
    frozen_configuration = {
        "repository": repo_url,
        "directory": selected_dir,
        "commits": [commit.commit for commit in commits],
        "srcdiff_sha256": sha256_file(srcdiff),
        "srcmove_sha256": sha256_file(srcmove),
        "archive": True,
        "position": args.position,
        "source_encoding": args.src_encoding,
        "excluded_suffixes": excluded_suffixes,
        "input_scope": INPUT_SCOPE,
        "srcdiff_timeout_seconds": args.srcdiff_timeout,
        "srcmove_timeout_seconds": args.srcmove_timeout,
        "traversal_mode": TRAVERSAL_MODE,
    }
    pairs = [
        {
            "sequence": sequence,
            "pair_key": f"{history_id}:{sequence}",
            "old_commit": old.commit,
            "new_commit": new.commit,
            "status": "pending",
        }
        for sequence, (old, new) in enumerate(zip(commits, commits[1:]))
    ]
    history: dict[str, Any] = {
        "schema_version": HISTORY_SCHEMA_VERSION,
        "history_id": history_id,
        "status": "running",
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "label": args.label,
        "case": args.case,
        "repository": repo_url,
        "directory": selected_dir,
        "requested_start_revision": args.start,
        "resolved_start_commit": resolved_start,
        "retained_start_ref": retained_ref,
        "traversal_mode": TRAVERSAL_MODE,
        "requested_pair_count": args.count,
        "available_pair_count": len(pairs),
        "configuration": frozen_configuration,
        "configuration_fingerprint_sha256": _configuration_fingerprint(
            frozen_configuration
        ),
        "commits": [commit.as_json() for commit in commits],
        "pairs": pairs,
    }
    write_history_artifacts(history_dir, history, data_root)

    original_dir = work_root / "history-original"
    modified_dir = work_root / "history-modified"
    commits_by_id = {commit["commit"]: commit for commit in history["commits"]}
    for pair in history["pairs"]:
        pair_started = time.monotonic()
        progress = ProgressDisplay(
            f"Pair {pair['sequence'] + 1}/{len(history['pairs'])}",
            detail=_pair_identity(pair, commits_by_id),
        )
        progress.start()
        pair["status"] = "running"
        pair["started_at"] = utc_now()
        write_history_artifacts(history_dir, history, data_root)
        try:
            inventory_started = time.monotonic()
            changed, analyzable = inventory_changed_paths(
                clone_dir,
                pair["old_commit"],
                pair["new_commit"],
                selected_dir,
                excluded_suffixes,
            )
            inventory_seconds = time.monotonic() - inventory_started
            pair["changed_paths"] = len(changed)
            pair["analyzable_changed_paths"] = len(analyzable)
            pair["changed_path_records"] = [change.as_json() for change in changed]
            pair["analyzable_paths"] = [change.path for change in analyzable]
            if not analyzable:
                pair_seconds = time.monotonic() - pair_started
                pair.update(
                    {
                        "status": "no_analyzable_change",
                        "completed_at": utc_now(),
                        "timings": {
                            "pair_seconds": pair_seconds,
                            "inventory_seconds": inventory_seconds,
                            "export_seconds": 0.0,
                            "srcdiff_seconds": 0.0,
                            "srcmove_seconds": 0.0,
                            "orchestration_seconds": pair_seconds,
                        },
                    }
                )
                write_history_artifacts(history_dir, history, data_root)
                progress.finish(
                    f"{len(changed)} changed paths; no analyzable source changes",
                    completion="skipped",
                )
                continue
            try:
                export_started = time.monotonic()
                export_changed_files(
                    clone_dir,
                    pair["old_commit"],
                    pair["new_commit"],
                    analyzable,
                    original_dir,
                    modified_dir,
                )
                export_seconds = time.monotonic() - export_started
            except Exception as error:
                pair_seconds = time.monotonic() - pair_started
                pair.update(
                    {
                        "status": "export_failed",
                        "completed_at": utc_now(),
                        "error": {"type": type(error).__name__, "message": str(error)},
                        "timings": {
                            "pair_seconds": pair_seconds,
                            "inventory_seconds": inventory_seconds,
                            "export_seconds": time.monotonic() - export_started,
                            "srcdiff_seconds": 0.0,
                            "srcmove_seconds": 0.0,
                            "orchestration_seconds": pair_seconds,
                        },
                    }
                )
                write_history_artifacts(history_dir, history, data_root)
                progress.finish(str(error), success=False, completion="export failed")
                continue

            source = {
                "case": args.case,
                "repository": repo_url,
                "old_commit": pair["old_commit"],
                "new_commit": pair["new_commit"],
                "directory": selected_dir,
                "filtering_scope": {
                    "mode": INPUT_SCOPE,
                    "excluded_suffixes": excluded_suffixes,
                    "paths": [change.as_json() for change in analyzable],
                },
            }
            benchmark_started = time.monotonic()
            entry, entry_path = run_staged_repository_benchmark(
                data_root=data_root,
                series=history_id,
                case_name=args.case,
                original=original_dir,
                modified=modified_dir,
                source=source,
                srcdiff=srcdiff,
                srcmove=srcmove,
                srcdiff_timeout_seconds=args.srcdiff_timeout,
                srcmove_timeout_seconds=args.srcmove_timeout,
                use_position=args.position,
                use_archive=True,
                source_encoding=args.src_encoding,
                excluded_suffixes=[],
                show_progress=False,
            )
            benchmark_seconds = time.monotonic() - benchmark_started
            srcdiff_seconds = _seconds(
                entry.get("srcdiff_attempt", {}).get("elapsed_seconds")
            )
            srcmove_seconds = _seconds(
                entry.get("srcmove_attempt", {}).get("elapsed_seconds")
            )
            pair_seconds = time.monotonic() - pair_started
            pair.update(
                {
                    "status": entry["status"],
                    "completed_at": utc_now(),
                    "repository_benchmark_id": entry["benchmark_id"],
                    "repository_benchmark_path": _relative(entry_path, data_root),
                    "input_snapshot_id": entry.get("input_snapshot_id"),
                    "corpus_id": entry.get("corpus_id"),
                    "run_id": entry.get("run_id"),
                    "counts": entry.get("counts", {}),
                    "metrics": entry.get("results", {}),
                    "timings": {
                        "pair_seconds": pair_seconds,
                        "inventory_seconds": inventory_seconds,
                        "export_seconds": export_seconds,
                        "benchmark_seconds": benchmark_seconds,
                        "srcdiff_seconds": srcdiff_seconds,
                        "srcmove_seconds": srcmove_seconds,
                        "orchestration_seconds": max(
                            0.0, pair_seconds - srcdiff_seconds - srcmove_seconds
                        ),
                    },
                }
            )
            if entry["status"] != "completed":
                pair["error"] = {
                    "type": entry["status"],
                    "message": _entry_failure_detail(entry),
                }
            write_history_artifacts(history_dir, history, data_root)
            if entry["status"] == "completed":
                metrics = pair["metrics"]
                progress.finish(
                    f"{pair['counts'].get('included_files', 0)} files; "
                    f"{metrics.get('move_group_count', 0)} move groups, "
                    f"{metrics.get('move_pair_count', 0)} move pairs; "
                    f"srcDiff {srcdiff_seconds:.1f}s, "
                    f"srcMove {srcmove_seconds:.1f}s, "
                    f"overhead {pair['timings']['orchestration_seconds']:.1f}s",
                    completion="analyzed",
                )
            else:
                progress.finish(
                    _entry_failure_detail(entry),
                    success=False,
                    completion=entry["status"].replace("_", " "),
                )
        except Exception as error:
            pair_seconds = time.monotonic() - pair_started
            pair.update(
                {
                    "status": "orchestration_failed",
                    "completed_at": utc_now(),
                    "error": {"type": type(error).__name__, "message": str(error)},
                    "timings": {
                        **pair.get("timings", {}),
                        "pair_seconds": pair_seconds,
                        "orchestration_seconds": pair_seconds,
                    },
                }
            )
            history["status"] = "interrupted"
            history["elapsed_seconds"] = time.monotonic() - history_started
            write_history_artifacts(history_dir, history, data_root)
            progress.finish(
                str(error), success=False, completion="orchestration failed"
            )
            return history, history_dir

    history["status"] = (
        "completed" if _aggregate(history["pairs"])["failed"] == 0 else "completed_with_failures"
    )
    history["elapsed_seconds"] = time.monotonic() - history_started
    history["completed_at"] = utc_now()
    write_history_artifacts(history_dir, history, data_root)
    return history, history_dir


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark srcMove across adjacent first-parent commits."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    start = subparsers.add_parser("start", help="create and run a frozen history")
    start.add_argument("case")
    start.add_argument("--start", required=True)
    start.add_argument("--count", type=int, required=True, help="number of commit pairs")
    start.add_argument("--label")
    start.add_argument("--directory")
    network = start.add_mutually_exclusive_group()
    network.add_argument("--fetch", action="store_true")
    network.add_argument("--offline", action="store_true")
    start.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    start.add_argument("--srcdiff", type=Path)
    start.add_argument("--srcmove", type=Path)
    start.add_argument("--srcdiff-timeout", type=float, default=1800.0)
    start.add_argument("--srcmove-timeout", type=float, default=300.0)
    start.add_argument("--src-encoding", default="UTF-8")
    start.add_argument("--position", action="store_true")
    args = parser.parse_args(argv)
    if args.count <= 0:
        parser.error("--count must be positive")
    if args.srcdiff_timeout <= 0 or args.srcmove_timeout <= 0:
        parser.error("timeouts must be positive")
    return args


def print_history_summary(
    history: Mapping[str, Any], history_dir: Path, *, stream: TextIO = sys.stdout
) -> None:
    aggregates = history["aggregates"]
    timings = aggregates["timings"]
    title = history.get("label") or history["case"]
    status = str(history["status"]).replace("_", " ").capitalize()
    print(file=stream)
    print(f"Historical repository analysis: {title}", file=stream)
    print(f"  Status:  {status}", file=stream)
    print(f"  History: {history['history_id']}", file=stream)
    print(
        f"  Pairs:   {aggregates['completed']} analyzed, "
        f"{aggregates['no_analyzable_change']} skipped, "
        f"{aggregates['failed']} failed, {aggregates['pending']} pending",
        file=stream,
    )
    print(
        f"  Moves:   {aggregates['move_group_count']} groups, "
        f"{aggregates['move_pair_count']} pairs, "
        f"{aggregates['annotated_region_count']} annotated regions",
        file=stream,
    )
    print(
        f"  Time:    {_duration(_seconds(history.get('elapsed_seconds')))} total; "
        f"srcDiff {timings['srcdiff_seconds']:.1f}s, "
        f"srcMove {timings['srcmove_seconds']:.1f}s, "
        f"overhead {timings['orchestration_seconds']:.1f}s",
        file=stream,
    )

    failures = [
        pair
        for pair in history["pairs"]
        if pair["status"]
        in {
            "export_failed",
            "srcdiff_failed",
            "srcmove_failed",
            "orchestration_failed",
        }
    ]
    if failures:
        print(file=stream)
        print("Failures:", file=stream)
        for pair in failures:
            message = pair.get("error", {}).get("message", pair["status"])
            print(
                f"  {pair['sequence'] + 1}/{len(history['pairs'])} "
                f"{pair['old_commit'][:8]} → {pair['new_commit'][:8]} — {message}",
                file=stream,
            )

    print(file=stream)
    print("Artifacts:", file=stream)
    print(f"  Manifest: {(history_dir / 'history.json').resolve()}", file=stream)
    print(f"  Summary:  {(history_dir / 'summary.csv').resolve()}", file=stream)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    history, history_dir = run_history_start(args)
    print_history_summary(history, history_dir)
    return 0 if history["status"] == "completed" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
