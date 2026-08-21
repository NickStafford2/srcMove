#!/usr/bin/env python3
"""Materialize a Phase 2 BigCloneBench selection as an immutable snapshot."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.bigclonebench.adapter import CompiledBigCloneBenchAdapter
from benchmarks.bigclonebench.compile import DEFAULT_DATA_ROOT
from benchmarks.corpus import create_input_snapshot
from benchmarks.progress import ProgressDisplay


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("selection", help="Selection ID or directory.")
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    disposition = "created"

    def record_disposition(value: str) -> None:
        nonlocal disposition
        disposition = value

    try:
        with ProgressDisplay(
            "snapshot/validate", detail="checking selection and compiled catalog"
        ) as progress:
            adapter = CompiledBigCloneBenchAdapter(
                data_root=args.data_root,
                selection=args.selection,
            )
            progress.finish("selection and catalog validated")
        with ProgressDisplay(
            "snapshot/materialize",
            total=adapter.selection_manifest["counts"]["selected_frames"],
            detail=adapter.selection_manifest["request"]["pair_set"],
        ) as progress:
            snapshot = create_input_snapshot(
                data_root=args.data_root.expanduser().resolve(),
                adapter=adapter,
                source=adapter.source_manifest(),
                status_callback=record_disposition,
            )
            progress.finish(
                f"{snapshot.manifest['counts']['selected']:,} cases",
                completion=disposition,
            )
        print(f"BigCloneBench input snapshot: {disposition}")
        print(f"input_snapshot_id={snapshot.snapshot_id}")
        print(f"directory={snapshot.directory}")
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
