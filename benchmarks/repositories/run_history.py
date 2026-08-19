#!/usr/bin/env python3
"""Run repository benchmarks across adjacent first-parent commits."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence, TextIO

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
from benchmarks.repositories.adapter import (
    GitRepositorySnapshotAdapter,
    GitSnapshotEntry,
    GitSnapshotMaterializationError,
)
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


HISTORY_SCHEMA_VERSION = 4
PAIR_SCHEMA_VERSION = 1
TRAVERSAL_MODE = "first_parent"
INPUT_SCOPE = "changed_files"
SAFE_HISTORY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
REGULAR_GIT_MODES = {"100644", "100755"}
PROFILE_TIMING_KEYS = (
    "srcdiff_input_snapshot_verification_seconds",
    "srcdiff_attempt_recovery_seconds",
    "srcdiff_executable_observation_seconds",
    "srcdiff_attempt_reconciliation_seconds",
    "srcdiff_corpus_verification_seconds",
    "srcmove_corpus_verification_seconds",
    "srcmove_attempt_recovery_seconds",
    "srcmove_observation_seconds",
    "srcmove_attempt_reconciliation_seconds",
    "history_artifact_write_seconds",
)


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


def _configuration_fingerprint(configuration: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(dict(configuration))).hexdigest()


def _aggregate(pairs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    statuses = [pair["status"] for pair in pairs]
    completed = [pair for pair in pairs if pair["status"] == "completed"]
    timing_keys = (
        "pair_seconds",
        "inventory_seconds",
        "export_seconds",
        "input_snapshot_seconds",
        "srcdiff_stage_seconds",
        "srcdiff_execution_seconds",
        "srcdiff_cached_execution_seconds",
        "cache_reuse_seconds",
        "srcmove_stage_seconds",
        "srcmove_execution_seconds",
        "other_seconds",
    ) + PROFILE_TIMING_KEYS
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


def _is_reused(value: object) -> bool:
    return isinstance(value, str) and "reused" in value


def _pair_timing_detail(pair: Mapping[str, Any]) -> str:
    timings = pair.get("timings", {})
    dispositions = pair.get("dispositions", {})
    details: list[str] = []
    srcdiff_execution = _seconds(timings.get("srcdiff_execution_seconds"))
    cached_execution = _seconds(
        timings.get("srcdiff_cached_execution_seconds")
    )
    cache_reuse = _seconds(timings.get("cache_reuse_seconds"))
    if _is_reused(dispositions.get("srcdiff_corpus")):
        details.append(
            f"cache {cache_reuse:.1f}s "
            f"(srcDiff reused; cached run {cached_execution:.1f}s)"
        )
    else:
        details.append(f"srcDiff {srcdiff_execution:.1f}s")
        if cache_reuse:
            details.append(f"cache {cache_reuse:.1f}s")
    details.append(
        f"srcMove {_seconds(timings.get('srcmove_execution_seconds')):.1f}s"
    )
    details.append(f"other {_seconds(timings.get('other_seconds')):.1f}s")
    return ", ".join(details)


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
    "input_snapshot_seconds",
    "srcdiff_stage_seconds",
    "srcdiff_execution_seconds",
    "srcdiff_cached_execution_seconds",
    "cache_reuse_seconds",
    "srcmove_stage_seconds",
    "srcmove_execution_seconds",
    "other_seconds",
    *PROFILE_TIMING_KEYS,
]


def _spreadsheet_safe(value: str) -> str:
    return f"'{value}" if value.startswith(("=", "+", "-", "@")) else value


def _replace_relative_symlink(link: Path, target: Path) -> None:
    target = target.resolve(strict=True)
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.exists() and link.resolve() == target:
        return
    if link.exists() and link.is_dir() and not link.is_symlink():
        raise ValueError(f"refusing to replace directory with browse link: {link}")
    temporary = link.with_name(f".{link.name}.tmp-{uuid.uuid4().hex}")
    try:
        temporary.symlink_to(os.path.relpath(target, start=link.parent))
        os.replace(temporary, link)
    finally:
        temporary.unlink(missing_ok=True)


def _positive_pair_artifacts(
    history_dir: Path, pair: Mapping[str, Any]
) -> dict[str, Path]:
    data_root = history_dir.parent.parent.resolve()
    artifacts = pair.get("artifacts", {})

    def artifact_path(key: str, description: str) -> Path:
        relative = artifacts.get(key)
        if not isinstance(relative, str):
            raise ValueError(
                f"positive pair {pair['sequence'] + 1} does not reference {description}"
            )
        path = (data_root / relative).resolve()
        if not path.is_relative_to(data_root):
            raise ValueError(f"unsafe {description} path: {relative}")
        if not path.is_file():
            raise FileNotFoundError(f"{description} not found: {path}")
        return path

    results = artifact_path("results_path", "results.json")
    retained = {"results.json": results}
    if not artifacts.get("srcmove_xml") and not artifacts.get("srcmove_attempt"):
        return retained
    if artifacts.get("srcmove_xml"):
        srcmove = artifact_path("srcmove_xml", "srcmove.xml")
    else:
        srcmove_attempt = artifact_path("srcmove_attempt", "srcMove attempt")
        srcmove = srcmove_attempt.parent / "srcmove.xml"
        if not srcmove.is_file():
            raise FileNotFoundError(
                f"positive pair {pair['sequence'] + 1} is missing srcmove.xml: {srcmove}"
            )

    if artifacts.get("srcdiff_xml"):
        srcdiff = artifact_path("srcdiff_xml", "srcdiff.xml")
    elif not artifacts.get("corpus_manifest"):
        return {**retained, "srcmove.xml": srcmove}
    else:
        corpus_manifest_path = artifact_path("corpus_manifest", "corpus manifest")
        corpus = json.loads(corpus_manifest_path.read_text(encoding="utf-8"))
        accepted = [
            case
            for case in corpus.get("cases", [])
            if isinstance(case, Mapping)
            and case.get("generation_status") == "accepted"
            and isinstance(case.get("input_path"), str)
        ]
        if len(accepted) != 1:
            raise ValueError(
                f"positive pair {pair['sequence'] + 1} must reference one accepted srcDiff XML"
            )
        srcdiff = (corpus_manifest_path.parent / accepted[0]["input_path"]).resolve()
        if not srcdiff.is_relative_to(corpus_manifest_path.parent.resolve()):
            raise ValueError(f"unsafe srcDiff corpus path: {accepted[0]['input_path']}")
        if not srcdiff.is_file():
            raise FileNotFoundError(f"srcDiff XML not found: {srcdiff}")
    return {**retained, "srcmove.xml": srcmove, "srcdiff.xml": srcdiff}


def refresh_history_browse_view(
    history_dir: Path, pairs: Sequence[Mapping[str, Any]]
) -> None:
    """Create a human-facing, zero-copy view of artifacts for positive pairs."""

    history_dir = history_dir.resolve()
    moves_dir = history_dir / "moves"
    moves_dir.mkdir(parents=True, exist_ok=True)
    retained_pair_names: set[str] = set()
    for pair in pairs:
        if _seconds(pair.get("metrics", {}).get("move_count")) <= 0:
            continue
        pair_name = f"{pair['sequence'] + 1:06d}"
        retained_pair_names.add(pair_name)
        browse_dir = moves_dir / pair_name
        artifacts = _positive_pair_artifacts(history_dir, pair)
        for obsolete_name in {"results.json", "srcmove.xml", "srcdiff.xml"} - set(
            artifacts
        ):
            obsolete = browse_dir / obsolete_name
            if obsolete.is_symlink() or obsolete.is_file():
                obsolete.unlink()
            elif obsolete.exists():
                raise ValueError(f"unexpected browse artifact directory: {obsolete}")
        for name, target in artifacts.items():
            _replace_relative_symlink(browse_dir / name, target)
    for child in moves_dir.iterdir():
        if child.name in retained_pair_names:
            continue
        if child.is_symlink() or child.is_file():
            child.unlink()
        else:
            shutil.rmtree(child)
    _replace_relative_symlink(history_dir.parent / "latest", history_dir)


def _history_entry_artifacts(
    entry: Mapping[str, Any], execution_root: Path, data_root: Path
) -> dict[str, str]:
    artifacts: dict[str, str] = {}
    for key in (
        "input_snapshot_manifest",
        "corpus_manifest",
        "run_manifest",
        "results_path",
    ):
        value = entry.get(key)
        if isinstance(value, str):
            artifacts[key] = (execution_root / value).resolve().relative_to(
                data_root
            ).as_posix()
    for key, attempt in (
        ("srcdiff_attempt", entry.get("srcdiff_attempt", {})),
        ("srcmove_attempt", entry.get("srcmove_attempt", {})),
    ):
        value = attempt.get("path") if isinstance(attempt, Mapping) else None
        if isinstance(value, str):
            artifacts[key] = (execution_root / value).resolve().relative_to(
                data_root
            ).as_posix()
    return artifacts


def _copy_canonical_artifact(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp-{uuid.uuid4().hex}")
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _remove_isolated_pipeline(history_dir: Path, pipeline_root: Path) -> None:
    history_dir = history_dir.resolve()
    pipeline_root = pipeline_root.resolve()
    if (
        pipeline_root.name != ".pipeline"
        or pipeline_root.parent != history_dir
        or pipeline_root.is_symlink()
    ):
        raise ValueError(f"unsafe isolated pipeline path: {pipeline_root}")
    if pipeline_root.is_dir():
        shutil.rmtree(pipeline_root)


def _failure_artifact_roots(
    pair: Mapping[str, Any], data_root: Path, pipeline_root: Path
) -> set[Path]:
    roots: set[Path] = set()
    artifacts = pair.get("artifacts", {})
    for key in (
        "input_snapshot_manifest",
        "corpus_manifest",
        "run_manifest",
        "results_path",
        "srcdiff_attempt",
        "srcmove_attempt",
    ):
        relative = artifacts.get(key)
        if not isinstance(relative, str):
            continue
        path = (data_root / relative).resolve()
        if not path.is_relative_to(pipeline_root):
            raise ValueError(f"compact failure artifact escaped pipeline: {path}")
        owner = path.parent
        if key in {"results_path", "srcmove_attempt"}:
            run_ancestor = next(
                (parent for parent in path.parents if parent.parent.name == "runs"),
                None,
            )
            if run_ancestor is not None:
                owner = run_ancestor
        roots.add(owner)
        if key == "corpus_manifest" and path.is_file():
            corpus = json.loads(path.read_text(encoding="utf-8"))
            generation_id = corpus.get("generation_id")
            if isinstance(generation_id, str):
                batch = pipeline_root / "generation-batches" / generation_id
                if batch.is_dir():
                    roots.add(batch.resolve())
    return roots


def _prune_isolated_pipeline(pipeline_root: Path, retained: set[Path]) -> None:
    for category in (
        "input-snapshots",
        "attempts",
        "generation-batches",
        "corpora",
        "runs",
        "repository-runs",
    ):
        category_dir = pipeline_root / category
        if not category_dir.is_dir():
            continue
        for child in category_dir.iterdir():
            resolved = child.resolve()
            keep = any(root == resolved or root.is_relative_to(resolved) for root in retained)
            if keep:
                continue
            if child.is_symlink() or child.is_file():
                child.unlink()
            else:
                shutil.rmtree(child)
        if not any(category_dir.iterdir()):
            category_dir.rmdir()


def finalize_history_retention(
    history_dir: Path,
    history: dict[str, Any],
    data_root: Path,
    pipeline_root: Path,
) -> None:
    policy = history["retention"]
    if policy == "full":
        return
    positive = [
        pair
        for pair in history["pairs"]
        if _seconds(pair.get("metrics", {}).get("move_count")) > 0
    ]
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
    if policy == "results":
        retained_results = 0
        for pair in history["pairs"]:
            if pair["status"] != "completed":
                pair.pop("artifacts", None)
                continue
            artifacts = pair.get("artifacts", {})
            relative = artifacts.get("results_path")
            if not isinstance(relative, str):
                raise ValueError(
                    f"completed pair {pair['sequence'] + 1} does not reference results.json"
                )
            source = (data_root / relative).resolve()
            if not source.is_relative_to(pipeline_root.resolve()):
                raise ValueError(f"results artifact escaped isolated pipeline: {source}")
            if not source.is_file():
                raise FileNotFoundError(f"srcMove results not found: {source}")
            destination = (
                history_dir / "results" / f"{pair['sequence'] + 1:06d}.json"
            )
            _copy_canonical_artifact(source, destination)
            pair["artifacts"] = {
                "results_path": destination.relative_to(data_root).as_posix()
            }
            retained_results += 1
        _remove_isolated_pipeline(history_dir, pipeline_root)
    elif policy == "compact":
        retained_results = len(positive)
        for pair in positive:
            browse_dir = history_dir / "moves" / f"{pair['sequence'] + 1:06d}"
            retained_artifacts = {}
            for name, source in _positive_pair_artifacts(history_dir, pair).items():
                destination = browse_dir / name
                _copy_canonical_artifact(source, destination)
                retained_artifacts[
                    {
                        "results.json": "results_path",
                        "srcmove.xml": "srcmove_xml",
                        "srcdiff.xml": "srcdiff_xml",
                    }[name]
                ] = destination.relative_to(data_root).as_posix()
            pair["artifacts"] = retained_artifacts
        retained_roots: set[Path] = set()
        for pair in failures:
            retained_roots.update(
                _failure_artifact_roots(pair, data_root, pipeline_root)
            )
        for pair in history["pairs"]:
            if pair not in positive and pair not in failures:
                pair.pop("artifacts", None)
        if retained_roots:
            _prune_isolated_pipeline(pipeline_root, retained_roots)
        else:
            _remove_isolated_pipeline(history_dir, pipeline_root)
    elif policy == "ephemeral":
        retained_results = 0
        for pair in history["pairs"]:
            pair.pop("artifacts", None)
        _remove_isolated_pipeline(history_dir, pipeline_root)
    else:
        raise ValueError(f"unknown retention policy: {policy}")
    history["retention_summary"] = {
        "result_pairs": retained_results,
        "positive_evidence_pairs": len(positive) if policy == "compact" else 0,
        "failure_evidence_pairs": len(failures) if policy == "compact" else 0,
        "discarded_successful_intermediate_pairs": sum(
            pair["status"] == "completed" for pair in history["pairs"]
        ),
    }
    history["retention_finalized_at"] = utc_now()


def write_history_artifacts(
    history_dir: Path,
    history: dict[str, Any],
    pair: Mapping[str, Any] | None = None,
) -> float:
    started = time.monotonic()
    history["aggregates"] = _aggregate(history["pairs"])
    history["updated_at"] = utc_now()
    pairs_dir = history_dir / "pairs"
    pairs_dir.mkdir(exist_ok=True)
    receipts = history["pairs"] if pair is None else [pair]
    for receipt in receipts:
        write_json_atomic(
            pairs_dir / f"{receipt['sequence'] + 1:06d}.json", receipt
        )
    manifest = {key: value for key, value in history.items() if key != "pairs"}
    manifest["pair_receipts"] = {
        "directory": "pairs",
        "filename_pattern": "%06d.json",
        "count": len(history["pairs"]),
    }
    write_json_atomic(history_dir / "history.json", manifest)

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
                    "changed_paths": pair.get("path_counts", {}).get("changed"),
                    "analyzable_changed_paths": pair.get("path_counts", {}).get(
                        "analyzable"
                    ),
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
                    "input_snapshot_seconds": pair.get("timings", {}).get(
                        "input_snapshot_seconds"
                    ),
                    "srcdiff_stage_seconds": pair.get("timings", {}).get(
                        "srcdiff_stage_seconds"
                    ),
                    "srcdiff_execution_seconds": pair.get("timings", {}).get(
                        "srcdiff_execution_seconds"
                    ),
                    "srcdiff_cached_execution_seconds": pair.get("timings", {}).get(
                        "srcdiff_cached_execution_seconds"
                    ),
                    "cache_reuse_seconds": pair.get("timings", {}).get(
                        "cache_reuse_seconds"
                    ),
                    "srcmove_stage_seconds": pair.get("timings", {}).get(
                        "srcmove_stage_seconds"
                    ),
                    "srcmove_execution_seconds": pair.get("timings", {}).get(
                        "srcmove_execution_seconds"
                    ),
                    "other_seconds": pair.get("timings", {}).get("other_seconds"),
                    **{
                        key: pair.get("timings", {}).get(key)
                        for key in PROFILE_TIMING_KEYS
                    },
                }
            )
    temporary.replace(summary_path)
    refresh_history_browse_view(
        history_dir, [] if history.get("retention") == "ephemeral" else receipts
    )
    return time.monotonic() - started


def checkpoint_history_pair(
    history_dir: Path,
    history: dict[str, Any],
    pair: dict[str, Any],
) -> float:
    """Atomically publish one ordered pair without rewriting history-wide views."""

    started = time.monotonic()
    history["updated_at"] = utc_now()
    pairs_dir = history_dir / "pairs"
    pairs_dir.mkdir(exist_ok=True)
    write_json_atomic(pairs_dir / f"{pair['sequence'] + 1:06d}.json", pair)
    elapsed = time.monotonic() - started
    pair.setdefault("timings", {})["history_artifact_write_seconds"] = elapsed
    # The receipt itself is the durable progress cursor. Its write duration is
    # added in memory and published when finalization rewrites all receipts. If
    # the process is killed first, the timing is honestly absent rather than
    # requiring a second self-referential receipt write.
    return elapsed


def _finalize_pair_timings(pair: dict[str, Any], pair_started: float) -> None:
    timings = pair.setdefault("timings", {})
    pair_seconds = time.monotonic() - pair_started
    timings["pair_seconds"] = pair_seconds
    timings["other_seconds"] = (
        pair_seconds
        - _seconds(timings.get("srcdiff_execution_seconds"))
        - _seconds(timings.get("cache_reuse_seconds"))
        - _seconds(timings.get("srcmove_execution_seconds"))
    )


def _run_history_pair(
    pair_template: Mapping[str, Any],
    *,
    pair_work_dir: Path,
    clone_dir: Path,
    selected_dir: str | None,
    excluded_suffixes: Sequence[str],
    pipeline_root: Path,
    data_root: Path,
    history_id: str,
    case_name: str,
    repo_url: str,
    srcdiff: Path,
    srcmove: Path,
    srcdiff_timeout: float,
    srcmove_timeout: float,
    position: bool,
    source_encoding: str,
) -> dict[str, Any]:
    """Execute one pair without touching coordinator-owned history state."""

    pair = dict(pair_template)
    pair_started = time.monotonic()
    pair.update({"status": "running", "started_at": utc_now()})
    inventory_seconds = 0.0
    export_seconds = 0.0
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
        pair["path_counts"] = {
            "changed": len(changed),
            "analyzable": len(analyzable),
        }
        pair["changed_paths"] = [change.as_json() for change in changed]
        if not analyzable:
            pair.update(
                {
                    "status": "no_analyzable_change",
                    "completed_at": utc_now(),
                    "timings": {
                        "inventory_seconds": inventory_seconds,
                        "export_seconds": 0.0,
                        "input_snapshot_seconds": 0.0,
                        "srcdiff_stage_seconds": 0.0,
                        "srcdiff_execution_seconds": 0.0,
                        "srcdiff_cached_execution_seconds": 0.0,
                        "cache_reuse_seconds": 0.0,
                        "srcmove_stage_seconds": 0.0,
                        "srcmove_execution_seconds": 0.0,
                    },
                }
            )
            _finalize_pair_timings(pair, pair_started)
            return pair

        source = {
            "case": case_name,
            "repository": repo_url,
            "old_commit": pair["old_commit"],
            "new_commit": pair["new_commit"],
            "directory": selected_dir,
            "filtering_scope": {
                "mode": INPUT_SCOPE,
                "excluded_suffixes": list(excluded_suffixes),
                "paths": [change.as_json() for change in analyzable],
            },
        }
        benchmark_started = time.monotonic()
        entry, _ = run_staged_repository_benchmark(
            data_root=pipeline_root,
            series=history_id,
            case_name=case_name,
            original=None,
            modified=None,
            source=source,
            srcdiff=srcdiff,
            srcmove=srcmove,
            srcdiff_timeout_seconds=srcdiff_timeout,
            srcmove_timeout_seconds=srcmove_timeout,
            use_position=position,
            use_archive=True,
            source_encoding=source_encoding,
            excluded_suffixes=[],
            show_progress=False,
            index_series=False,
            snapshot_adapter=GitRepositorySnapshotAdapter(
                case_id=case_name,
                repository=clone_dir,
                entries=[
                    GitSnapshotEntry(
                        path=change.path,
                        old_mode=change.old_mode,
                        new_mode=change.new_mode,
                        old_blob=change.old_blob,
                        new_blob=change.new_blob,
                    )
                    for change in analyzable
                ],
                work_dir=pair_work_dir,
                metadata={"source": source},
            ),
        )
        benchmark_seconds = time.monotonic() - benchmark_started
        entry_timings = entry.get("timings", {})
        dispositions = entry.get("dispositions", {})
        input_snapshot_seconds = _seconds(
            entry_timings.get("input_snapshot_wall_seconds")
        )
        srcdiff_stage_seconds = _seconds(
            entry_timings.get("srcdiff_stage_wall_seconds")
        )
        srcdiff_execution_seconds = _seconds(
            entry_timings.get("srcdiff_execution_seconds")
        )
        srcdiff_cached_execution_seconds = _seconds(
            entry_timings.get("srcdiff_cached_execution_seconds")
        )
        srcmove_stage_seconds = _seconds(
            entry_timings.get("srcmove_stage_wall_seconds")
        )
        srcmove_execution_seconds = _seconds(
            entry_timings.get("srcmove_execution_seconds")
        )
        cache_reuse_seconds = (
            input_snapshot_seconds
            if _is_reused(dispositions.get("input_snapshot"))
            else 0.0
        ) + (
            srcdiff_stage_seconds
            if _is_reused(dispositions.get("srcdiff_corpus"))
            else 0.0
        )
        pair.update(
            {
                "status": entry["status"],
                "completed_at": utc_now(),
                "artifacts": _history_entry_artifacts(
                    entry, pipeline_root, data_root
                ),
                "counts": entry.get("counts", {}),
                "metrics": entry.get("results", {}),
                "dispositions": dispositions,
                "timings": {
                    "inventory_seconds": inventory_seconds,
                    "export_seconds": export_seconds,
                    "benchmark_seconds": benchmark_seconds,
                    "input_snapshot_seconds": input_snapshot_seconds,
                    "srcdiff_stage_seconds": srcdiff_stage_seconds,
                    "srcdiff_execution_seconds": srcdiff_execution_seconds,
                    "srcdiff_cached_execution_seconds": (
                        srcdiff_cached_execution_seconds
                    ),
                    "cache_reuse_seconds": cache_reuse_seconds,
                    "srcmove_stage_seconds": srcmove_stage_seconds,
                    "srcmove_execution_seconds": srcmove_execution_seconds,
                    **{
                        key: _seconds(entry_timings.get(key))
                        for key in PROFILE_TIMING_KEYS
                        if key != "history_artifact_write_seconds"
                    },
                },
            }
        )
        if entry["status"] != "completed":
            pair["error"] = {
                "type": entry["status"],
                "message": _entry_failure_detail(entry),
            }
        _finalize_pair_timings(pair, pair_started)
        return pair
    except Exception as error:
        status = (
            "export_failed"
            if isinstance(error, GitSnapshotMaterializationError)
            else "orchestration_failed"
        )
        pair.update(
            {
                "status": status,
                "completed_at": utc_now(),
                "error": {"type": type(error).__name__, "message": str(error)},
                "timings": {
                    **pair.get("timings", {}),
                    "inventory_seconds": inventory_seconds,
                    "export_seconds": export_seconds,
                },
            }
        )
        _finalize_pair_timings(pair, pair_started)
        return pair


def _coordinate_history_pairs(
    history_dir: Path,
    history: dict[str, Any],
    *,
    jobs: int,
    worker_arguments: Mapping[str, Any],
    worker: Callable[..., dict[str, Any]] = _run_history_pair,
    progress: ProgressDisplay | None = None,
) -> None:
    """Run bounded workers and publish their results in deterministic order."""

    pair_work_root = history_dir / ".work"
    pair_work_root.mkdir(exist_ok=False)
    display = progress or ProgressDisplay(
        "History pairs",
        total=len(history["pairs"]),
        detail=f"{jobs} worker{'s' if jobs != 1 else ''}",
    )
    display.start()
    try:
        with ThreadPoolExecutor(
            max_workers=jobs,
            thread_name_prefix="history-pair",
        ) as executor:
            futures = [
                executor.submit(
                    worker,
                    pair,
                    pair_work_dir=(
                        pair_work_root / f"{pair['sequence'] + 1:06d}"
                    ),
                    **worker_arguments,
                )
                for pair in history["pairs"]
            ]
            # Later pairs may finish first, but only the coordinator publishes
            # receipts and terminal output, always in selected sequence order.
            for sequence, future in enumerate(futures):
                pair = future.result()
                if pair["sequence"] != sequence:
                    raise RuntimeError("history worker returned an out-of-order pair")
                history["pairs"][sequence] = pair
                checkpoint_history_pair(history_dir, history, pair)
                if pair["status"] == "completed":
                    metrics = pair["metrics"]
                    detail = (
                        f"pair {sequence + 1}: "
                        f"{pair['counts'].get('included_files', 0)} files; "
                        f"{metrics.get('move_group_count', 0)} move groups, "
                        f"{metrics.get('move_pair_count', 0)} move pairs"
                    )
                elif pair["status"] == "no_analyzable_change":
                    detail = (
                        f"pair {sequence + 1}: "
                        f"{pair.get('path_counts', {}).get('changed', 0)} changed "
                        "paths; skipped"
                    )
                else:
                    detail = f"pair {sequence + 1}: {_entry_failure_detail(pair)}"
                display.update(sequence + 1, detail=detail)
    except BaseException as error:
        display.finish(str(error), success=False, completion="interrupted")
        raise
    finally:
        if pair_work_root.is_dir() and not pair_work_root.is_symlink():
            shutil.rmtree(pair_work_root)
    display.finish(
        f"processed with {jobs} worker{'s' if jobs != 1 else ''}",
        completion="complete",
    )


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
    pipeline_root = (
        data_root if args.retention == "full" else history_dir / ".pipeline"
    )
    if pipeline_root != data_root:
        pipeline_root.mkdir(parents=True, exist_ok=False)
    excluded_suffixes = sorted(DEFAULT_EXCLUDED_SUFFIXES)
    frozen_configuration = {
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
            "schema_version": PAIR_SCHEMA_VERSION,
            "sequence": sequence,
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
        "retention": args.retention,
        "cache_reuse_enabled": args.retention == "full",
        "jobs": args.jobs,
        "traversal_mode": TRAVERSAL_MODE,
        "requested_pair_count": args.count,
        "available_pair_count": len(pairs),
        "configuration": frozen_configuration,
        "configuration_fingerprint_sha256": _configuration_fingerprint(
            {
                "repository": repo_url,
                "directory": selected_dir,
                "commits": [commit.commit for commit in commits],
                **frozen_configuration,
            }
        ),
        "commits": [commit.as_json() for commit in commits],
        "pairs": pairs,
    }
    write_history_artifacts(history_dir, history)

    worker_arguments = {
        "clone_dir": clone_dir,
        "selected_dir": selected_dir,
        "excluded_suffixes": excluded_suffixes,
        "pipeline_root": pipeline_root,
        "data_root": data_root,
        "history_id": history_id,
        "case_name": args.case,
        "repo_url": repo_url,
        "srcdiff": srcdiff,
        "srcmove": srcmove,
        "srcdiff_timeout": args.srcdiff_timeout,
        "srcmove_timeout": args.srcmove_timeout,
        "position": args.position,
        "source_encoding": args.src_encoding,
    }
    try:
        _coordinate_history_pairs(
            history_dir,
            history,
            jobs=args.jobs,
            worker_arguments=worker_arguments,
        )
    except BaseException:
        history["status"] = "interrupted"
        history["elapsed_seconds"] = time.monotonic() - history_started
        write_history_artifacts(history_dir, history)
        raise

    history["status"] = (
        "completed" if _aggregate(history["pairs"])["failed"] == 0 else "completed_with_failures"
    )
    history["elapsed_seconds"] = time.monotonic() - history_started
    history["completed_at"] = utc_now()
    finalize_history_retention(
        history_dir, history, data_root, pipeline_root
    )
    write_history_artifacts(history_dir, history)
    return history, history_dir


def _load_json_object(path: Path, description: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read {description}: {path}: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{description} must contain a JSON object: {path}")
    return value


def resolve_history_directory(data_root: Path, selector: str | None) -> Path:
    """Resolve a history ID, path, label, or the latest history."""

    data_root = data_root.expanduser().resolve()
    histories_root = data_root / "repository-histories"
    if selector is not None:
        supplied = Path(selector).expanduser()
        direct_candidates = [
            supplied,
            supplied.parent if supplied.name == "history.json" else supplied,
            histories_root / selector,
        ]
        for candidate in direct_candidates:
            resolved = candidate.resolve()
            if (resolved / "history.json").is_file():
                return resolved

    candidates = [
        directory
        for directory in histories_root.glob("history-*")
        if (directory / "history.json").is_file()
    ]
    if selector is not None:
        candidates = [
            directory
            for directory in candidates
            if _load_json_object(directory / "history.json", "history manifest").get(
                "label"
            )
            == selector
        ]
        if not candidates:
            raise FileNotFoundError(
                f"history ID, path, or label not found: {selector}"
            )
    if not candidates:
        raise FileNotFoundError(f"no histories found below {histories_root}")
    return max(
        candidates,
        key=lambda directory: (directory / "history.json").stat().st_mtime_ns,
    ).resolve()


def load_history_results(history_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest = _load_json_object(history_dir / "history.json", "history manifest")
    if manifest.get("schema_version") != HISTORY_SCHEMA_VERSION:
        raise ValueError(
            f"history results require schema {HISTORY_SCHEMA_VERSION}: {history_dir}"
        )
    receipt_configuration = manifest.get("pair_receipts", {})
    expected_count = receipt_configuration.get("count")
    pairs_dir = history_dir / receipt_configuration.get("directory", "pairs")
    receipt_paths = sorted(pairs_dir.glob("*.json"))
    if not isinstance(expected_count, int) or len(receipt_paths) != expected_count:
        raise ValueError(
            f"history pair receipt count mismatch: expected {expected_count}, "
            f"found {len(receipt_paths)}"
        )
    pairs = [
        _load_json_object(path, "history pair receipt") for path in receipt_paths
    ]
    if [pair.get("sequence") for pair in pairs] != list(range(len(pairs))):
        raise ValueError("history pair receipts are not a contiguous ordered sequence")
    return manifest, pairs


def _resolve_artifact(data_root: Path, relative: object, description: str) -> Path:
    if not isinstance(relative, str):
        raise ValueError(f"pair receipt does not reference {description}")
    root = data_root.expanduser().resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"unsafe {description} path: {relative}")
    if not path.is_file():
        raise FileNotFoundError(f"{description} not found: {path}")
    return path


def _xpath_location(xpath: object) -> str | None:
    if not isinstance(xpath, str):
        return None
    filename = re.search(r"@filename='([^']+)'", xpath)
    function = re.search(r"src:function\[src:name='([^']+)'\]", xpath)
    parts = []
    if filename:
        parts.append(filename.group(1))
    if function:
        parts.append(function.group(1))
    return " :: ".join(parts) if parts else None


def _move_filenames(move: Mapping[str, Any]) -> set[str]:
    filenames = set()
    for key in ("from_xpaths", "to_xpaths"):
        values = move.get(key)
        if not isinstance(values, list):
            continue
        for xpath in values:
            if isinstance(xpath, str) and (
                match := re.search(r"@filename='([^']+)'", xpath)
            ):
                filenames.add(match.group(1))
    return filenames


def _print_move_side(
    label: str, xpaths: object, raw_texts: object, *, verbose: bool, stream: TextIO
) -> None:
    paths = xpaths if isinstance(xpaths, list) else []
    texts = raw_texts if isinstance(raw_texts, list) else []
    item_count = max(len(paths), len(texts))
    for index in range(item_count):
        xpath = paths[index] if index < len(paths) else None
        raw_text = texts[index] if index < len(texts) else ""
        location = _xpath_location(xpath)
        suffix = f"  {location}" if location else ""
        item_label = label if item_count == 1 else f"{label} {index + 1}"
        print(f"    {item_label}:{suffix}", file=stream)
        lines = str(raw_text).splitlines() or [""]
        for line in lines:
            print(f"      {line}", file=stream)
        if verbose and isinstance(xpath, str):
            print(f"      XPath: {xpath}", file=stream)


def _print_pair_diff(
    history: Mapping[str, Any],
    pair: Mapping[str, Any],
    paths: Sequence[str] = (),
    *,
    stream: TextIO,
) -> None:
    case = history.get("case")
    if not isinstance(case, str):
        raise ValueError("history manifest does not identify its repository case")
    repo_dir = SCRIPT_DIR / case / "work" / "repo"
    if not (repo_dir / ".git").exists():
        raise FileNotFoundError(f"repository cache not found: {repo_dir}")
    selected_paths = list(paths) or [
        record["path"]
        for record in pair.get("changed_paths", [])
        if isinstance(record, Mapping) and isinstance(record.get("path"), str)
    ]
    command = [
        "git",
        "diff",
        "--no-ext-diff",
        "--unified=8",
        pair["old_commit"],
        pair["new_commit"],
        "--",
        *selected_paths,
    ]
    result = run(command, cwd=repo_dir)
    require_ok(result, f"git diff for history pair {pair['sequence'] + 1}")
    print("\n  Git diff:", file=stream)
    print(result.stdout.rstrip() or "    (empty)", file=stream)


def print_history_results(
    history: Mapping[str, Any],
    pairs: Sequence[Mapping[str, Any]],
    data_root: Path,
    *,
    pair_number: int | None = None,
    show_diff: bool = False,
    verbose: bool = False,
    stream: TextIO = sys.stdout,
) -> None:
    if pair_number is not None:
        if pair_number < 1 or pair_number > len(pairs):
            raise ValueError(f"pair must be between 1 and {len(pairs)}")
        selected = [pairs[pair_number - 1]]
    else:
        selected = [
            pair
            for pair in pairs
            if _seconds(pair.get("metrics", {}).get("move_count")) > 0
        ]

    title = history.get("label") or history.get("case") or history["history_id"]
    total_moves = sum(
        int(_seconds(pair.get("metrics", {}).get("move_count"))) for pair in selected
    )
    positive_pairs = sum(
        _seconds(pair.get("metrics", {}).get("move_count")) > 0 for pair in pairs
    )
    print(f"Historical move results: {title}", file=stream)
    print(f"  History: {history['history_id']}", file=stream)
    print(
        f"  Detected: {history.get('aggregates', {}).get('move_group_count', 0)} groups, "
        f"{history.get('aggregates', {}).get('move_pair_count', 0)} pairs "
        f"across {positive_pairs}/{len(pairs)} commit pairs",
        file=stream,
    )
    if pair_number is None and not selected:
        print("\nNo moves were detected.", file=stream)
        return

    commits = {
        commit.get("commit"): commit
        for commit in history.get("commits", [])
        if isinstance(commit, Mapping)
    }
    for pair in selected:
        number = pair["sequence"] + 1
        metrics = pair.get("metrics", {})
        subject = commits.get(pair["new_commit"], {}).get("subject")
        print(file=stream)
        print(
            f"Pair {number}/{len(pairs)}  "
            f"{pair['old_commit'][:8]} → {pair['new_commit'][:8]}",
            file=stream,
        )
        if subject:
            print(f"  Commit: {subject}", file=stream)
        print(f"  Status: {str(pair['status']).replace('_', ' ')}", file=stream)
        print(
            f"  Moves:  {metrics.get('move_group_count', 0)} groups, "
            f"{metrics.get('move_pair_count', 0)} pairs, "
            f"{metrics.get('annotated_region_count', 0)} annotated regions",
            file=stream,
        )
        if pair.get("error"):
            print(f"  Failure: {pair['error'].get('message', pair['error'])}", file=stream)

        move_count = int(_seconds(metrics.get("move_count")))
        moved_paths: set[str] = set()
        if move_count:
            results_reference = pair.get("artifacts", {}).get("results_path")
            if not isinstance(results_reference, str):
                print(
                    "  Move details were not retained by this history's "
                    "retention policy.",
                    file=stream,
                )
                if show_diff:
                    _print_pair_diff(history, pair, stream=stream)
                continue
            results_path = _resolve_artifact(
                data_root,
                results_reference,
                "srcMove results",
            )
            results = _load_json_object(results_path, "srcMove results")
            moves = results.get("moves")
            if not isinstance(moves, list) or len(moves) != move_count:
                raise ValueError(
                    f"move detail count mismatch for pair {number}: "
                    f"expected {move_count}"
                )
            for index, move in enumerate(moves, start=1):
                if not isinstance(move, Mapping):
                    raise ValueError(f"invalid move detail for pair {number}")
                moved_paths.update(_move_filenames(move))
                print(
                    f"\n  Move {index}/{len(moves)}  "
                    f"{move.get('match_kind', 'unknown')}  "
                    f"id={move.get('move_id', 'unknown')}",
                    file=stream,
                )
                _print_move_side(
                    "From",
                    move.get("from_xpaths"),
                    move.get("from_raw_texts"),
                    verbose=verbose,
                    stream=stream,
                )
                _print_move_side(
                    "To",
                    move.get("to_xpaths"),
                    move.get("to_raw_texts"),
                    verbose=verbose,
                    stream=stream,
                )
            if verbose:
                print(f"\n  Results: {results_path}", file=stream)
                srcmove_reference = pair.get("artifacts", {}).get("srcmove_xml")
                if isinstance(srcmove_reference, str):
                    srcmove_xml = _resolve_artifact(
                        data_root, srcmove_reference, "srcMove XML"
                    )
                else:
                    attempt_path = _resolve_artifact(
                        data_root,
                        pair.get("artifacts", {}).get("srcmove_attempt"),
                        "srcMove attempt",
                    )
                    srcmove_xml = attempt_path.parent / "srcmove.xml"
                if srcmove_xml.is_file():
                    print(f"  Annotated XML: {srcmove_xml}", file=stream)
        elif pair["status"] == "completed":
            print("  No moves detected in this pair.", file=stream)

        if show_diff:
            _print_pair_diff(history, pair, sorted(moved_paths), stream=stream)

    if pair_number is None:
        print(
            f"\nShown {total_moves} moves from {len(selected)} positive pairs.",
            file=stream,
        )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark srcMove across adjacent first-parent commits."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    start = subparsers.add_parser("start", help="create and run a frozen history")
    start.add_argument("case")
    start.add_argument("--start", required=True)
    start.add_argument("--count", type=int, required=True, help="number of commit pairs")
    start.add_argument(
        "--jobs",
        type=int,
        default=1,
        help="maximum concurrent commit pairs; default: 1",
    )
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
    retention = start.add_mutually_exclusive_group()
    retention.add_argument(
        "--retention",
        choices=("results", "full", "compact", "ephemeral"),
        default="results",
        help="artifact retention policy; default: results",
    )
    retention.add_argument(
        "--no-cache",
        action="store_const",
        dest="retention",
        const="results",
        help="alias for --retention results",
    )
    show = subparsers.add_parser(
        "show", help="show detected moves from a saved history"
    )
    show.add_argument(
        "history",
        nargs="?",
        help="history ID, path, or label; defaults to the latest history",
    )
    show.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    show.add_argument("--pair", type=int, help="show one 1-based pair number")
    show.add_argument("--diff", action="store_true", help="include the Git diff")
    show.add_argument(
        "--verbose",
        action="store_true",
        help="include XPaths and canonical artifact paths",
    )
    args = parser.parse_args(argv)
    if args.command == "start":
        if args.count <= 0:
            parser.error("--count must be positive")
        if args.jobs <= 0:
            parser.error("--jobs must be positive")
        if args.srcdiff_timeout <= 0 or args.srcmove_timeout <= 0:
            parser.error("timeouts must be positive")
    elif args.pair is not None and args.pair <= 0:
        parser.error("--pair must be positive")
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
    retention = history.get("retention", "full")
    print(
        f"  Storage: {str(retention).capitalize()} retention"
        + ("; reusable cache enabled" if retention == "full" else "; isolated run"),
        file=stream,
    )
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
    elapsed_seconds = _seconds(history.get("elapsed_seconds"))
    srcdiff_execution = timings["srcdiff_execution_seconds"]
    cache_reuse = timings["cache_reuse_seconds"]
    srcmove_execution = timings["srcmove_execution_seconds"]
    jobs = history.get("jobs", 1)
    if isinstance(jobs, int) and jobs > 1:
        print(
            f"  Time:    {_duration(elapsed_seconds)} wall; summed pair work: "
            f"srcDiff execution {srcdiff_execution:.1f}s, "
            f"cache reuse {cache_reuse:.1f}s, "
            f"srcMove execution {srcmove_execution:.1f}s, "
            f"other {timings['other_seconds']:.1f}s",
            file=stream,
        )
    else:
        other = elapsed_seconds - srcdiff_execution - cache_reuse - srcmove_execution
        print(
            f"  Time:    {_duration(elapsed_seconds)} total; "
            f"srcDiff execution {srcdiff_execution:.1f}s, "
            f"cache reuse {cache_reuse:.1f}s, "
            f"srcMove execution {srcmove_execution:.1f}s, "
            f"other {other:.1f}s",
            file=stream,
        )
    cached_execution = timings["srcdiff_cached_execution_seconds"]
    if cached_execution:
        print(
            f"  Cached:  srcDiff execution provenance {cached_execution:.1f}s "
            "(not included in current time)",
            file=stream,
        )
    print(
        "  Profile: srcDiff snapshot verify "
        f"{timings['srcdiff_input_snapshot_verification_seconds']:.1f}s, "
        f"recovery {timings['srcdiff_attempt_recovery_seconds']:.1f}s, "
        f"reconciliation {timings['srcdiff_attempt_reconciliation_seconds']:.1f}s, "
        f"corpus verify {timings['srcdiff_corpus_verification_seconds']:.1f}s",
        file=stream,
    )
    print(
        "           srcMove corpus verify "
        f"{timings['srcmove_corpus_verification_seconds']:.1f}s, "
        f"recovery {timings['srcmove_attempt_recovery_seconds']:.1f}s, "
        f"observation {timings['srcmove_observation_seconds']:.1f}s, "
        f"reconciliation {timings['srcmove_attempt_reconciliation_seconds']:.1f}s",
        file=stream,
    )
    print(
        "           history artifacts "
        f"{timings['history_artifact_write_seconds']:.1f}s",
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
    if args.command == "show":
        history_dir = resolve_history_directory(args.data_root, args.history)
        history, pairs = load_history_results(history_dir)
        print_history_results(
            history,
            pairs,
            args.data_root,
            pair_number=args.pair,
            show_diff=args.diff,
            verbose=args.verbose,
        )
        return 0
    history, history_dir = run_history_start(args)
    print_history_summary(history, history_dir)
    return 0 if history["status"] == "completed" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
