#!/usr/bin/env python3
"""Offline generator for the committed medium BigCloneBench preset."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from contextlib import closing
from pathlib import Path
from typing import Any, Mapping


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.bigclonebench.compile import DEFAULT_DATA_ROOT
from benchmarks.bigclonebench.compiled import load_compiled_dataset
PAIR_SETS = ("type1", "type2", "type3", "known-false-positive")
PRESET_PATH = SCRIPT_DIR / "frozen_profiles.jsonl"
from benchmarks.bigclonebench.selection import (
    TYPE3_STRATA,
    _catalog_connection,
    _frame,
    _row_groups_for_identifiers,
    _sample_rank,
    create_selection,
    load_selection,
    type3_stratum,
)
from benchmarks.contracts import canonical_json
from benchmarks.provenance import utc_now


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", help="Compiled dataset ID or directory")
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--output", type=Path, default=PRESET_PATH)
    parser.add_argument("--seed", type=int, default=0)
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


def _conflict_ids(directory: Path, manifest: Mapping[str, Any]) -> set[str]:
    path = directory / manifest["artifacts"]["label_conflicts"]["path"]
    return {
        json.loads(line)["unordered_pair_id"]
        for line in path.read_text(encoding="utf-8").splitlines()
    }


def _pivot(seed: int, attempt: int, maximum: int) -> int:
    digest = hashlib.sha256(
        canonical_json({"algorithm": "sha256-pair-id-pivot-v1", "seed": seed, "attempt": attempt})
    ).digest()
    return 1 + int.from_bytes(digest, "big") % maximum


def _probe_type3_frames(
    compiled: Any, *, seed: int, conflict_ids: set[str]
) -> list[dict[str, Any]]:
    """Copy a bounded deterministic Type-3 sample from the catalog."""

    candidates: list[str] = []
    seen: set[str] = set()
    predicates = {
        "very_strong": "similarity_line >= .9 AND similarity_token >= .9",
        "strong": "MIN(similarity_line, similarity_token) >= .7 AND MIN(similarity_line, similarity_token) < .9",
        "moderate": "MIN(similarity_line, similarity_token) >= .5 AND MIN(similarity_line, similarity_token) < .7",
        "weak": "MIN(similarity_line, similarity_token) < .5",
    }
    with closing(_catalog_connection(compiled)) as connection:
        for band, _, _ in TYPE3_STRATA:
            rows = connection.execute(
                "SELECT unordered_pair_id FROM pair_rows NOT INDEXED "
                "WHERE pair_kind='positive' AND syntactic_type=3 "
                "AND source_status='available' AND " + predicates[band] +
                " ORDER BY pair_id LIMIT 2000"
            )
            added = 0
            for (frame_id,) in rows:
                if frame_id in seen or frame_id in conflict_ids:
                    continue
                seen.add(frame_id)
                candidates.append(str(frame_id))
                added += 1
                if added == 100:
                    break
        groups = list(
            _row_groups_for_identifiers(
                connection,
                "type3",
                "exact-unordered-fragment-pair",
                tuple(candidates),
            )
        )
    frames = {
        name: [] for name, _, _ in TYPE3_STRATA
    }
    for frame_id, rows in groups:
        frame = _frame(frame_id, rows, "exact-unordered-fragment-pair")
        strength = min(
            min(float(row["similarity"]["line"]), float(row["similarity"]["token"]))
            for row in frame["rows"]
        )
        frames[type3_stratum(strength)].append(frame)
    missing = {name: 25 - len(values) for name, values in frames.items() if len(values) < 25}
    if missing:
        raise ValueError(f"not enough Type-3 frames for frozen sample: {missing}")
    return [frame for name, _, _ in TYPE3_STRATA for frame in frames[name][:25]]


def generate(args: argparse.Namespace) -> tuple[Path, dict[str, int]]:
    compiled = load_compiled_dataset(
        args.dataset, data_root=args.data_root, verification="identity"
    )
    supplied = _selection_arguments(args.selection)
    selected: dict[str, tuple[Path, Mapping[str, Any]]] = {}
    for pair_set in PAIR_SETS:
        if pair_set == "type3" and pair_set not in supplied:
            continue
        if pair_set in supplied:
            directory = supplied[pair_set].expanduser().resolve()
            manifest = load_selection(
                directory, expected_dataset_id=compiled.dataset_id
            )
        else:
            directory, manifest, _ = create_selection(
                compiled,
                data_root=args.data_root,
                pair_set=pair_set,
                mode="sample",
                role="tuning",
                sample_size=100,
                seed=args.seed,
            )
        request = manifest["request"]
        if (
            request["pair_set"] != pair_set
            or request["mode"] != "sample"
            or request["role"] != "tuning"
            or request["sample"]["seed"] != args.seed
            or request["sample"]["size"] != 100
            or manifest["counts"]["selected_frames"] != 100
        ):
            raise ValueError(f"selection is not the required medium source: {directory}")
        selected[pair_set] = directory, manifest

    conflict_source = next(
        (value for key, value in selected.items() if key != "type3"), None
    )
    if conflict_source is None:
        raise ValueError("a verified non-Type-3 selection is required for conflicts")
    conflicts = _conflict_ids(*conflict_source)
    expected_conflicts = int(
        compiled.manifest["counts"]["positive_negative_label_conflicts"]
    )
    if len(conflicts) != expected_conflicts:
        raise ValueError(
            "verified conflict artifact does not match the compiled conflict count"
        )
    type3_frames = (
        _frames(*selected["type3"])
        if "type3" in selected
        else _probe_type3_frames(compiled, seed=args.seed, conflict_ids=conflicts)
    )

    header = {
        "kind": "manifest",
        "schema_version": 1,
        "created_at": utc_now(),
        "compiled_dataset": {
            "dataset_id": compiled.dataset_id,
            "manifest_sha256": compiled.manifest_sha256,
            "catalog_sha256": compiled.manifest["artifacts"]["catalog"]["sha256"],
        },
        "selection_algorithm": "committed-medium-sha256-rank-v1",
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
        "type3_generation": (
            "verified_selection"
            if "type3" in selected
            else "bounded_sha256_seeded_pair_id_primary_key_probes_v1"
        ),
    }
    output_rows: list[dict[str, Any]] = []
    for pair_set in PAIR_SETS:
        frames = (
            type3_frames
            if pair_set == "type3"
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
    with args.output.open("wb") as stream:
        stream.write(canonical_json(header) + b"\n")
        for row in output_rows:
            stream.write(canonical_json(row) + b"\n")
    return args.output, {pair_set: 100 for pair_set in PAIR_SETS}


def main() -> int:
    args = parse_args()
    try:
        path, counts = generate(args)
        print(f"wrote {path}")
        print(" ".join(f"{name}={count}" for name, count in counts.items()))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
