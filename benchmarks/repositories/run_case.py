#!/usr/bin/env python3
"""Run and save one repository benchmark through the staged pipeline."""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Mapping

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
TESTS_ROOT = REPO_ROOT / "tests"
for import_root in (REPO_ROOT, TESTS_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from benchmarks.contracts import RunMode
from benchmarks.corpus import (
    DEFAULT_EXCLUDED_SUFFIXES,
    create_input_snapshot,
    generate_corpus,
    run_corpus,
)
from benchmarks.process import write_json_atomic
from benchmarks.progress import ProgressDisplay
from benchmarks.provenance import utc_now
from benchmarks.repositories.adapter import RepositoryAdapter
from support.tooling import (
    find_srcdiff,
    find_srcmove,
    format_process_failure,
    run_command as run,
)


DEFAULT_DATA_ROOT = REPO_ROOT / "benchmark-data"
SAFE_SERIES_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def require_ok(result: subprocess.CompletedProcess, what: str) -> None:
    if result.returncode != 0:
        raise RuntimeError(format_process_failure(what, result))


def normalize_repo_subdir(value: object, context: str) -> str | None:
    if value is None:
        return None

    if not isinstance(value, str):
        raise RuntimeError(f"invalid 'directory' in {context}: must be a string")

    subdir = value.strip()
    if not subdir:
        return None

    subdir = subdir.replace("\\", "/").strip("/")

    if subdir in (".", "./"):
        return None

    if subdir.startswith("../") or "/../" in subdir or subdir == "..":
        raise RuntimeError(f"invalid 'directory' in {context}: must stay within the repository")

    return subdir


def load_case_config(info_json: Path) -> dict:
    with info_json.open("r", encoding="utf-8") as f:
        data = json.load(f)

    repo_url = data.get("github")
    if not isinstance(repo_url, str) or not repo_url:
        raise RuntimeError(f"missing or invalid 'github' field in {info_json}")

    old_rev = data.get("old_rev")
    new_rev = data.get("new_rev")
    directory = normalize_repo_subdir(data.get("directory"), str(info_json))

    if old_rev is not None and (not isinstance(old_rev, str) or not old_rev):
        raise RuntimeError(f"invalid 'old_rev' in {info_json}")
    if new_rev is not None and (not isinstance(new_rev, str) or not new_rev):
        raise RuntimeError(f"invalid 'new_rev' in {info_json}")

    return {
        "github": repo_url,
        "old_rev": old_rev,
        "new_rev": new_rev,
        "directory": directory,
    }


def is_git_repo(path: Path) -> bool:
    return (path / ".git").exists()


def get_origin_url(repo_dir: Path) -> str | None:
    result = run(["git", "remote", "get-url", "origin"], cwd=repo_dir)
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def clone_repo(repo_url: str, clone_dir: Path) -> None:
    clone_dir.parent.mkdir(parents=True, exist_ok=True)
    result = run(["git", "clone", repo_url, str(clone_dir)])
    require_ok(result, "git clone")


def update_repo(repo_dir: Path) -> None:
    result = run(["git", "fetch", "origin", "--tags", "--prune"], cwd=repo_dir)
    require_ok(result, "git fetch origin --tags --prune")


def ensure_repo(
    repo_url: str,
    clone_dir: Path,
    *,
    offline: bool,
    update: bool,
) -> bool:
    """Prepare the repository cache and report whether network work was done."""
    if not clone_dir.exists():
        if offline:
            raise RuntimeError(
                f"repository cache is missing in offline mode: {clone_dir}"
            )
        clone_repo(repo_url, clone_dir)
        return True

    if not is_git_repo(clone_dir):
        raise RuntimeError(f"existing path is not a git repo: {clone_dir}")

    current_origin = get_origin_url(clone_dir)
    if current_origin != repo_url:
        raise RuntimeError(
            f"cached repository origin mismatch: expected {repo_url}, found {current_origin}"
        )

    if update:
        update_repo(clone_dir)
        return True

    return False


def resolve_commit(repo_dir: Path, rev: str) -> str:
    result = run(["git", "rev-parse", "--verify", f"{rev}^{{commit}}"], cwd=repo_dir)
    require_ok(result, f"git rev-parse {rev}")
    return result.stdout.strip()


def resolve_requested_commits(
    repo_dir: Path,
    old_rev: str,
    new_rev: str,
    *,
    offline: bool,
    repository_updated: bool,
) -> tuple[str, str]:
    try:
        return resolve_commit(repo_dir, old_rev), resolve_commit(repo_dir, new_rev)
    except RuntimeError as error:
        if offline:
            raise RuntimeError(
                "requested revision is unavailable in the offline repository cache"
            ) from error
        if repository_updated:
            raise

    print("      requested revision not cached; fetching once")
    update_repo(repo_dir)
    return resolve_commit(repo_dir, old_rev), resolve_commit(repo_dir, new_rev)


def export_commit(
    repo_dir: Path, commit: str, out_dir: Path, subdir: str | None = None
) -> None:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    archive_cmd = ["git", "archive", commit]
    if subdir:
        archive_cmd.append(subdir)

    extract_cmd = ["tar", "-x", "-C", str(out_dir)]

    p1 = subprocess.Popen(
        archive_cmd,
        cwd=str(repo_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
    )
    p2 = subprocess.Popen(
        extract_cmd,
        stdin=p1.stdout,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
    )

    assert p1.stdout is not None
    p1.stdout.close()

    _, err2 = p2.communicate()
    _, err1 = p1.communicate()

    if p1.returncode != 0:
        extra = f" (subdir={subdir})" if subdir else ""
        raise RuntimeError(
            f"git archive failed for {commit}{extra}\n"
            f"stderr:\n{err1.decode(errors='replace')}"
        )

    if p2.returncode != 0:
        extra = f" (subdir={subdir})" if subdir else ""
        raise RuntimeError(
            f"tar extract failed for {commit}{extra}\n"
            f"stderr:\n{err2.decode(errors='replace')}"
        )


def validate_storage_name(value: str, kind: str) -> str:
    if not SAFE_SERIES_RE.fullmatch(value):
        raise ValueError(
            f"{kind} must start with an alphanumeric character and contain only "
            f"letters, digits, '.', '_', or '-': {value!r}"
        )
    return value


def validate_series_name(value: str) -> str:
    return validate_storage_name(value, "series")


def _relative_to_data_root(path: Path, data_root: Path) -> str:
    return path.resolve().relative_to(data_root.resolve()).as_posix()


def _attempt_summary(path: Path, data_root: Path) -> dict[str, Any]:
    if not path.is_file():
        return {
            "status": "missing",
            "path": _relative_to_data_root(path, data_root),
        }
    attempt = json.loads(path.read_text(encoding="utf-8"))
    return {
        "attempt_id": attempt["attempt_id"],
        "path": _relative_to_data_root(path, data_root),
        "termination": attempt["termination"],
        "elapsed_seconds": attempt.get("process_elapsed_seconds"),
        "resource_usage": attempt.get("resource_usage", {}),
        "xml": attempt.get("xml", {}),
    }


def _results_summary(run_dir: Path, run_manifest: Mapping[str, Any]) -> dict[str, Any]:
    completed = [case for case in run_manifest["cases"] if case["status"] == "completed"]
    if not completed:
        return {}
    results_path = run_dir / completed[0]["results"]["path"]
    if not results_path.is_file():
        return {}
    value = json.loads(results_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        return {}
    fields = (
        "move_count",
        "move_group_count",
        "move_pair_count",
        "annotated_region_count",
        "regions_total",
        "candidates_total",
        "groups_total",
        "group_kinds",
        "match_kinds",
    )
    return {field: value[field] for field in fields if field in value}


SERIES_COLUMNS = [
    "benchmark_id",
    "created_at",
    "case",
    "requested_old_revision",
    "requested_new_revision",
    "old_commit",
    "new_commit",
    "status",
    "included_files",
    "excluded_files",
    "input_snapshot_id",
    "corpus_id",
    "run_id",
    "srcdiff_accepted",
    "srcdiff_failed",
    "srcdiff_xml_status",
    "srcdiff_seconds",
    "srcdiff_stage_wall_seconds",
    "srcdiff_execution_seconds",
    "srcdiff_cached_execution_seconds",
    "srcdiff_peak_rss_bytes",
    "srcmove_completed",
    "srcmove_failed",
    "srcmove_xml_status",
    "srcmove_seconds",
    "srcmove_stage_wall_seconds",
    "srcmove_execution_seconds",
    "srcmove_peak_rss_bytes",
    "pipeline_wall_seconds",
    "move_count",
    "move_group_count",
    "move_pair_count",
    "annotated_region_count",
    "regions_total",
]


def update_series(data_root: Path, series: str, entry: Mapping[str, Any]) -> Path:
    series_dir = data_root / "repository-runs" / validate_series_name(series)
    manifest_path = series_dir / f"{entry['benchmark_id']}.json"
    write_json_atomic(manifest_path, entry)

    summary_path = series_dir / "summary.csv"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = summary_path.with_name(
        f".{summary_path.name}.tmp-{uuid.uuid4().hex}"
    )
    with temporary.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=SERIES_COLUMNS)
        writer.writeheader()
        manifests = sorted(
            path for path in series_dir.glob("repository-*.json") if path != manifest_path
        )
        manifests.append(manifest_path)
        for benchmark_path in manifests:
            benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
            counts = benchmark.get("counts", {})
            results = benchmark.get("results", {})
            srcdiff_attempt = benchmark.get("srcdiff_attempt", {})
            srcmove_attempt = benchmark.get("srcmove_attempt", {})
            timings = benchmark.get("timings", {})
            writer.writerow(
                {
                    "benchmark_id": benchmark.get("benchmark_id"),
                    "created_at": benchmark.get("created_at"),
                    "case": benchmark.get("case"),
                    "requested_old_revision": benchmark.get("source", {}).get(
                        "requested_old_revision"
                    ),
                    "requested_new_revision": benchmark.get("source", {}).get(
                        "requested_new_revision"
                    ),
                    "old_commit": benchmark.get("source", {}).get("old_commit"),
                    "new_commit": benchmark.get("source", {}).get("new_commit"),
                    "status": benchmark.get("status"),
                    "included_files": counts.get("included_files"),
                    "excluded_files": counts.get("excluded_files"),
                    "input_snapshot_id": benchmark.get("input_snapshot_id"),
                    "corpus_id": benchmark.get("corpus_id"),
                    "run_id": benchmark.get("run_id"),
                    "srcdiff_accepted": counts.get("srcdiff_accepted"),
                    "srcdiff_failed": counts.get("srcdiff_failed"),
                    "srcdiff_xml_status": srcdiff_attempt.get("xml", {}).get(
                        "status"
                    ),
                    "srcdiff_seconds": srcdiff_attempt.get("elapsed_seconds"),
                    "srcdiff_stage_wall_seconds": timings.get(
                        "srcdiff_stage_wall_seconds"
                    ),
                    "srcdiff_execution_seconds": timings.get(
                        "srcdiff_execution_seconds"
                    ),
                    "srcdiff_cached_execution_seconds": timings.get(
                        "srcdiff_cached_execution_seconds"
                    ),
                    "srcdiff_peak_rss_bytes": srcdiff_attempt.get(
                        "resource_usage", {}
                    ).get("peak_rss_bytes"),
                    "srcmove_completed": counts.get("srcmove_completed"),
                    "srcmove_failed": counts.get("srcmove_failed"),
                    "srcmove_xml_status": srcmove_attempt.get("xml", {}).get(
                        "status"
                    ),
                    "srcmove_seconds": srcmove_attempt.get("elapsed_seconds"),
                    "srcmove_stage_wall_seconds": timings.get(
                        "srcmove_stage_wall_seconds"
                    ),
                    "srcmove_execution_seconds": timings.get(
                        "srcmove_execution_seconds"
                    ),
                    "srcmove_peak_rss_bytes": srcmove_attempt.get(
                        "resource_usage", {}
                    ).get("peak_rss_bytes"),
                    "pipeline_wall_seconds": timings.get("pipeline_wall_seconds"),
                    "move_count": results.get("move_count"),
                    "move_group_count": results.get("move_group_count"),
                    "move_pair_count": results.get("move_pair_count"),
                    "annotated_region_count": results.get("annotated_region_count"),
                    "regions_total": results.get("regions_total"),
                }
            )
    temporary.replace(summary_path)
    return manifest_path


def _format_duration(value: object) -> str:
    return "unavailable" if not isinstance(value, (int, float)) else f"{value:.1f}s"


def _format_memory(value: object) -> str:
    if not isinstance(value, int):
        return "unavailable"
    return f"{value / (1024 * 1024):.1f} MiB peak"


def print_benchmark_summary(
    entry: Mapping[str, Any], index_path: Path, data_root: Path
) -> None:
    completed = entry.get("status") == "completed"
    heading = "COMPLETED" if completed else "FAILED"
    source = entry.get("source", {})
    counts = entry.get("counts", {})
    results = entry.get("results", {})
    dispositions = entry.get("dispositions", {})
    timings = entry.get("timings", {})
    srcdiff = entry.get("srcdiff_attempt", {})
    srcmove = entry.get("srcmove_attempt", {})

    print()
    print(f"Repository benchmark: {heading}")
    print()
    print(f"  Case:        {entry['case']}")
    print(f"  Series:      {entry['series']}")
    print(
        "  Revisions:   "
        f"{source.get('requested_old_revision')} ({source.get('old_commit')})"
    )
    print(
        "               "
        f"{source.get('requested_new_revision')} ({source.get('new_commit')})"
    )
    print(
        "  Files:       "
        f"{counts.get('included_files', 0)} included, "
        f"{counts.get('excluded_files', 0)} excluded"
    )
    if srcdiff:
        if "reused" in dispositions.get("srcdiff_corpus", ""):
            print(
                "  srcDiff:     "
                f"reused in {_format_duration(timings.get('srcdiff_stage_wall_seconds'))}; "
                f"cached execution {_format_duration(srcdiff.get('elapsed_seconds'))}, "
                f"{_format_memory(srcdiff.get('resource_usage', {}).get('peak_rss_bytes'))}"
            )
        else:
            print(
                "  srcDiff:     "
                f"execution {_format_duration(timings.get('srcdiff_execution_seconds'))}, "
                f"stage {_format_duration(timings.get('srcdiff_stage_wall_seconds'))}, "
                f"{_format_memory(srcdiff.get('resource_usage', {}).get('peak_rss_bytes'))}"
            )
    if srcmove:
        print(
            "  srcMove:     "
            f"{_format_duration(srcmove.get('elapsed_seconds'))}, "
            f"{_format_memory(srcmove.get('resource_usage', {}).get('peak_rss_bytes'))} "
            f"({dispositions.get('srcmove_run', 'unknown')})"
        )
    if results:
        print()
        print(
            "  Moves:       "
            f"{results.get('move_count', 0)} moves, "
            f"{results.get('move_group_count', 0)} groups, "
            f"{results.get('move_pair_count', 0)} pairs"
        )
        print(
            "  Regions:     "
            f"{results.get('annotated_region_count', 0)} annotated / "
            f"{results.get('regions_total', 0)} total"
        )
    if entry.get("error"):
        print()
        print(f"  Failure:     {entry['error'].get('message', entry['error'])}")

    print()
    print("Artifacts:")
    if entry.get("results_path"):
        print(f"  Results:        {(data_root / entry['results_path']).resolve()}")
    if entry.get("run_manifest"):
        print(f"  Run manifest:   {(data_root / entry['run_manifest']).resolve()}")
    print(f"  Benchmark index: {index_path.resolve()}")
    print(f"  Series summary:  {(index_path.parent / 'summary.csv').resolve()}")
    if entry.get("status") == "srcdiff_failed":
        attempt_path = (data_root / entry["srcdiff_attempt"]["path"]).resolve()
        investigate = (REPO_ROOT / "benchmarks" / "investigate.py").resolve()
        print()
        print("Diagnostics:")
        print(f"  srcDiff attempt: {attempt_path}")
        print(f"  Replay: python3 {investigate} replay {attempt_path}")
        print(f"  Isolate: python3 {investigate} isolate {attempt_path}")


def run_staged_repository_benchmark(
    *,
    data_root: Path,
    series: str,
    case_name: str,
    original: Path,
    modified: Path,
    source: Mapping[str, Any],
    srcdiff: Path,
    srcmove: Path,
    srcdiff_timeout_seconds: float,
    srcmove_timeout_seconds: float,
    use_position: bool,
    use_archive: bool,
    source_encoding: str,
    excluded_suffixes: list[str],
    show_progress: bool = True,
) -> tuple[dict[str, Any], Path]:
    """Run and index one append-only repository benchmark without copying results."""

    pipeline_started = time.monotonic()
    data_root = data_root.expanduser().resolve()
    excluded_suffixes = sorted(
        set(DEFAULT_EXCLUDED_SUFFIXES).union(excluded_suffixes)
    )
    validate_storage_name(case_name, "case name")
    validate_series_name(series)
    benchmark_id = (
        f"repository-{utc_now().replace(':', '').replace('+', '-')}-"
        f"{case_name}-{uuid.uuid4()}"
    )
    entry: dict[str, Any] = {
        "schema_version": 2,
        "benchmark_id": benchmark_id,
        "created_at": utc_now(),
        "series": series,
        "case": case_name,
        "status": "running",
        "source": dict(source),
        "configuration": {
            "position": use_position,
            "archive": use_archive,
            "source_encoding": source_encoding,
            "excluded_suffixes": excluded_suffixes,
            "srcdiff_timeout_seconds": srcdiff_timeout_seconds,
            "srcmove_timeout_seconds": srcmove_timeout_seconds,
        },
        "timings": {},
    }
    try:
        snapshot_disposition = "created"

        def record_snapshot_disposition(value: str) -> None:
            nonlocal snapshot_disposition
            snapshot_disposition = value

        snapshot_started = time.monotonic()
        with ProgressDisplay(
            "4/6 Input snapshot",
            detail="hashing and verifying exported files",
            enabled=show_progress,
        ) as progress:
            input_snapshot_dir, input_snapshot = create_input_snapshot(
                data_root=data_root,
                adapter=RepositoryAdapter(
                    case_id=case_name,
                    original=original,
                    modified=modified,
                    metadata={"source": dict(source)},
                ),
                source=source,
                filter_configuration={"excluded_suffixes": excluded_suffixes},
                status_callback=record_snapshot_disposition,
            )
            snapshot_completion = (
                "verified and reused"
                if snapshot_disposition == "reused"
                else "created"
            )
            progress.finish(
                f"{input_snapshot['counts']['included_files']} included, "
                f"{input_snapshot['counts']['excluded_files']} excluded",
                completion=snapshot_completion,
            )
        entry["timings"]["input_snapshot_wall_seconds"] = (
            time.monotonic() - snapshot_started
        )
        entry.update(
            {
                "input_snapshot_id": input_snapshot["input_snapshot_id"],
                "input_snapshot_manifest": _relative_to_data_root(
                    input_snapshot_dir / "manifest.json", data_root
                ),
                "dispositions": {"input_snapshot": snapshot_completion},
                "counts": {
                    "included_files": input_snapshot["counts"]["included_files"],
                    "excluded_files": input_snapshot["counts"]["excluded_files"],
                },
            }
        )

        srcdiff_disposition = "executed"
        srcdiff_stage_started = time.monotonic()
        srcdiff_progress = ProgressDisplay(
            "5/6 srcDiff corpus",
            detail=f"preparing {case_name}",
            enabled=show_progress,
        )
        srcdiff_progress.start()

        def report_srcdiff_activity(activity: str, case_id: str) -> None:
            nonlocal srcdiff_disposition
            if activity == "running":
                srcdiff_disposition = "executed"
                srcdiff_progress.update(detail=f"executing {case_id}")
            elif activity == "reused":
                srcdiff_disposition = "verified and reused"
                srcdiff_progress.update(detail=f"verifying prior attempt for {case_id}")

        try:
            corpus_dir, corpus = generate_corpus(
                data_root=data_root,
                input_snapshot=input_snapshot["input_snapshot_id"],
                srcdiff=srcdiff,
                timeout_seconds=srcdiff_timeout_seconds,
                use_position=use_position,
                use_archive=use_archive,
                source_encoding=source_encoding,
                activity_callback=report_srcdiff_activity,
            )
        except BaseException as error:
            srcdiff_progress.finish(str(error), success=False, completion="failed")
            raise
        entry.update(
            {
                "corpus_id": corpus["corpus_id"],
                "corpus_manifest": _relative_to_data_root(
                    corpus_dir / "manifest.json", data_root
                ),
                "counts": {
                    **entry["counts"],
                    "srcdiff_accepted": corpus["counts"]["accepted"],
                    "srcdiff_failed": corpus["counts"]["failed"],
                },
            }
        )
        generation_case = corpus["cases"][0]
        srcdiff_attempt_path = (
            data_root / generation_case["attempt_path"] / "attempt.json"
        )
        entry["srcdiff_attempt"] = _attempt_summary(srcdiff_attempt_path, data_root)
        entry["dispositions"]["srcdiff_corpus"] = srcdiff_disposition
        srcdiff_seconds = entry["srcdiff_attempt"].get("elapsed_seconds")
        srcdiff_stage_seconds = time.monotonic() - srcdiff_stage_started
        entry["timings"]["srcdiff_stage_wall_seconds"] = srcdiff_stage_seconds
        if isinstance(srcdiff_seconds, (int, float)):
            timing_name = (
                "srcdiff_execution_seconds"
                if srcdiff_disposition == "executed"
                else "srcdiff_cached_execution_seconds"
            )
            entry["timings"][timing_name] = srcdiff_seconds
        srcdiff_progress.finish(
            f"{corpus['counts']['accepted']} accepted, "
            f"{corpus['counts']['failed']} failed"
            + (
                f", {'execution' if srcdiff_disposition == 'executed' else 'cached execution'} "
                f"{srcdiff_seconds:.1f}s"
                if srcdiff_seconds is not None
                else ""
            ),
            success=corpus["counts"]["failed"] == 0,
            completion=srcdiff_disposition,
        )

        if corpus["counts"]["accepted"] == 0:
            entry.update({"status": "srcdiff_failed", "completed_at": utc_now()})
            entry["timings"]["pipeline_wall_seconds"] = (
                time.monotonic() - pipeline_started
            )
            series_path = update_series(data_root, series, entry)
            return entry, series_path

        srcmove_stage_started = time.monotonic()
        srcmove_progress = ProgressDisplay(
            "6/6 srcMove run",
            detail=f"executing {case_name}",
            enabled=show_progress,
        )
        srcmove_progress.start()
        try:
            run_dir, run_manifest = run_corpus(
                data_root=data_root,
                corpus=corpus["corpus_id"],
                srcmove=srcmove,
                timeout_seconds=srcmove_timeout_seconds,
                mode=RunMode.DEVELOPMENT,
                activity_callback=lambda activity, case_id: srcmove_progress.update(
                    detail=f"{activity} {case_id}"
                ),
            )
        except BaseException as error:
            srcmove_progress.finish(str(error), success=False, completion="failed")
            raise
        entry.update(
            {
                "run_id": run_manifest["run_id"],
                "run_manifest": _relative_to_data_root(
                    run_dir / "run.json", data_root
                ),
                "status": (
                    "completed"
                    if run_manifest["counts"]["failed"] == 0
                    else "srcmove_failed"
                ),
                "completed_at": utc_now(),
                "results": _results_summary(run_dir, run_manifest),
                "dispositions": {**entry["dispositions"], "srcmove_run": "executed"},
            }
        )
        entry["counts"].update(
            {
                "srcmove_completed": run_manifest["counts"]["completed"],
                "srcmove_failed": run_manifest["counts"]["failed"],
            }
        )
        if run_manifest["cases"]:
            srcmove_attempt_path = (
                run_dir
                / "attempts"
                / run_manifest["cases"][0]["attempt_id"]
                / "attempt.json"
            )
            entry["srcmove_attempt"] = _attempt_summary(srcmove_attempt_path, data_root)
            completed_case = next(
                (case for case in run_manifest["cases"] if case["status"] == "completed"),
                None,
            )
            if completed_case is not None:
                entry["results_path"] = _relative_to_data_root(
                    run_dir / completed_case["results"]["path"], data_root
                )
            srcmove_seconds = entry["srcmove_attempt"].get("elapsed_seconds")
        srcmove_progress.finish(
            f"{run_manifest['counts']['completed']} completed, "
            f"{run_manifest['counts']['failed']} failed"
            + (f", {srcmove_seconds:.1f}s" if srcmove_seconds is not None else ""),
            success=run_manifest["counts"]["failed"] == 0,
            completion="executed",
        )
        entry["timings"]["srcmove_stage_wall_seconds"] = (
            time.monotonic() - srcmove_stage_started
        )
        if isinstance(srcmove_seconds, (int, float)):
            entry["timings"]["srcmove_execution_seconds"] = srcmove_seconds
        entry["timings"]["pipeline_wall_seconds"] = (
            time.monotonic() - pipeline_started
        )
        series_path = update_series(data_root, series, entry)
        return entry, series_path
    except Exception as error:
        entry["timings"]["pipeline_wall_seconds"] = (
            time.monotonic() - pipeline_started
        )
        entry.update(
            {
                "status": "orchestration_failed",
                "completed_at": utc_now(),
                "error": {"type": type(error).__name__, "message": str(error)},
            }
        )
        update_series(data_root, series, entry)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark srcMove across two revisions of a Git repository.",
    )
    parser.add_argument(
        "case",
        help="name of case directory under benchmarks/repositories",
    )
    parser.add_argument(
        "--old-rev",
        default=None,
        help="old git revision/tag/commit (overrides info.json)",
    )
    parser.add_argument(
        "--new-rev",
        default=None,
        help="new git revision/tag/commit (overrides info.json)",
    )
    parser.add_argument(
        "--fetch",
        action="store_true",
        help="fetch the cached repository before resolving revisions",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="forbid cloning or fetching; require all revisions in the cache",
    )
    parser.add_argument(
        "--series",
        default="adhoc",
        help="Name used to group saved benchmark references. Default: adhoc.",
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=DEFAULT_DATA_ROOT,
        help="Generated benchmark storage root. Default: benchmark-data.",
    )
    parser.add_argument("--srcdiff", type=Path, help="Explicit srcdiff executable.")
    parser.add_argument("--srcmove", type=Path, help="Explicit srcMove executable.")
    parser.add_argument("--srcdiff-timeout", type=float, default=1800.0)
    parser.add_argument("--srcmove-timeout", type=float, default=300.0)
    parser.add_argument(
        "--position",
        action="store_true",
        help="pass --position to srcdiff and save position-annotated srcdiff.xml",
    )
    parser.add_argument(
        "--no-srcdiff-archive",
        action="store_true",
        help="do not pass --archive to srcdiff",
    )
    parser.add_argument(
        "--src-encoding",
        default="UTF-8",
        help="source encoding passed to srcdiff --src-encoding (default: UTF-8)",
    )
    parser.add_argument(
        "--directory",
        default=None,
        help="limit export/srcdiff to a repository subdirectory (overrides info.json)",
    )
    args = parser.parse_args()

    if args.fetch and args.offline:
        parser.error("--fetch and --offline cannot be used together")

    script_path = Path(__file__).resolve()
    benchmark_root = script_path.parent
    repo_root = benchmark_root.parent.parent

    case_dir = benchmark_root / args.case
    if not case_dir.is_dir():
        print(f"error: case directory not found: {case_dir}", file=sys.stderr)
        return 1

    info_json = case_dir / "info.json"
    if not info_json.is_file():
        print(f"error: missing info.json: {info_json}", file=sys.stderr)
        return 1

    srcdiff_bin = find_srcdiff(repo_root, args.srcdiff)
    if srcdiff_bin is None:
        print("error: srcdiff not found on PATH", file=sys.stderr)
        return 1

    srcmove_bin = find_srcmove(repo_root, args.srcmove)
    if srcmove_bin is None:
        print("error: srcMove binary not found", file=sys.stderr)
        return 1

    config = load_case_config(info_json)
    selected_dir = (
        normalize_repo_subdir(args.directory, "--directory")
        if args.directory is not None
        else config["directory"]
    )

    repo_url = config["github"]
    old_rev = args.old_rev if args.old_rev is not None else config["old_rev"]
    new_rev = args.new_rev if args.new_rev is not None else config["new_rev"]

    if old_rev is None or new_rev is None:
        print(
            f"error: case '{args.case}' has no configured revisions; "
            "pass both --old-rev and --new-rev",
            file=sys.stderr,
        )
        return 2
    if args.srcdiff_timeout <= 0 or args.srcmove_timeout <= 0:
        print("error: benchmark timeouts must be positive", file=sys.stderr)
        return 1
    try:
        validate_series_name(args.series)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    work_root = case_dir / "work"
    clone_dir = work_root / "repo"
    original_dir = work_root / "original"
    modified_dir = work_root / "modified"
    work_root.mkdir(parents=True, exist_ok=True)

    cache_existed = clone_dir.exists()
    with ProgressDisplay("1/6 Repository cache", detail=repo_url) as progress:
        repository_updated = ensure_repo(
            repo_url,
            clone_dir,
            offline=args.offline,
            update=args.fetch,
        )
        cache_completion = (
            "created" if not cache_existed else "fetched" if args.fetch else "reused"
        )
        progress.finish(str(clone_dir.resolve()), completion=cache_completion)

    with ProgressDisplay("2/6 Revisions", detail=f"resolving {old_rev} → {new_rev}") as progress:
        old_commit, new_commit = resolve_requested_commits(
            clone_dir,
            old_rev,
            new_rev,
            offline=args.offline,
            repository_updated=repository_updated,
        )
        progress.finish("requested revisions resolved to commits", completion="verified")

    export_detail = selected_dir or "complete repository trees"
    with ProgressDisplay("3/6 Exports", detail=export_detail) as progress:
        export_commit(clone_dir, old_commit, original_dir, selected_dir)
        progress.update(detail="old revision exported; exporting new revision")
        export_commit(clone_dir, new_commit, modified_dir, selected_dir)
        progress.finish("old and new source trees", completion="created")

    source = {
        "repository": repo_url,
        "requested_old_revision": old_rev,
        "requested_new_revision": new_rev,
        "old_commit": old_commit,
        "new_commit": new_commit,
        "directory": selected_dir,
    }
    data_root = args.data_root.expanduser().resolve()
    entry, index_path = run_staged_repository_benchmark(
        data_root=data_root,
        series=args.series,
        case_name=args.case,
        original=original_dir,
        modified=modified_dir,
        source=source,
        srcdiff=srcdiff_bin,
        srcmove=srcmove_bin,
        srcdiff_timeout_seconds=args.srcdiff_timeout,
        srcmove_timeout_seconds=args.srcmove_timeout,
        use_position=args.position,
        use_archive=not args.no_srcdiff_archive,
        source_encoding=args.src_encoding,
        excluded_suffixes=[],
    )

    print_benchmark_summary(entry, index_path, data_root)
    return 0 if entry["status"] == "completed" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        raise SystemExit(1)
