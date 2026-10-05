#!/usr/bin/env python3
"""Offline generator for the committed medium BigCloneBench preset."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bigMoveBench.catalog import load_compiled_dataset
from bigMoveBench.paths import DEFAULT_CACHE_ROOT
from bigMoveBench.categories import CATEGORY_RULES_VERSION
from bigMoveBench.progress import ProgressDisplay
from bigMoveBench.selection_index import sample_frames
from benchmarking.provenance import sha256_file
PAIR_SETS = ("type1", "type2b", "type2c", "type3", "known-false-positive")
PRESET_PATH = SCRIPT_DIR / "frozen_profiles.jsonl"
from bigMoveBench.selection import (
    TYPE3_STRATA,
    _sample_rank,
    create_selection,
    load_selection,
    type3_stratum,
)
from benchmarking.identity import canonical_json
from benchmarking.provenance import utc_now


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", help="Compiled dataset ID or directory")
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    parser.add_argument("--output", type=Path, default=PRESET_PATH)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--selection-index", type=Path, help="Reuse a versioned dense-position SQLite companion")
    parser.add_argument(
        "--selection",
        action="append",
        default=[],
        metavar="PAIR_SET=PATH",
        help="Reuse a verified medium selection instead of generating it",
    )
    return parser.parse_args()


def _selection_arguments(values: list[str]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for value in values:
        pair_set, separator, path = value.partition("=")
        if not separator or pair_set not in PAIR_SETS or pair_set in result:
            raise ValueError(f"invalid --selection value: {value}")
        result[pair_set] = Path(path)
    return result


def _frames(directory: Path, manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    path = directory / manifest["artifacts"]["frames"]["path"]
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def generate(args: argparse.Namespace) -> tuple[Path, dict[str, int]]:
    if args.output.exists():
        raise ValueError(f"profile output already exists; choose a new --output: {args.output}")
    with ProgressDisplay("profiles/validate", detail="checking compiled catalog identity"):
        compiled = load_compiled_dataset(
            args.dataset, data_root=args.cache_root, verification="identity"
        )
    supplied = _selection_arguments(args.selection)
    selected: dict[str, tuple[Path, Mapping[str, Any]]] = {}
    indexed_frames = None
    sampling = None
    if getattr(args, "selection_index", None):
        if supplied:
            raise ValueError("--selection-index cannot mix with --selection")
        with ProgressDisplay("profiles/indexed", total=500, detail="sampling dense positions and retrieving selected frames") as progress:
            indexed_frames, sampling = sample_frames(compiled, args.selection_index, seed=args.seed, progress=progress)
            progress.update(detail="hashing companion provenance")
            sampling["index_sha256"] = sha256_file(args.selection_index)
    for pair_set in (() if indexed_frames is not None else PAIR_SETS):
        if pair_set in supplied:
            directory = supplied[pair_set].expanduser().resolve()
            manifest = load_selection(
                directory, expected_dataset_id=compiled.dataset_id
            )
        else:
            with ProgressDisplay("profiles/selection", detail=f"{pair_set}: full-frame ranking") as progress:
                directory, manifest, _ = create_selection(
                    compiled,
                    data_root=args.cache_root,
                    pair_set=pair_set,
                    mode="sample",
                    sample_size=100,
                    seed=args.seed,
                    progress=progress,
                )
        request = manifest["request"]
        if (
            request.get("category_rules_version") != CATEGORY_RULES_VERSION
            or request["pair_set"] != pair_set
            or request["mode"] != "sample"
            or request["sample"]["seed"] != args.seed
            or request["sample"]["size"] != 100
            or manifest["counts"]["selected_frames"] != 100
        ):
            raise ValueError(f"selection is not the required medium source: {directory}")
        selected[pair_set] = directory, manifest

    type3_frames = indexed_frames["type3"] if indexed_frames is not None else _frames(*selected["type3"])

    header = {
        "kind": "manifest",
        "category_rules_version": CATEGORY_RULES_VERSION,
        "schema_version": 1,
        "created_at": utc_now(),
        "compiled_dataset": {
            "dataset_id": compiled.dataset_id,
            "manifest_sha256": compiled.manifest_sha256,
            "catalog_sha256": compiled.manifest["artifacts"]["catalog"]["sha256"],
        },
        "selection_algorithm": sampling["algorithm"] if sampling else "committed-medium-sha256-rank-v1",
        **({"indexed_selection": sampling} if sampling else {}),
        "seed": args.seed,
        "profiles": {"small": 20, "medium": 100},
        "type3_band_profiles": {"small": 5, "medium": 25},
        "eligibility": {
            "source_status": "available",
            "content_label_conflicts": "excluded_at_generation",
            "minimum_tokens": None,
            "minimum_judges": None,
            "minimum_confidence": None,
        },
        "source_selection_ids": {
            pair_set: manifest["selection_id"]
            for pair_set, (_, manifest) in selected.items()
        },
        "type3_generation": "indexed_full_population" if sampling else "verified_selection",
    }
    output_rows: list[dict[str, Any]] = []
    for pair_set in PAIR_SETS:
        frames = (
            type3_frames
            if pair_set == "type3"
            else indexed_frames[pair_set] if indexed_frames is not None
            else _frames(*selected[pair_set])
        )
        if pair_set == "type3":
            grouped: dict[str, list[dict[str, Any]]] = {}
            for frame in frames:
                strength = min(
                    min(float(row["similarity"]["line"]), float(row["similarity"]["token"]))
                    for row in frame["rows"]
                )
                grouped.setdefault(type3_stratum(strength), []).append(frame)
            pair_rank = 0
            for band, _, _ in TYPE3_STRATA:
                band_frames = grouped.get(band, [])
                ranked = sorted(
                    band_frames,
                    key=lambda frame: (_sample_rank(args.seed, frame["frame_id"]), frame["frame_id"]),
                )
                for band_rank, frame in enumerate(ranked, start=1):
                    pair_rank += 1
                    output_rows.append(
                        {
                            "kind": "frame",
                            "pair_set": pair_set,
                            "rank": pair_rank,
                            "band_rank": band_rank,
                            "type3_strength_stratum": band,
                            "frame": frame,
                        }
                    )
        else:
            ranked = sorted(
                frames,
                key=lambda frame: (_sample_rank(args.seed, frame["frame_id"]), frame["frame_id"]),
            )
            output_rows.extend(
                {
                    "kind": "frame",
                    "pair_set": pair_set,
                    "rank": rank,
                    "frame": frame,
                }
                for rank, frame in enumerate(ranked, start=1)
            )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with ProgressDisplay("profiles/publish", detail="publishing a new immutable profile"):
        descriptor, name = tempfile.mkstemp(prefix=".profiles-", dir=args.output.parent)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(canonical_json(header) + b"\n")
                for row in output_rows:
                    stream.write(canonical_json(row) + b"\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.link(name, args.output)
        finally:
            Path(name).unlink(missing_ok=True)
    return args.output, {pair_set: 100 for pair_set in PAIR_SETS}


def main() -> int:
    args = parse_args()
    try:
        path, counts = generate(args)
        print(f"wrote {path}")
        print(" ".join(f"{name}={count}" for name, count in counts.items()))
        return 0
    except (OSError, ValueError, json.JSONDecodeError, sqlite3.Error) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
