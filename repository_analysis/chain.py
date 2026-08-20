"""Verification and reporting for immutable older-history continuations."""

from __future__ import annotations

import csv
import hashlib
import os
import uuid
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .inputs import (
    FrozenAnalysisManifest,
    build_pair_work_items,
    load_frozen_manifest,
)
from .reporting import (
    FAILURE_STATUSES,
    SUMMARY_COLUMNS,
    _pretty_json,
    _replace_derived_file,
    _sealed_receipts,
    _summary_row,
    _write_temporary,
    derive_history_summary,
)
from .resume import prepare_verified_resume
from .retention import RetentionPolicy


CHAIN_REPORT_SCHEMA_VERSION = 1
CHAIN_SUMMARY_COLUMNS = (
    "chain_sequence",
    "segment_index",
    "segment_sequence",
    "segment_analysis_root",
    *SUMMARY_COLUMNS,
)


@dataclass(frozen=True, slots=True)
class AnalysisSegment:
    analysis_root: Path
    manifest: FrozenAnalysisManifest
    manifest_sha256: str


def load_verified_analysis_chain(
    oldest_analysis_root: Path,
) -> tuple[AnalysisSegment, ...]:
    """Load an oldest-to-newest chain and verify every link and completed segment."""

    segments: list[AnalysisSegment] = []
    seen: set[Path] = set()
    root = oldest_analysis_root.expanduser().resolve()
    while True:
        if root in seen:
            raise ValueError(f"analysis continuation cycle detected at {root}")
        seen.add(root)
        manifest = load_frozen_manifest(root)
        segment = AnalysisSegment(
            analysis_root=root,
            manifest=manifest,
            manifest_sha256=hashlib.sha256(manifest.canonical_bytes()).hexdigest(),
        )
        _verify_completed_segment(segment)
        segments.append(segment)
        continuation = manifest.continuation
        if continuation is None:
            break
        newer_root = continuation.newer_analysis_root.resolve()
        newer = load_frozen_manifest(newer_root)
        newer_sha256 = hashlib.sha256(newer.canonical_bytes()).hexdigest()
        if newer_sha256 != continuation.newer_manifest_sha256:
            raise ValueError("newer analysis manifest checksum drift")
        if manifest.commits[-1] != continuation.boundary_commit:
            raise ValueError("older segment boundary drift")
        if newer.commits[0] != continuation.boundary_commit:
            raise ValueError("newer segment boundary drift")
        _verify_segment_compatibility(manifest, newer)
        root = newer_root
    return tuple(segments)


def publish_chain_reports(oldest_analysis_root: Path) -> dict[str, Any]:
    """Atomically publish one chronological report across a verified chain."""

    segments = load_verified_analysis_chain(oldest_analysis_root)
    root = segments[0].analysis_root
    csv_destination = root / "chain-summary.csv"
    json_destination = root / "chain-summary.json"
    csv_temporary, row_count = _write_chain_csv(csv_destination, segments)
    try:
        summary = _chain_summary(segments)
        if row_count != summary["selected_pairs"]:
            raise RuntimeError("sealed receipts changed during chain publication")
        published = {
            **summary,
            "schema_version": CHAIN_REPORT_SCHEMA_VERSION,
            "chain_summary_csv": {
                "path": csv_destination.name,
                "rows": row_count,
                "sha256": _sha256_file(csv_temporary),
            },
        }
        json_temporary = _write_temporary(
            json_destination, _pretty_json(published)
        )
    except BaseException:
        csv_temporary.unlink(missing_ok=True)
        raise
    try:
        _replace_derived_file(csv_temporary, csv_destination)
        _replace_derived_file(json_temporary, json_destination)
    finally:
        csv_temporary.unlink(missing_ok=True)
        json_temporary.unlink(missing_ok=True)
    return published


