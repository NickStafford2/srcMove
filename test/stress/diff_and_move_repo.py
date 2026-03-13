#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path


def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
    )


def require_ok(result: subprocess.CompletedProcess, what: str) -> None:
    if result.returncode != 0:
        raise RuntimeError(
            f"{what} failed\n"
            f"command stdout:\n{result.stdout}\n"
            f"command stderr:\n{result.stderr}"
        )


def normalize_repo_subdir(value: object, info_json: Path) -> str | None:
    if value is None:
        return None

    if not isinstance(value, str):
        raise RuntimeError(f"invalid 'directory' in {info_json}: must be a string")

    subdir = value.strip()
    if not subdir:
        return None

    subdir = subdir.replace("\\", "/").strip("/")

    if subdir in (".", "./"):
        return None

    if subdir.startswith("../") or "/../" in subdir or subdir == "..":
        raise RuntimeError(
            f"invalid 'directory' in {info_json}: must stay within the repository"
        )

    return subdir


def load_case_config(info_json: Path) -> dict:
    with info_json.open("r", encoding="utf-8") as f:
        data = json.load(f)

    repo_url = data.get("github")
    if not isinstance(repo_url, str) or not repo_url:
        raise RuntimeError(f"missing or invalid 'github' field in {info_json}")

    old_rev = data.get("old_rev")
    new_rev = data.get("new_rev")
    directory = normalize_repo_subdir(data.get("directory"), info_json)

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
    require_ok(result, "git fetch origin --tags --prune")


def ensure_repo(repo_url: str, clone_dir: Path) -> None:
    if not clone_dir.exists():
        print("      repo not present; cloning")
        clone_repo(repo_url, clone_dir)
        return

    if not is_git_repo(clone_dir):
        raise RuntimeError(f"existing path is not a git repo: {clone_dir}")

    print("      repo already present; updating")
    update_repo(clone_dir, repo_url)


