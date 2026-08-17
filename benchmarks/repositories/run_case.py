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
from benchmarks.corpus import create_preparation, generate_corpus, run_corpus
from benchmarks.process import write_json_atomic
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


def is_tag_clobber_error(result: subprocess.CompletedProcess) -> bool:
    stderr = result.stderr or ""
    return "would clobber existing tag" in stderr


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


def update_repo(repo_dir: Path, repo_url: str) -> None:
    current_origin = get_origin_url(repo_dir)
    if current_origin != repo_url:
        result = run(["git", "remote", "set-url", "origin", repo_url], cwd=repo_dir)
        require_ok(result, "git remote set-url origin")

    result = run(["git", "fetch", "origin", "--tags", "--prune"], cwd=repo_dir)
    if result.returncode == 0:
        return

    if is_tag_clobber_error(result):
        print("      tag conflict detected; recreating cached repo")
        shutil.rmtree(repo_dir)
        clone_repo(repo_url, repo_dir)
        return

    require_ok(result, "git fetch origin --tags --prune")


def ensure_repo(repo_url: str, clone_dir: Path, *, allow_network: bool) -> None:
    if not clone_dir.exists():
        if not allow_network:
            raise RuntimeError(
                "cached repository is missing; rerun with --refresh-repo to allow a clone"
            )
        print("      repo not present; cloning (network explicitly enabled)")
        clone_repo(repo_url, clone_dir)
        return

    if not is_git_repo(clone_dir):
        raise RuntimeError(f"existing path is not a git repo: {clone_dir}")

    current_origin = get_origin_url(clone_dir)
    if not allow_network and current_origin != repo_url:
        raise RuntimeError(
            f"cached repository origin mismatch: expected {repo_url}, found {current_origin}"
        )

    if allow_network:
        print("      refreshing cached repo (network explicitly enabled)")
        update_repo(clone_dir, repo_url)
    else:
        print("      using cached repo offline")


