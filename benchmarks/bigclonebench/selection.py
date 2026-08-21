#!/usr/bin/env python3
"""Select deterministic sample or census frames from a compiled BCB catalog."""

from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import os
import shutil
import sqlite3
import sys
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.bigclonebench.compile import DEFAULT_DATA_ROOT
from benchmarks.bigclonebench.compiled import (
    VerifiedCompiledDataset,
    load_compiled_dataset,
)
from benchmarks.contracts import canonical_json, content_identifier
from benchmarks.progress import ProgressDisplay
from benchmarks.provenance import sha256_file, utc_now


SELECTION_SCHEMA_VERSION = 1
SELECTOR_VERSION = 1
GENERATED_INPUT_IDENTITY_VERSION = 1
DEFAULT_SAMPLE_SIZE = 100
PAIR_SETS = {
    "type1": {"pair_kind": "positive", "syntactic_types": [1]},
    "type2": {"pair_kind": "positive", "syntactic_types": [2]},
    "known-false-positive": {
        "pair_kind": "known_false_positive",
        "syntactic_types": None,
    },
}
DEDUPE_POLICIES = ("exact-unordered-fragment-pair", "none")


def _catalog_connection(compiled: VerifiedCompiledDataset) -> sqlite3.Connection:
    uri = (compiled.directory / "catalog.sqlite").resolve().as_uri()
    connection = sqlite3.connect(f"{uri}?mode=ro&immutable=1", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def _pair_predicate(pair_set: str, alias: str = "p") -> tuple[str, list[Any]]:
    declaration = PAIR_SETS[pair_set]
    predicate = f"{alias}.pair_kind=?"
    parameters: list[Any] = [declaration["pair_kind"]]
    syntactic_types = declaration["syntactic_types"]
    if syntactic_types is not None:
        predicate += f" AND {alias}.syntactic_type IN ({','.join('?' * len(syntactic_types))})"
        parameters.extend(syntactic_types)
    return predicate, parameters


_ROW_QUERY = """
SELECT
  p.*,
  f1.source_type AS f1_source_type, f1.source_name AS f1_source_name,
  f1.start_line AS f1_start_line, f1.end_line AS f1_end_line,
  f1.project AS f1_project, f1.tokens AS f1_tokens, f1.internal AS f1_internal,
  m1.expected_source_path AS f1_expected_source_path,
  m1.source_path AS f1_source_path, m1.extraction_status AS f1_extraction_status,
  m1.extraction_error AS f1_extraction_error,
  f2.source_type AS f2_source_type, f2.source_name AS f2_source_name,
  f2.start_line AS f2_start_line, f2.end_line AS f2_end_line,
  f2.project AS f2_project, f2.tokens AS f2_tokens, f2.internal AS f2_internal,
  m2.expected_source_path AS f2_expected_source_path,
  m2.source_path AS f2_source_path, m2.extraction_status AS f2_extraction_status,
  m2.extraction_error AS f2_extraction_error
FROM pair_rows AS p
JOIN functions AS f1 ON f1.function_id=p.function_id_one
JOIN functions AS f2 ON f2.function_id=p.function_id_two
LEFT JOIN function_materializations AS m1
  ON m1.functionality_id=p.functionality_id AND m1.function_id=p.function_id_one
LEFT JOIN function_materializations AS m2
  ON m2.functionality_id=p.functionality_id AND m2.function_id=p.function_id_two
"""


def _indexed_row_query(index: str) -> str:
    return _ROW_QUERY.replace(
        "FROM pair_rows AS p", f"FROM pair_rows AS p INDEXED BY {index}"
    )


def _function(row: sqlite3.Row, side: int) -> dict[str, Any]:
    prefix = f"f{side}_"
    function_id = row[f"function_id_{'one' if side == 1 else 'two'}"]
    fragment = row[f"fragment_{'one' if side == 1 else 'two'}_sha256"]
    return {
        "function_id": function_id,
        "functionality_id": row["functionality_id"],
        "source_type": row[prefix + "source_type"],
        "source_name": row[prefix + "source_name"],
        "start_line": row[prefix + "start_line"],
        "end_line": row[prefix + "end_line"],
        "project": row[prefix + "project"],
        "tokens": row[prefix + "tokens"],
        "internal": bool(row[prefix + "internal"]),
        "expected_source_path": row[prefix + "expected_source_path"],
        "source_path": row[prefix + "source_path"],
        "fragment_sha256": fragment,
        "extraction_status": row[prefix + "extraction_status"],
        "extraction_error": row[prefix + "extraction_error"],
    }


def _row_record(
    row: sqlite3.Row,
    *,
    original_fragment: str | None = None,
    modified_fragment: str | None = None,
) -> dict[str, Any]:
    disposition: str | None = None
    if original_fragment is not None and modified_fragment is not None:
        if row["fragment_one_sha256"] == row["fragment_two_sha256"]:
            disposition = "equal_direction_contributor"
        elif (
            row["fragment_one_sha256"] == original_fragment
            and row["fragment_two_sha256"] == modified_fragment
        ):
            disposition = "selected_direction_contributor"
        else:
            disposition = "excluded_reverse_duplicate"
    return {
        "catalog_pair_id": row["pair_id"],
        "source_row_id": row["source_row_hash"],
        "source_row_multiplicity": row["source_row_multiplicity"],
        "functionality_id": row["functionality_id"],
        "function_one": _function(row, 1),
        "function_two": _function(row, 2),
        "pair_kind": row["pair_kind"],
        "pair_type": row["pair_type"],
        "syntactic_type": row["syntactic_type"],
        "similarity": {
            "line": row["similarity_line"],
            "token": row["similarity_token"],
        },
        "size": {
            "min": row["min_size"],
            "max": row["max_size"],
            "min_pretty": row["min_pretty_size"],
            "max_pretty": row["max_pretty_size"],
        },
        "tokens": {"min": row["min_tokens"], "max": row["max_tokens"]},
        "judgment": {
            "min_judges": row["min_judges"],
            "min_confidence": row["min_confidence"],
        },
        "pair_internal": bool(row["pair_internal"]),
        "ordered_pair_id": row["ordered_pair_id"],
        "unordered_pair_id": row["unordered_pair_id"],
        "catalog_direction": row["canonical_direction"],
        "direction_disposition": disposition,
        "source_status": row["source_status"],
    }


def _generated_input_id(original: str, modified: str) -> str:
    return content_identifier(
        "bcb-generated-input",
        {
            "version": GENERATED_INPUT_IDENTITY_VERSION,
            "original_fragment_sha256": original,
            "modified_fragment_sha256": modified,
        },
    )


def _frame(frame_key: str, rows: Sequence[sqlite3.Row], dedupe: str) -> dict[str, Any]:
    first = rows[0]
    if dedupe == "exact-unordered-fragment-pair":
        original, modified = sorted(
            (first["fragment_one_sha256"], first["fragment_two_sha256"])
        )
        frame_id = frame_key
        direction_policy = "fragment-sha256-ascending"
    else:
        original = first["fragment_one_sha256"]
        modified = first["fragment_two_sha256"]
        frame_id = content_identifier(
            "bcb-row-frame",
            {
                "pair_kind": first["pair_kind"],
                "source_row_id": first["source_row_hash"],
            },
        )
        direction_policy = "catalog-row"
    records = [
        _row_record(
            row,
            original_fragment=original,
            modified_fragment=modified,
        )
        for row in rows
    ]
    return {
        "frame_id": frame_id,
        "generated_input_id": _generated_input_id(original, modified),
        "direction": {
            "policy": direction_policy,
            "original_fragment_sha256": original,
            "modified_fragment_sha256": modified,
        },
        "catalog_row_count": len(records),
        "source_row_multiplicity": sum(
            record["source_row_multiplicity"] for record in records
        ),
        "functionality_ids": sorted({row["functionality_id"] for row in rows}),
        "function_ids": sorted(
            {
                function_id
                for row in rows
                for function_id in (row["function_id_one"], row["function_id_two"])
            }
        ),
        "reverse_direction_exclusions": [
            {
                "catalog_pair_id": record["catalog_pair_id"],
                "source_row_id": record["source_row_id"],
                "source_row_multiplicity": record["source_row_multiplicity"],
            }
            for record in records
            if record["direction_disposition"] == "excluded_reverse_duplicate"
        ],
        "rows": records,
    }


def _write_jsonl(stream, value: Mapping[str, Any]) -> None:
    stream.write(canonical_json(dict(value)))
    stream.write(b"\n")


def _grouped_rows(rows: Iterable[sqlite3.Row], key: str) -> Iterator[tuple[str, list[sqlite3.Row]]]:
    active_key: str | None = None
    group: list[sqlite3.Row] = []
    for row in rows:
        row_key = str(row[key])
        if active_key is not None and row_key != active_key:
            yield active_key, group
            group = []
        active_key = row_key
        group.append(row)
    if active_key is not None:
        yield active_key, group


def _available_frame_query(pair_set: str, dedupe: str) -> tuple[str, list[Any]]:
    predicate, parameters = _pair_predicate(pair_set)
    if dedupe == "exact-unordered-fragment-pair":
        order = "p.unordered_pair_id, p.source_row_hash"
    else:
        order = "p.source_row_hash"
    return (
        _indexed_row_query("pair_selection_idx")
        + f" WHERE {predicate} AND p.source_status='available' ORDER BY {order}",
        parameters,
    )


def _frame_inventory(
    connection: sqlite3.Connection, pair_set: str, dedupe: str
) -> Iterator[tuple[str, int, int]]:
    predicate, parameters = _pair_predicate(pair_set)
    if dedupe == "exact-unordered-fragment-pair":
        query = (
            "SELECT unordered_pair_id, COUNT(*), SUM(source_row_multiplicity) "
            f"FROM pair_rows p WHERE {predicate} AND source_status='available' "
            "GROUP BY unordered_pair_id ORDER BY unordered_pair_id"
        )
        yield from connection.execute(query, parameters)
        return
    query = (
        "SELECT source_row_hash, 1, source_row_multiplicity FROM pair_rows p "
        f"WHERE {predicate} AND source_status='available' ORDER BY source_row_hash"
    )
    yield from connection.execute(query, parameters)


def _sample_rank(seed: int, frame_id: str) -> bytes:
    return hashlib.sha256(
        canonical_json({"seed": seed, "frame_id": frame_id})
    ).digest()


def _selected_frame_ids(
    inventory: Iterable[tuple[str, int, int]],
    *,
    mode: str,
    sample_size: int,
    seed: int,
) -> tuple[set[str] | None, dict[str, int]]:
    if mode == "census":
        frames = catalog_rows = source_rows = 0
        for _, row_count, multiplicity in inventory:
            frames += 1
            catalog_rows += row_count
            source_rows += multiplicity
        return None, {
            "eligible_frames": frames,
            "eligible_catalog_rows": catalog_rows,
            "eligible_source_rows": source_rows,
        }
    smallest = heapq.nsmallest(
        sample_size,
        (
            (_sample_rank(seed, str(frame_id)), str(frame_id), row_count, multiplicity)
            for frame_id, row_count, multiplicity in inventory
        ),
    )
    # Counts for the complete frame are obtained separately for sample mode.
    return {item[1] for item in smallest}, {}


def _scalar_counts(
    connection: sqlite3.Connection, pair_set: str, dedupe: str
) -> dict[str, int]:
    predicate, parameters = _pair_predicate(pair_set)
    frame_expression = (
        "COUNT(DISTINCT unordered_pair_id)"
        if dedupe == "exact-unordered-fragment-pair"
        else "COUNT(*)"
    )
    row = connection.execute(
        f"SELECT {frame_expression}, COUNT(*), "
        "COALESCE(SUM(source_row_multiplicity),0), "
        "COALESCE(SUM(CASE WHEN min_tokens<50 THEN source_row_multiplicity ELSE 0 END),0) "
        f"FROM pair_rows p WHERE {predicate} AND source_status='available'",
        parameters,
    ).fetchone()
    unavailable = connection.execute(
        f"SELECT COUNT(*), COALESCE(SUM(source_row_multiplicity),0) FROM pair_rows p "
        f"WHERE {predicate} AND source_status!='available'",
        parameters,
    ).fetchone()
    return {
        "eligible_frames": int(row[0]),
        "eligible_catalog_rows": int(row[1]),
        "eligible_source_rows": int(row[2]),
        "eligible_source_rows_below_50_tokens": int(row[3]),
        "unavailable_catalog_rows": int(unavailable[0]),
        "unavailable_source_rows": int(unavailable[1]),
    }


def _conflict_ids(connection: sqlite3.Connection) -> list[str]:
    return [
        str(row[0])
        for row in connection.execute(
            "SELECT DISTINCT fp.unordered_pair_id FROM pair_rows AS fp "
            "INDEXED BY pair_selection_idx "
            "WHERE fp.pair_kind='known_false_positive' "
            "AND fp.source_status='available' AND EXISTS ("
            "SELECT 1 FROM pair_rows AS positive INDEXED BY pair_unordered_idx "
            "WHERE positive.unordered_pair_id=fp.unordered_pair_id "
            "AND positive.pair_kind='positive' "
            "AND positive.source_status='available') ORDER BY fp.unordered_pair_id"
        )
    ]


def _write_conflicts(
    connection: sqlite3.Connection, path: Path, expected_count: int
) -> dict[str, int]:
    identifiers = _conflict_ids(connection)
    if len(identifiers) != expected_count:
        raise ValueError(
            "compiled label-conflict count does not match catalog: "
            f"{expected_count} declared, {len(identifiers)} observed"
        )
    row_count = source_rows = 0
    with path.open("wb") as stream:
        if not identifiers:
            return {"frames": 0, "catalog_rows": 0, "source_rows": 0}
        placeholders = ",".join("?" * len(identifiers))
        rows = connection.execute(
            _indexed_row_query("pair_unordered_idx")
            + f" WHERE p.unordered_pair_id IN ({placeholders}) "
            "ORDER BY p.unordered_pair_id, p.pair_kind, p.source_row_hash",
            identifiers,
        )
        for frame_id, group in _grouped_rows(rows, "unordered_pair_id"):
            records = [_row_record(row) for row in group]
            row_count += len(records)
            source_rows += sum(item["source_row_multiplicity"] for item in records)
            _write_jsonl(
                stream,
                {
                    "unordered_pair_id": frame_id,
                    "labels": sorted({item["pair_kind"] for item in records}),
                    "catalog_row_count": len(records),
                    "source_row_multiplicity": sum(
                        item["source_row_multiplicity"] for item in records
                    ),
                    "rows": records,
                },
            )
    return {
        "frames": len(identifiers),
        "catalog_rows": row_count,
        "source_rows": source_rows,
    }


def _artifact(path: Path) -> dict[str, Any]:
    return {
        "path": path.name,
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def create_selection(
    compiled: VerifiedCompiledDataset,
    *,
    data_root: Path,
    pair_set: str,
    mode: str,
    role: str,
    dedupe: str = "exact-unordered-fragment-pair",
    sample_size: int = DEFAULT_SAMPLE_SIZE,
    seed: int = 0,
    progress: ProgressDisplay | None = None,
) -> tuple[Path, Mapping[str, Any], bool]:
    """Create or validate one immutable selection publication."""

    if pair_set not in PAIR_SETS:
        raise ValueError(f"unsupported pair set: {pair_set}")
    if mode not in {"sample", "census"}:
        raise ValueError(f"unsupported selection mode: {mode}")
    if role not in {"tuning", "evaluation"}:
        raise ValueError(f"unsupported selection role: {role}")
    if dedupe not in DEDUPE_POLICIES:
        raise ValueError(f"unsupported dedupe policy: {dedupe}")
    if sample_size <= 0:
        raise ValueError("sample size must be positive")

    request = {
        "selector_version": SELECTOR_VERSION,
        "compiled_dataset_id": compiled.dataset_id,
        "compiled_manifest_sha256": compiled.manifest_sha256,
        "pair_set": pair_set,
        "mode": mode,
        "role": role,
        "dedupe": dedupe,
        "direction": (
            "fragment-sha256-ascending"
            if dedupe == "exact-unordered-fragment-pair"
            else "catalog-row"
        ),
        "sample": (
            {"algorithm": "sha256-seed-frame-id", "seed": seed, "size": sample_size}
            if mode == "sample"
            else None
        ),
        "eligibility": {
            "source_status": "available",
            "minimum_tokens": None,
            "minimum_judges": None,
            "minimum_confidence": None,
        },
    }
    selection_id = content_identifier("bcb-selection", request)
    root = data_root.expanduser().resolve() / "bigclonebench" / "selections"
    final = root / selection_id
    if final.exists():
        manifest = load_selection(final, expected_dataset_id=compiled.dataset_id)
        return final, manifest, True

    root.mkdir(parents=True, exist_ok=True)
    staging = root / f".staging-{uuid.uuid4().hex}"
    staging.mkdir()
    frames_path = staging / "frames.jsonl"
    exclusions_path = staging / "exclusions.jsonl"
    conflicts_path = staging / "label-conflicts.jsonl"
    try:
        with closing(_catalog_connection(compiled)) as connection:
            counts = _scalar_counts(connection, pair_set, dedupe)
            selected_ids, inventory_counts = _selected_frame_ids(
                _frame_inventory(connection, pair_set, dedupe),
                mode=mode,
                sample_size=sample_size,
                seed=seed,
            )
            counts.update(inventory_counts)
            selected_frames = selected_catalog_rows = selected_source_rows = 0
            reverse_catalog_rows = reverse_source_rows = 0
            if progress is not None:
                progress.set_total(counts["eligible_frames"], completed=0)
                progress.update(detail=f"writing {pair_set} {mode} frames")
            query, parameters = _available_frame_query(pair_set, dedupe)
            group_key = (
                "unordered_pair_id"
                if dedupe == "exact-unordered-fragment-pair"
                else "source_row_hash"
            )
            with frames_path.open("wb") as frames, exclusions_path.open("wb") as exclusions:
                for completed, (frame_key, rows) in enumerate(
                    _grouped_rows(connection.execute(query, parameters), group_key),
                    start=1,
                ):
                    if selected_ids is not None and frame_key not in selected_ids:
                        _write_jsonl(
                            exclusions,
                            {
                                "frame_id": frame_key,
                                "reason": "deterministic_sample_not_selected",
                                "catalog_row_count": len(rows),
                                "source_row_multiplicity": sum(
                                    row["source_row_multiplicity"] for row in rows
                                ),
                            },
                        )
                    else:
                        frame = _frame(frame_key, rows, dedupe)
                        _write_jsonl(frames, frame)
                        selected_frames += 1
                        selected_catalog_rows += frame["catalog_row_count"]
                        selected_source_rows += frame["source_row_multiplicity"]
                        reverse_catalog_rows += len(frame["reverse_direction_exclusions"])
                        reverse_source_rows += sum(
                            item["source_row_multiplicity"]
                            for item in frame["reverse_direction_exclusions"]
                        )
                    if progress is not None and (
                        completed % 1000 == 0 or completed == counts["eligible_frames"]
                    ):
                        progress.update(completed)

                unavailable_predicate, unavailable_parameters = _pair_predicate(pair_set)
                unavailable_rows = connection.execute(
                    _indexed_row_query("pair_selection_idx")
                    + f" WHERE {unavailable_predicate} AND p.source_status!='available' "
                    "ORDER BY p.source_row_hash",
                    unavailable_parameters,
                )
                for row in unavailable_rows:
                    _write_jsonl(
                        exclusions,
                        {
                            "reason": "source_unavailable",
                            "row": _row_record(row),
                        },
                    )

            conflict_counts = _write_conflicts(
                connection,
                conflicts_path,
                int(compiled.manifest["counts"]["positive_negative_label_conflicts"]),
            )

        counts.update(
            {
                "selected_frames": selected_frames,
                "selected_catalog_rows": selected_catalog_rows,
                "selected_source_rows": selected_source_rows,
                "sample_excluded_frames": counts["eligible_frames"] - selected_frames,
                "reverse_direction_excluded_catalog_rows": reverse_catalog_rows,
                "reverse_direction_excluded_source_rows": reverse_source_rows,
            }
        )
        manifest = {
            "schema_version": SELECTION_SCHEMA_VERSION,
            "selection_id": selection_id,
            "created_at": utc_now(),
            "request": request,
            "compiled_dataset": {
                "dataset_id": compiled.dataset_id,
                "manifest_sha256": compiled.manifest_sha256,
                "catalog_sha256": compiled.manifest["artifacts"]["catalog"]["sha256"],
            },
            "counts": counts,
            "label_conflicts": conflict_counts,
            "artifacts": {
                "frames": _artifact(frames_path),
                "exclusions": _artifact(exclusions_path),
                "label_conflicts": _artifact(conflicts_path),
            },
        }
        (staging / "manifest.json").write_bytes(canonical_json(manifest) + b"\n")
        try:
            os.replace(staging, final)
        except OSError:
            if not final.is_dir():
                raise
            shutil.rmtree(staging)
            existing = load_selection(final, expected_dataset_id=compiled.dataset_id)
            return final, existing, True
        verified = load_selection(final, expected_dataset_id=compiled.dataset_id)
        return final, verified, False
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def load_selection(
    directory: Path, *, expected_dataset_id: str | None = None
) -> Mapping[str, Any]:
    """Validate a published immutable selection manifest and its artifacts."""

    directory = directory.expanduser().resolve()
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError(f"selection directory is unavailable: {directory}")
    manifest_path = directory / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError(f"selection manifest is unavailable: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("schema_version") != SELECTION_SCHEMA_VERSION:
        raise ValueError(f"invalid selection manifest: {manifest_path}")
    request = manifest.get("request")
    if not isinstance(request, dict):
        raise ValueError("selection request is missing or invalid")
    expected_id = content_identifier("bcb-selection", request)
    if manifest.get("selection_id") != expected_id or directory.name != expected_id:
        raise ValueError("selection identity does not match its request or directory")
    if expected_dataset_id is not None and request.get("compiled_dataset_id") != expected_dataset_id:
        raise ValueError("selection belongs to a different compiled dataset")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ValueError("selection artifacts are missing or invalid")
    for name in ("frames", "exclusions", "label_conflicts"):
        declaration = artifacts.get(name)
        if not isinstance(declaration, dict) or declaration.get("path") != f"{name.replace('_', '-')}.jsonl":
            raise ValueError(f"selection {name} artifact declaration is invalid")
        path = directory / declaration["path"]
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"selection artifact is unavailable: {path}")
        if path.stat().st_size != declaration.get("size_bytes") or sha256_file(path) != declaration.get("sha256"):
            raise ValueError(f"selection artifact checksum mismatch: {path}")
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", help="Compiled dataset ID or directory.")
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--pair-set", choices=tuple(PAIR_SETS), required=True)
    parser.add_argument("--mode", choices=("sample", "census"), default="sample")
    parser.add_argument("--role", choices=("tuning", "evaluation"), default="tuning")
    parser.add_argument("--dedupe", choices=DEDUPE_POLICIES, default=DEDUPE_POLICIES[0])
    parser.add_argument("--sample-size", type=int, default=DEFAULT_SAMPLE_SIZE)
    parser.add_argument("--seed", type=int, default=0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        with ProgressDisplay("selection/validate", detail="checking compiled catalog") as progress:
            compiled = load_compiled_dataset(
                args.dataset, data_root=args.data_root, verification="identity"
            )
            progress.finish("compiled catalog validated", completion="complete")
        with ProgressDisplay("selection/build", detail=f"{args.pair_set} {args.mode}") as progress:
            directory, manifest, reused = create_selection(
                compiled,
                data_root=args.data_root,
                pair_set=args.pair_set,
                mode=args.mode,
                role=args.role,
                dedupe=args.dedupe,
                sample_size=args.sample_size,
                seed=args.seed,
                progress=progress,
            )
            counts = manifest["counts"]
            progress.finish(
                f"{counts['selected_frames']:,} frames from "
                f"{counts['selected_source_rows']:,} source rows"
            )
        print(f"BigCloneBench selection: {'reused' if reused else 'published'}")
        print(f"selection_id={manifest['selection_id']}")
        print(f"directory={directory}")
        print(
            f"pair_set={args.pair_set} mode={args.mode} "
            f"unique_frames={counts['selected_frames']} "
            f"source_rows={counts['selected_source_rows']}"
        )
        print(
            "label_conflicts="
            f"{manifest['label_conflicts']['frames']} "
            f"below_50_token_rows={counts['eligible_source_rows_below_50_tokens']}"
        )
        return 0
    except (OSError, ValueError, sqlite3.Error, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