def fetch_tags(repo_dir: Path) -> None:
    result = run(["git", "fetch", "origin", "--tags", "--prune"], cwd=repo_dir)
    require_ok(result, "git fetch origin --tags --prune")


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


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="run_stress.py",
        description=(
            "Stress-test srcMove by comparing two explicit revisions of a Git repository."
        ),
    )
    parser.add_argument(
        "case",
        help="name of case directory under test/stress",
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
        "--keep-work",
        action="store_true",
        help="keep generated working files instead of deleting old ones first",
    )
    parser.add_argument(
        "--refresh-repo",
        action="store_true",
        help="force a git fetch even if the repo already exists locally",
    )
    args = parser.parse_args()

    script_path = Path(__file__).resolve()
    stress_root = script_path.parent
    repo_root = stress_root.parent.parent

    case_dir = stress_root / args.case
    if not case_dir.is_dir():
        print(f"error: case directory not found: {case_dir}", file=sys.stderr)
        return 1

    info_json = case_dir / "info.json"
    if not info_json.is_file():
        print(f"error: missing info.json: {info_json}", file=sys.stderr)
        return 1

    srcdiff_bin = shutil.which("srcdiff")
    if srcdiff_bin is None:
        print("error: srcdiff not found on PATH", file=sys.stderr)
        return 1

    srcmove_bin = repo_root / "build" / "srcMove"
    if not srcmove_bin.is_file():
        print(f"error: srcMove binary not found: {srcmove_bin}", file=sys.stderr)
        return 1

    config = load_case_config(info_json)
    selected_dir = config["directory"]

    repo_url = config["github"]
    old_rev = args.old_rev if args.old_rev is not None else config["old_rev"]
    new_rev = args.new_rev if args.new_rev is not None else config["new_rev"]
    selected_dir = config["directory"]

    if old_rev is None or new_rev is None:
        print(f"skipping case '{args.case}': old_rev/new_rev not specified")
        return 0

    work_root = case_dir / "work"
    clone_dir = work_root / "repo"
    original_dir = work_root / "original"
    modified_dir = work_root / "modified"
    diff_xml = work_root / "diff.xml"
    diff_new_xml = work_root / "diff_new.xml"
    results_json = work_root / "results.json"
    report_json = work_root / "report.json"

    if not args.keep_work and work_root.exists():
        if clone_dir.exists() and is_git_repo(clone_dir):
            temp_repo_dir = case_dir / ".repo_tmp_preserve"
            if temp_repo_dir.exists():
                shutil.rmtree(temp_repo_dir)
            shutil.move(str(clone_dir), str(temp_repo_dir))

            shutil.rmtree(work_root)
            work_root.mkdir(parents=True, exist_ok=True)

            shutil.move(str(temp_repo_dir), str(clone_dir))
        else:
            shutil.rmtree(work_root)

    work_root.mkdir(parents=True, exist_ok=True)

    print(f"[1/6] preparing repo {repo_url}")
    ensure_repo(repo_url, clone_dir)

    if args.refresh_repo:
        print("      refreshing existing repo")
        update_repo(clone_dir, repo_url)

    print("[2/6] fetching tags")
    fetch_tags(clone_dir)

    print("[3/6] resolving revisions")
    old_commit = resolve_commit(clone_dir, old_rev)
    new_commit = resolve_commit(clone_dir, new_rev)

    print(f"      old rev   : {old_rev}")
    print(f"      new rev   : {new_rev}")
    print(f"      old commit: {old_commit}")
    print(f"      new commit: {new_commit}")

    print("[4/6] exporting revisions")
    if selected_dir:
        print(f"      directory : {selected_dir}")
    export_commit(clone_dir, old_commit, original_dir, selected_dir)
    export_commit(clone_dir, new_commit, modified_dir, selected_dir)

    print("[5/6] running srcdiff")
    diff_start = time.perf_counter()
    diff_result = run(
        [
            srcdiff_bin,
            str(original_dir),
            str(modified_dir),
            "-o",
            str(diff_xml),
        ],
        cwd=repo_root,
    )
    diff_end = time.perf_counter()
    require_ok(diff_result, "srcdiff")

    if not diff_xml.is_file():
        raise RuntimeError(f"srcdiff did not create diff.xml: {diff_xml}")

    print("[6/6] running srcMove")
    move_start = time.perf_counter()
    move_result = run(
        [
            str(srcmove_bin),
            str(diff_xml),
            str(diff_new_xml),
            "--results",
            str(results_json),
        ],
        cwd=repo_root,
    )
    move_end = time.perf_counter()
    require_ok(move_result, "srcMove")

    move_count = None
    results_data = None
    if results_json.is_file():
        with results_json.open("r", encoding="utf-8") as f:
            results_data = json.load(f)
        move_count = results_data.get("move_count")

    report = {
        "case": args.case,
        "repo_url": repo_url,
        "old_rev": old_rev,
        "new_rev": new_rev,
        "directory": selected_dir,
        "old_commit": old_commit,
        "new_commit": new_commit,
        "srcdiff_seconds": diff_end - diff_start,
        "srcmove_seconds": move_end - move_start,
        "move_count": move_count,
        "paths": {
            "repo_dir": str(clone_dir),
            "original_dir": str(original_dir),
            "modified_dir": str(modified_dir),
            "diff_xml": str(diff_xml),
            "diff_new_xml": str(diff_new_xml),
            "results_json": str(results_json),
        },
    }

    if results_data is not None:
        report["results"] = results_data

    with report_json.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print()
    print("done")
    print(f"repo         : {clone_dir}")
    print(f"old_rev      : {old_rev}")
    print(f"new_rev      : {new_rev}")
    print(f"srcdiff time : {report['srcdiff_seconds']:.3f}s")
    print(f"srcMove time : {report['srcmove_seconds']:.3f}s")
    print(f"move_count   : {move_count}")
    print(f"report       : {report_json}")
    if selected_dir:
        print(f"directory    : {selected_dir}")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        raise SystemExit(1)
