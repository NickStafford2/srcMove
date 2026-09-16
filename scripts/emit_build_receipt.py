#!/usr/bin/env python3
"""Emit an atomic build-time receipt for a newly linked executable."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.provenance import (
    RECEIPT_SCHEMA_VERSION,
    build_receipt_identifier,
    observe_environment,
    observe_file,
    observe_repository,
    sha256_file,
    utc_now,
)


def parse_named_path(value: str) -> tuple[str, Path]:
    name, separator, raw_path = value.partition("=")
    if not separator or not name or not raw_path:
        raise argparse.ArgumentTypeError("expected NAME=PATH")
    return name, Path(raw_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, action="append", required=True)
    parser.add_argument("--repository", type=parse_named_path, action="append", default=[])
    parser.add_argument("--source-lock", type=Path)
    parser.add_argument("--build-entry-point", required=True)
    parser.add_argument("--configuration", required=True)
    parser.add_argument("--cmake-options", default="{}")
    parser.add_argument("--compiler-id", required=True)
    parser.add_argument("--compiler-version", required=True)
    parser.add_argument(
        "--test-status",
        choices=("passed", "failed", "not_run"),
        default="not_run",
    )
    return parser.parse_args()


def build_receipt(args: argparse.Namespace) -> dict:
    try:
        cmake_options = json.loads(args.cmake_options)
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid --cmake-options JSON: {error}") from error
    if not isinstance(cmake_options, dict):
        raise ValueError("--cmake-options must decode to an object")

    artifacts = []
    for path in args.artifact:
        observation = observe_file(path)
        if observation["status"] != "observed":
            raise ValueError(f"artifact is unavailable: {path}")
        artifacts.append(
            {
                "name": Path(observation["path"]).name,
                "sha256": observation["sha256"],
                "size_bytes": observation["size_bytes"],
            }
        )

    repositories = {
        name: observe_repository(path) for name, path in args.repository
    }
    source_lock = None
    if args.source_lock is not None and args.source_lock.is_file():
        source_lock = {
            "name": args.source_lock.name,
            "sha256": sha256_file(args.source_lock),
        }

    build = {
        "entry_point": args.build_entry_point,
        "configuration": args.configuration,
        "cmake_options": cmake_options,
        "compiler": {
            "id": args.compiler_id,
            "version": args.compiler_version,
        },
    }
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "receipt_id": build_receipt_identifier(
            sources=repositories,
            source_lock=source_lock,
            build=build,
            artifacts=artifacts,
        ),
        "completed_at": utc_now(),
        "sources": repositories,
        "source_lock": source_lock,
        "build": build,
        "environment": observe_environment(),
        "artifacts": artifacts,
        "tests": {"status": args.test_status},
    }


def write_atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary_path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary_path, path)


def main() -> int:
    args = parse_args()
    try:
        receipt = build_receipt(args)
        write_atomic(args.output, receipt)
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
