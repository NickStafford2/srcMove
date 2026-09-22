#!/usr/bin/env python3
"""Publish small and medium selections from the checked-in frozen table."""

from __future__ import annotations

import json
import os
import shutil
import uuid
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from bigMoveBench.catalog import VerifiedCompiledDataset
from bigMoveBench.selection import SELECTION_SCHEMA_VERSION, TYPE3_STRATA, _artifact, load_selection
from benchmarking.identity import canonical_json, content_identifier
from benchmarking.provenance import sha256_file, utc_now


PRESET_PATH = Path(__file__).with_name("frozen_profiles.jsonl")
PAIR_SETS = ("type1", "type2", "type3", "known-false-positive")
PROFILE_SIZES = {"small": 20, "medium": 100}


def _rows(profile: str, pair_set: str) -> tuple[Mapping[str, Any], list[Mapping[str, Any]]]:
    if profile not in PROFILE_SIZES or pair_set not in PAIR_SETS:
        raise ValueError(f"unsupported frozen profile: {profile}/{pair_set}")
    values = [json.loads(line) for line in PRESET_PATH.read_text(encoding="utf-8").splitlines()]
    if not values or values[0].get("kind") != "manifest":
        raise ValueError("frozen profile manifest is missing")
    limit = 5 if pair_set == "type3" and profile == "small" else (25 if pair_set == "type3" else PROFILE_SIZES[profile])
    rows = [
        row for row in values[1:]
        if row.get("pair_set") == pair_set
        and (row.get("band_rank", row.get("rank", 0)) <= limit)
    ]
    expected = PROFILE_SIZES[profile]
    if len(rows) != expected:
        raise ValueError(f"frozen {pair_set} {profile} profile has {len(rows)} rows; expected {expected}")
    return values[0], rows


def create_frozen_selection(
    compiled: VerifiedCompiledDataset,
    *,
    data_root: Path,
    pair_set: str,
    profile: str,
) -> tuple[Path, Mapping[str, Any], bool]:
    preset, rows = _rows(profile, pair_set)
    identity = preset["compiled_dataset"]
    expected_identity = {
        "dataset_id": compiled.dataset_id,
        "manifest_sha256": compiled.manifest_sha256,
        "catalog_sha256": compiled.manifest["artifacts"]["catalog"]["sha256"],
    }
    if identity != expected_identity:
        raise ValueError("frozen profiles belong to a different compiled dataset")
    request = {
        "selector_version": "frozen-profile-v2",
        "compiled_dataset_id": compiled.dataset_id,
        "compiled_manifest_sha256": compiled.manifest_sha256,
        "pair_set": pair_set,
        "mode": "preset",
        "profile": profile,
        "dedupe": "exact-unordered-fragment-pair",
        "direction": "fragment-sha256-ascending",
        "sample": {
            "algorithm": preset["selection_algorithm"],
            "seed": preset["seed"],
            "size": len(rows),
            "preset_sha256": sha256_file(PRESET_PATH),
        },
        "eligibility": preset["eligibility"],
    }
    selection_id = content_identifier("bcb-selection", request)
    root = data_root.expanduser().resolve() / "bigclonebench" / "selections"
    final = root / selection_id
    if final.exists():
        return final, load_selection(final, expected_dataset_id=compiled.dataset_id), True

    root.mkdir(parents=True, exist_ok=True)
    staging = root / f".staging-{uuid.uuid4().hex}"
    staging.mkdir()
    try:
        frames_path = staging / "frames.jsonl"
        exclusions_path = staging / "exclusions.jsonl"
        conflicts_path = staging / "label-conflicts.jsonl"
        with frames_path.open("wb") as stream:
            for row in rows:
                stream.write(canonical_json(row["frame"]) + b"\n")
        exclusions_path.write_bytes(b"")
        conflicts_path.write_bytes(b"")
        catalog_rows = sum(int(row["frame"]["catalog_row_count"]) for row in rows)
        source_rows = sum(int(row["frame"]["source_row_multiplicity"]) for row in rows)
        counts = {
            "eligible_frames": len(rows), "eligible_catalog_rows": catalog_rows,
            "eligible_source_rows": source_rows, "eligible_source_rows_below_50_tokens": 0,
            "content_label_conflict_excluded_frames": 0,
            "content_label_conflict_excluded_catalog_rows": 0,
            "content_label_conflict_excluded_source_rows": 0,
            "unavailable_catalog_rows": 0, "unavailable_source_rows": 0,
            "selected_frames": len(rows), "selected_catalog_rows": catalog_rows,
            "selected_source_rows": source_rows, "sample_excluded_frames": 0,
            "reverse_direction_excluded_catalog_rows": 0,
            "reverse_direction_excluded_source_rows": 0,
        }
        strata = None
        if pair_set == "type3":
            band_counts = Counter(row["type3_strength_stratum"] for row in rows)
            strata = {name: {"selected_frames": band_counts[name]} for name, _, _ in TYPE3_STRATA}
        manifest = {
            "schema_version": SELECTION_SCHEMA_VERSION,
            "selection_id": selection_id,
            "created_at": utc_now(),
            "request": request,
            "compiled_dataset": dict(identity),
            "counts": counts,
            "strata": strata,
            "label_conflicts": {"frames": 0, "catalog_rows": 0, "source_rows": 0},
            "artifacts": {
                "frames": _artifact(frames_path),
                "exclusions": _artifact(exclusions_path),
                "label_conflicts": _artifact(conflicts_path),
            },
        }
        (staging / "manifest.json").write_bytes(canonical_json(manifest) + b"\n")
        os.replace(staging, final)
        return final, load_selection(final, expected_dataset_id=compiled.dataset_id), False
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise
