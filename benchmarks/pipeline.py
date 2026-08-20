#!/usr/bin/env python3
"""Create an input snapshot, generate a srcDiff corpus, or replay srcMove."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = REPO_ROOT / "tests"
for import_root in (REPO_ROOT, TESTS_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from benchmarks.contracts import RunMode
from benchmarks.corpus import create_input_snapshot, generate_corpus, run_corpus
from benchmarks.repositories.adapter import RepositoryAdapter
from support.tooling import find_srcdiff, find_srcmove


DEFAULT_DATA_ROOT = REPO_ROOT / "benchmark-data"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    subparsers = parser.add_subparsers(dest="stage", required=True)

    snapshot = subparsers.add_parser(
        "snapshot",
        help="Freeze and checksum an old/new source pair for later srcDiff runs.",
    )
    snapshot.add_argument("--case-id", required=True)
    snapshot.add_argument("--original", type=Path, required=True)
    snapshot.add_argument("--modified", type=Path, required=True)
    snapshot.add_argument("--source-json", default="{}")
    snapshot.add_argument("--metadata-json", default="{}")
    snapshot.add_argument(
        "--exclude-suffix",
        action="append",
        default=[],
        help=(
            "Exclude an additional suffix without modifying the source export; "
            ".py is always excluded (repeatable)."
        ),
    )

    generate = subparsers.add_parser("generate")
    generate.add_argument(
        "input_snapshot", help="Input snapshot ID, directory, or manifest path."
    )
    generate.add_argument("--srcdiff", type=Path)
    generate.add_argument("--timeout", type=float, default=1800.0)
    generate.add_argument("--position", action="store_true")
    generate.add_argument("--single-file", action="store_true")
    generate.add_argument("--source-encoding", default="UTF-8")
    generate.add_argument("--retry-failed", action="store_true")
    generate.add_argument(
        "--case",
        action="append",
        default=[],
        help="With --retry-failed, retry only this failed case (repeatable).",
    )

    run = subparsers.add_parser("run")
    run.add_argument("corpus")
    run.add_argument("--srcmove", type=Path)
    run.add_argument("--timeout", type=float, default=300.0)
    run.add_argument("--resume-run")
    run.add_argument("--retry-failed", action="store_true")
    run.add_argument(
        "--case",
        action="append",
        default=[],
        help="With --retry-failed, retry only this failed case (repeatable).",
    )
    run.add_argument(
        "--mode", choices=[mode.value for mode in RunMode], default="development"
    )
    return parser.parse_args()


def json_object(value: str, option: str) -> dict:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as error:
        raise ValueError(f"{option} is invalid JSON: {error}") from error
    if not isinstance(parsed, dict):
        raise ValueError(f"{option} must decode to an object")
    return parsed


def main() -> int:
    args = parse_args()
    data_root = args.data_root.expanduser().resolve()
    exit_code = 0
    try:
        if args.stage == "snapshot":
            adapter = RepositoryAdapter(
                case_id=args.case_id,
                original=args.original,
                modified=args.modified,
                metadata=json_object(args.metadata_json, "--metadata-json"),
            )
            directory, manifest = create_input_snapshot(
                data_root=data_root,
                adapter=adapter,
                source=json_object(args.source_json, "--source-json"),
                filter_configuration={"excluded_suffixes": args.exclude_suffix},
            )
            print(f"input_snapshot_id={manifest['input_snapshot_id']}")
        elif args.stage == "generate":
            srcdiff = find_srcdiff(REPO_ROOT, args.srcdiff)
            if srcdiff is None:
                raise ValueError("srcdiff not found; pass --srcdiff")
            directory, manifest = generate_corpus(
                data_root=data_root,
                input_snapshot=args.input_snapshot,
                srcdiff=srcdiff,
                timeout_seconds=args.timeout,
                use_position=args.position,
                use_archive=not args.single_file,
                source_encoding=args.source_encoding,
                retry_failed=args.retry_failed,
                selected_case_ids=args.case,
            )
            print(f"corpus_id={manifest['corpus_id']}")
            failed = sum(
                case["generation_status"] != "accepted"
                for case in manifest["cases"]
            )
            if failed:
                print(f"failed_cases={failed}", file=sys.stderr)
                exit_code = 1
        else:
            srcmove = find_srcmove(REPO_ROOT, args.srcmove)
            if srcmove is None:
                raise ValueError("srcMove not found; pass --srcmove")
            directory, manifest = run_corpus(
                data_root=data_root,
                corpus=args.corpus,
                srcmove=srcmove,
                timeout_seconds=args.timeout,
                mode=RunMode(args.mode),
                resume_run=args.resume_run,
                retry_failed=args.retry_failed,
                selected_case_ids=args.case,
            )
            print(f"run_id={manifest['run_id']}")
            failed = sum(case["status"] != "completed" for case in manifest["cases"])
            if failed:
                print(f"failed_cases={failed}", file=sys.stderr)
                exit_code = 1
        print(f"directory={directory}")
        return exit_code
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