def _verify_completed_segment(segment: AnalysisSegment) -> None:
    policy = _retention_policy(segment.analysis_root)
    plan = prepare_verified_resume(
        segment.analysis_root,
        build_pair_work_items(segment.manifest),
        retention_policy=policy,
    )
    if next(plan.remaining_work_items, None) is not None:
        raise ValueError(f"analysis segment is not complete: {segment.analysis_root}")
    expected = len(segment.manifest.commits) - 1
    if plan.prefix.next_sequence != expected:
        raise ValueError(f"analysis segment is not complete: {segment.analysis_root}")


def _retention_policy(analysis_root: Path) -> RetentionPolicy:
    receipts = _sealed_receipts(analysis_root)
    try:
        _, first = next(receipts)
    except StopIteration as error:
        raise ValueError(
            f"analysis segment has no sealed receipts: {analysis_root}"
        ) from error
    record = first.get("retention_policy")
    if not isinstance(record, dict):
        raise ValueError(f"analysis segment retention policy drift: {analysis_root}")
    for retain_positive_xml in (False, True):
        policy = RetentionPolicy(retain_positive_xml=retain_positive_xml)
        if record == policy.record():
            return policy
    raise ValueError(f"analysis segment retention policy drift: {analysis_root}")


def _verify_segment_compatibility(
    older: FrozenAnalysisManifest, newer: FrozenAnalysisManifest
) -> None:
    if older.repository_identity != newer.repository_identity:
        raise ValueError("repository identity drift across analysis continuation")
    if older.configuration != newer.configuration:
        raise ValueError("configuration drift across analysis continuation")
    if older.schema_versions != newer.schema_versions:
        raise ValueError("contract schema drift across analysis continuation")
    for name, left, right in (
        ("srcDiff", older.srcdiff, newer.srcdiff),
        ("srcMove", older.srcmove, newer.srcmove),
    ):
        if (left.size_bytes, left.sha256) != (right.size_bytes, right.sha256):
            raise ValueError(f"{name} executable drift across analysis continuation")


def _chain_summary(segments: tuple[AnalysisSegment, ...]) -> dict[str, Any]:
    statuses: Counter[str] = Counter()
    timings: Counter[str] = Counter()
    totals = Counter()
    segment_records: list[dict[str, Any]] = []
    for index, segment in enumerate(segments):
        summary = derive_history_summary(segment.analysis_root)
        statuses.update(summary["statuses"])
        timings.update(summary["timings"])
        for name in (
            "selected_pairs",
            "completed",
            "no_analyzable_change",
            "failed",
            "move_count",
            "move_group_count",
            "move_pair_count",
            "annotated_region_count",
        ):
            totals[name] += summary[name]
        segment_records.append(
            {
                "segment_index": index,
                "analysis_root": str(segment.analysis_root),
                "manifest_sha256": segment.manifest_sha256,
                "oldest_commit": segment.manifest.commits[0],
                "newest_commit": segment.manifest.commits[-1],
                "selected_pairs": summary["selected_pairs"],
            }
        )
    return {
        **dict(totals),
        "failed": sum(statuses[status] for status in FAILURE_STATUSES),
        "statuses": dict(sorted(statuses.items())),
        "timings": dict(sorted(timings.items())),
        "segment_count": len(segments),
        "segments": segment_records,
    }


def _write_chain_csv(
    destination: Path, segments: tuple[AnalysisSegment, ...]
) -> tuple[Path, int]:
    temporary = destination.with_name(f".{destination.name}.tmp-{uuid.uuid4().hex}")
    count = 0
    try:
        with temporary.open("x", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(
                stream, fieldnames=CHAIN_SUMMARY_COLUMNS, lineterminator="\n"
            )
            writer.writeheader()
            for segment_index, segment in enumerate(segments):
                for receipt_path, receipt in _sealed_receipts(segment.analysis_root):
                    row = _summary_row(
                        segment.analysis_root, receipt_path, receipt
                    )
                    writer.writerow(
                        {
                            "chain_sequence": count,
                            "segment_index": segment_index,
                            "segment_sequence": receipt["sequence"],
                            "segment_analysis_root": str(segment.analysis_root),
                            **row,
                        }
                    )
                    count += 1
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return temporary, count


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            hasher.update(block)
    return hasher.hexdigest()