def resolve_commit(repo_dir: Path, rev: str) -> str:
    result = run(["git", "rev-parse", rev], cwd=repo_dir)
    require_ok(result, f"git rev-parse {rev}")
    return result.stdout.strip()


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
    "old_commit",
    "new_commit",
    "status",
    "preparation_id",
    "corpus_id",
    "run_id",
    "srcdiff_accepted",
    "srcdiff_failed",
    "srcdiff_xml_status",
    "srcdiff_seconds",
    "srcdiff_peak_rss_bytes",
    "srcmove_completed",
    "srcmove_failed",
    "srcmove_xml_status",
    "srcmove_seconds",
    "srcmove_peak_rss_bytes",
    "move_count",
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
            writer.writerow(
                {
                    "benchmark_id": benchmark.get("benchmark_id"),
                    "created_at": benchmark.get("created_at"),
                    "case": benchmark.get("case"),
                    "old_commit": benchmark.get("source", {}).get("old_commit"),
                    "new_commit": benchmark.get("source", {}).get("new_commit"),
                    "status": benchmark.get("status"),
                    "preparation_id": benchmark.get("preparation_id"),
                    "corpus_id": benchmark.get("corpus_id"),
                    "run_id": benchmark.get("run_id"),
                    "srcdiff_accepted": counts.get("srcdiff_accepted"),
                    "srcdiff_failed": counts.get("srcdiff_failed"),
                    "srcdiff_xml_status": srcdiff_attempt.get("xml", {}).get(
                        "status"
                    ),
                    "srcdiff_seconds": srcdiff_attempt.get("elapsed_seconds"),
                    "srcdiff_peak_rss_bytes": srcdiff_attempt.get(
                        "resource_usage", {}
                    ).get("peak_rss_bytes"),
                    "srcmove_completed": counts.get("srcmove_completed"),
                    "srcmove_failed": counts.get("srcmove_failed"),
                    "srcmove_xml_status": srcmove_attempt.get("xml", {}).get(
                        "status"
                    ),
                    "srcmove_seconds": srcmove_attempt.get("elapsed_seconds"),
                    "srcmove_peak_rss_bytes": srcmove_attempt.get(
                        "resource_usage", {}
                    ).get("peak_rss_bytes"),
                    "move_count": results.get("move_count"),
                }
            )
    temporary.replace(summary_path)
    return manifest_path


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
) -> tuple[dict[str, Any], Path]:
    """Run and index one append-only repository benchmark without copying results."""

    data_root = data_root.expanduser().resolve()
    validate_storage_name(case_name, "case name")
    validate_series_name(series)
    benchmark_id = (
        f"repository-{utc_now().replace(':', '').replace('+', '-')}-"
        f"{case_name}-{uuid.uuid4()}"
    )
    entry: dict[str, Any] = {
        "schema_version": 1,
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
    }
    try:
        preparation_dir, preparation = create_preparation(
            data_root=data_root,
            adapter=RepositoryAdapter(
                case_id=case_name,
                original=original,
                modified=modified,
                metadata={"source": dict(source)},
            ),
            source=source,
            filter_configuration={"excluded_suffixes": excluded_suffixes},
        )
        entry.update(
            {
                "preparation_id": preparation["preparation_id"],
                "preparation_manifest": _relative_to_data_root(
                    preparation_dir / "manifest.json", data_root
                ),
            }
        )

        corpus_dir, corpus = generate_corpus(
            data_root=data_root,
            preparation=preparation["preparation_id"],
            srcdiff=srcdiff,
            timeout_seconds=srcdiff_timeout_seconds,
            use_position=use_position,
            use_archive=use_archive,
            source_encoding=source_encoding,
        )
        entry.update(
            {
                "corpus_id": corpus["corpus_id"],
                "corpus_manifest": _relative_to_data_root(
                    corpus_dir / "manifest.json", data_root
                ),
                "counts": {
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

        if corpus["counts"]["accepted"] == 0:
            entry.update({"status": "srcdiff_failed", "completed_at": utc_now()})
            series_path = update_series(data_root, series, entry)
            return entry, series_path

        run_dir, run_manifest = run_corpus(
            data_root=data_root,
            corpus=corpus["corpus_id"],
            srcmove=srcmove,
            timeout_seconds=srcmove_timeout_seconds,
            mode=RunMode.DEVELOPMENT,
        )
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
        series_path = update_series(data_root, series, entry)
        return entry, series_path
    except Exception as error:
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
        "--refresh-repo",
        action="store_true",
        help="explicitly allow clone/fetch; otherwise use the cached repo offline",
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
        "--exclude-python",
        action="store_true",
        help="exclude Python files non-destructively in the preparation manifest",
    )
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
        print(f"skipping case '{args.case}': old_rev/new_rev not specified")
        return 0
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

    print(f"[1/5] preparing repo {repo_url}")
    ensure_repo(repo_url, clone_dir, allow_network=args.refresh_repo)

    print("[2/5] repository cache ready")

    print("[3/5] resolving revisions")
    old_commit = resolve_commit(clone_dir, old_rev)
    new_commit = resolve_commit(clone_dir, new_rev)

    print(f"      old rev   : {old_rev}")
    print(f"      new rev   : {new_rev}")
    print(f"      old commit: {old_commit}")
    print(f"      new commit: {new_commit}")

    print("[4/5] exporting revisions")
    if selected_dir:
        print(f"      directory : {selected_dir}")
    export_commit(clone_dir, old_commit, original_dir, selected_dir)
    export_commit(clone_dir, new_commit, modified_dir, selected_dir)

    print("[5/5] running validated, append-only benchmark")
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
        excluded_suffixes=[".py"] if args.exclude_python else [],
    )

    print()
    print(f"status={entry['status']}")
    print(f"benchmark_id={entry['benchmark_id']}")
    print(f"series={entry['series']}")
    print(f"saved={index_path}")
    print(f"series_summary={index_path.parent / 'summary.csv'}")
    if entry.get("run_manifest"):
        print(f"run={data_root / entry['run_manifest']}")
    if entry["status"] == "srcdiff_failed":
        attempt = entry["srcdiff_attempt"]
        attempt_path = data_root / attempt["path"]
        print(f"srcdiff_attempt={attempt_path}")
        print(
            "replay="
            f"python3 benchmarks/investigate.py replay {attempt_path}"
        )
        print(
            "isolate="
            f"python3 benchmarks/investigate.py isolate {attempt_path}"
        )
    return 0 if entry["status"] == "completed" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        raise SystemExit(1)
