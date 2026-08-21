#!/usr/bin/env python3
"""Materialize a Phase 2 BigCloneBench selection as an immutable snapshot."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.bigclonebench.adapter import CompiledBigCloneBenchAdapter
from benchmarks.bigclonebench.compile import DEFAULT_DATA_ROOT
from benchmarks.corpus import (
    VerifiedSnapshot,
    create_input_snapshot,
    load_input_snapshot,
)
from benchmarks.contracts import content_identifier
from benchmarks.process import write_json_atomic
from benchmarks.progress import ProgressDisplay


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("selection", help="Selection ID or directory.")
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    return parser.parse_args()


def materialize_compiled_selection(
    *, data_root: Path, selection: str | Path
) -> tuple[VerifiedSnapshot, str]:
    """Load an existing selection snapshot without rematerializing its sources."""

    data_root = data_root.expanduser().resolve()
    adapter = CompiledBigCloneBenchAdapter(
        data_root=data_root,
        selection=selection,
    )
    source = adapter.source_manifest()
    snapshots_root = data_root / "input-snapshots"
    index_path = data_root / "bigclonebench" / "snapshot-index.json"
    request_id = content_identifier(
        "bcb-snapshot-request",
        {
            "adapter": {"name": adapter.name, "version": adapter.version},
            "source": source,
            "filter_configuration": {"excluded_suffixes": [".py"]},
        },
    )
    index: dict[str, Any] = {"schema_version": 1, "entries": {}}
    if index_path.is_file():
        value = json.loads(index_path.read_text(encoding="utf-8"))
        if (
            not isinstance(value, dict)
            or value.get("schema_version") != 1
            or not isinstance(value.get("entries"), dict)
        ):
            raise ValueError(f"invalid BigCloneBench snapshot index: {index_path}")
        index = value

    def matches(candidate: VerifiedSnapshot) -> bool:
        return (
            candidate.manifest.get("adapter")
            == {"name": adapter.name, "version": adapter.version}
            and candidate.manifest.get("source") == source
            and candidate.manifest.get("filter_configuration")
            == {"excluded_suffixes": [".py"]}
        )

    indexed_id = index["entries"].get(request_id)
    if isinstance(indexed_id, str):
        try:
            indexed = load_input_snapshot(data_root, indexed_id)
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        else:
            if matches(indexed):
                return indexed, "reused"

    if snapshots_root.is_dir():
        for manifest_path in sorted(snapshots_root.glob("*/manifest.json")):
            try:
                candidate = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(candidate, dict):
                continue
            if (
                candidate.get("adapter")
                != {"name": adapter.name, "version": adapter.version}
                or candidate.get("source") != source
                or candidate.get("filter_configuration")
                != {"excluded_suffixes": [".py"]}
            ):
                continue
            verified = load_input_snapshot(data_root, manifest_path.parent)
            index["entries"][request_id] = verified.snapshot_id
            write_json_atomic(index_path, index)
            return verified, "reused"

    disposition = "created"

    def record_disposition(value: str) -> None:
        nonlocal disposition
        disposition = value

    snapshot = create_input_snapshot(
        data_root=data_root,
        adapter=adapter,
        source=source,
        status_callback=record_disposition,
    )
    index["entries"][request_id] = snapshot.snapshot_id
    write_json_atomic(index_path, index)
    return snapshot, disposition


def main() -> int:
    args = parse_args()
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
            snapshot, disposition = materialize_compiled_selection(
                data_root=args.data_root,
                selection=args.selection,
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
