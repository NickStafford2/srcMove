#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent


def run_git(repo_dir: Path, args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(repo_dir),
        text=True,
        capture_output=True,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )

    return result.stdout


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a readable ordered commit manifest for a stress-test repo."
    )
    parser.add_argument(
        "case",
        help="Case name under test/stress, e.g. wowy_advanced_analytics.",
    )
    parser.add_argument(
        "--branch",
        default="HEAD",
        help="Branch/revision to order. Default: HEAD.",
    )
    parser.add_argument(
        "--all-parents",
        action="store_true",
        help="Include commits from merged branches. Default is first-parent only.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing commits.json.",
    )
    return parser.parse_args()


def get_commit_subject(repo_dir: Path, commit: str) -> str:
    return run_git(repo_dir, ["show", "-s", "--format=%s", commit]).strip()


def get_commit_date(repo_dir: Path, commit: str) -> str:
    return run_git(repo_dir, ["show", "-s", "--format=%cI", commit]).strip()


def build_manifest(
    *,
    case: str,
    repo_dir: Path,
    branch: str,
    first_parent: bool,
) -> dict[str, Any]:
    rev_list_cmd = ["rev-list", "--reverse"]

    if first_parent:
        rev_list_cmd.append("--first-parent")

    rev_list_cmd.append(branch)

    commits = [
        line.strip()
        for line in run_git(repo_dir, rev_list_cmd).splitlines()
        if line.strip()
    ]

    entries: list[dict[str, Any]] = []

    width = max(6, len(str(len(commits))))

    for index, commit in enumerate(commits, start=1):
        seq = f"v{index:0{width}d}"

        entries.append(
            {
                "seq": seq,
                "index": index,
                "commit": commit,
                "short": commit[:12],
                "subject": get_commit_subject(repo_dir, commit),
                "date": get_commit_date(repo_dir, commit),
            }
        )

    strategy = f"git {' '.join(rev_list_cmd)}"

    return {
        "schema_version": 1,
        "case": case,
        "repo_dir": str(repo_dir),
        "branch": branch,
        "ordering_strategy": strategy,
        "commit_count": len(entries),
        "commits": entries,
    }


def main() -> int:
    args = parse_args()

    case_dir = SCRIPT_DIR / args.case
    repo_dir = case_dir / "work" / "repo"
    manifest_path = case_dir / "commits.json"

    if not repo_dir.is_dir():
        print(f"error: repo not found: {repo_dir}", file=sys.stderr)
        print(
            "Run diff_and_move_repo.py or build_examples.py once first so the repo is cloned.",
            file=sys.stderr,
        )
        return 1

    if manifest_path.exists() and not args.force:
        print(f"error: manifest already exists: {manifest_path}", file=sys.stderr)
        print("Use --force to overwrite it.", file=sys.stderr)
        return 1

    manifest = build_manifest(
        case=args.case,
        repo_dir=repo_dir,
        branch=args.branch,
        first_parent=not args.all_parents,
    )

    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"wrote: {manifest_path}")
    print(f"commits: {manifest['commit_count']}")
    print(f"ordering: {manifest['ordering_strategy']}")

    print()
    print("first commits:")
    for entry in manifest["commits"][:10]:
        print(f"  {entry['seq']}  {entry['short']}  {entry['subject']}")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        raise SystemExit(1)
