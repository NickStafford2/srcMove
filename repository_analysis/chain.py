"""Transactional growth of one logical repository analysis."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import stat
import uuid
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .inputs import (
    FrozenAnalysisManifest,
    build_pair_work_items,
    canonical_pretty_json_bytes,
    load_frozen_manifest,
    persist_frozen_manifest,
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


ANALYSIS_STATE_SCHEMA_VERSION = 1
ANALYSIS_STATE_REPORT_SCHEMA_VERSION = 3
PENDING_CONTINUATION_SCHEMA_VERSION = 1
CURRENT_STATE_NAME = "current.json"
PENDING_SEGMENT_PATH = PurePosixPath("pending/continuation")
STATE_SUMMARY_COLUMNS = (
    "sequence",
    "segment_index",
    "segment_sequence",
    "segment_path",
    *tuple(name for name in SUMMARY_COLUMNS if name != "sequence"),
)


@dataclass(frozen=True, slots=True)
class AnalysisSegment:
    relative_path: PurePosixPath
    manifest_sha256: str
    oldest_commit: str
    newest_commit: str
    pair_count: int

    def record(self) -> dict[str, Any]:
        return {
            "path": str(self.relative_path),
            "manifest_sha256": self.manifest_sha256,
            "oldest_commit": self.oldest_commit,
            "newest_commit": self.newest_commit,
            "pair_count": self.pair_count,
        }


@dataclass(frozen=True, slots=True)
class AnalysisState:
    generation: int
    commits: tuple[str, ...]
    segments: tuple[AnalysisSegment, ...]

    def record(self) -> dict[str, Any]:
        return {
            "schema_version": ANALYSIS_STATE_SCHEMA_VERSION,
            "generation": self.generation,
            "commits": list(self.commits),
            "segments": [segment.record() for segment in self.segments],
        }

    def canonical_bytes(self) -> bytes:
        return canonical_pretty_json_bytes(self.record())


@dataclass(frozen=True, slots=True)
class PendingContinuation:
    requested_pair_count: int
    base_state_sha256: str

    def record(self) -> dict[str, Any]:
        return {
            "schema_version": PENDING_CONTINUATION_SCHEMA_VERSION,
            "requested_pair_count": self.requested_pair_count,
            "base_state_sha256": self.base_state_sha256,
        }


def initialize_analysis_state(analysis_root: Path) -> AnalysisState:
    """Publish generation zero after the initial segment is complete."""

    root = analysis_root.expanduser().resolve()
    current_path = root / CURRENT_STATE_NAME
    if current_path.exists() or current_path.is_symlink():
        return load_verified_analysis_state(root)
    manifest = load_frozen_manifest(root)
    if manifest.continuation is not None:
        raise ValueError(
            "legacy multi-root continuation cannot initialize a single-root state"
        )
    segment = _segment_record(PurePosixPath("."), manifest)
    _verify_completed_segment(root, manifest)
    state = AnalysisState(0, manifest.commits, (segment,))
    _publish_new_file(current_path, state.canonical_bytes())
    return state


def load_verified_analysis_state(analysis_root: Path) -> AnalysisState:
    """Strictly load the authoritative generation and all immutable segments."""

    root = analysis_root.expanduser().resolve()
    path = root / CURRENT_STATE_NAME
    record = _load_canonical_json(path)
    _exact_fields(
        record,
        {"schema_version", "generation", "commits", "segments"},
        "state",
    )
    _exact_version(record, "schema_version", ANALYSIS_STATE_SCHEMA_VERSION)
    generation = _nonnegative_integer(record["generation"], "generation")
    commits = _string_tuple(record["commits"], "commits")
    segment_values = record["segments"]
    if not isinstance(segment_values, list) or not segment_values:
        raise ValueError("state segments must be a non-empty array")
    segments = tuple(
        _load_segment(value, index) for index, value in enumerate(segment_values)
    )
    state = AnalysisState(generation, commits, segments)
    if path.read_bytes() != state.canonical_bytes():
        raise ValueError("analysis state is not canonically encoded")
    if generation != len(segments) - 1:
        raise ValueError("analysis state generation does not match segment count")
    _verify_state_segments(root, state)
    return state


def load_oldest_segment(
    analysis_root: Path, state: AnalysisState
) -> tuple[Path, FrozenAnalysisManifest]:
    """Return the current oldest immutable segment after state verification."""

    root = analysis_root.expanduser().resolve()
    segment_root = _segment_root(root, state.segments[0].relative_path)
    return segment_root, load_frozen_manifest(segment_root)


def oldest_segment_retention_policy(
    analysis_root: Path, state: AnalysisState
) -> RetentionPolicy:
    """Return the retention policy inherited by a continuation."""

    root = analysis_root.expanduser().resolve()
    segment_root = _segment_root(root, state.segments[0].relative_path)
    return _retention_policy(segment_root)


def create_pending_continuation(
    analysis_root: Path,
    manifest: FrozenAnalysisManifest,
    *,
    requested_pair_count: int,
    base_state: AnalysisState,
) -> Path:
    """Atomically prepare one durable but non-current continuation segment."""

    root = analysis_root.expanduser().resolve()
    pending_parent = root / PENDING_SEGMENT_PATH.parent
    pending_parent.mkdir(exist_ok=True)
    if pending_parent.is_symlink() or not pending_parent.is_dir():
        raise ValueError(f"pending path is not an owned directory: {pending_parent}")
    pending_root = root / PENDING_SEGMENT_PATH
    if pending_root.exists() or pending_root.is_symlink():
        raise ValueError(f"a continuation is already pending: {pending_root}")
    temporary = pending_parent / f".prepare-{uuid.uuid4().hex}"
    temporary.mkdir()
    request = PendingContinuation(
        requested_pair_count=requested_pair_count,
        base_state_sha256=_state_sha256(base_state),
    )
    try:
        persist_frozen_manifest(temporary, manifest)
        _publish_new_file(
            temporary / "request.json",
            canonical_pretty_json_bytes(request.record()),
        )
        os.rename(temporary, pending_root)
        _fsync_directory(pending_parent)
    finally:
        try:
            temporary.rmdir()
        except OSError:
            pass
    return pending_root


def load_pending_continuation(
    analysis_root: Path, state: AnalysisState, requested_pair_count: int
) -> tuple[Path, FrozenAnalysisManifest] | None:
    """Load a resumable pending segment and bind it to the current generation."""

    root = analysis_root.expanduser().resolve()
    pending_root = root / PENDING_SEGMENT_PATH
    if pending_root.is_symlink():
        raise ValueError(
            f"pending continuation is not an owned directory: {pending_root}"
        )
    if not pending_root.exists():
        return None
    if not pending_root.is_dir():
        raise ValueError(
            f"pending continuation is not an owned directory: {pending_root}"
        )
    request = _load_pending_request(pending_root / "request.json")
    if request.requested_pair_count != requested_pair_count:
        raise ValueError(
            "pending continuation count differs from the requested count; "
            f"expected {request.requested_pair_count}"
        )
    if request.base_state_sha256 != _state_sha256(state):
        raise ValueError("pending continuation base state drift")
    manifest = load_frozen_manifest(pending_root)
    _verify_new_segment_link(root, state, manifest)
    return pending_root, manifest


def reconcile_promoted_continuation(
    analysis_root: Path, state: AnalysisState
) -> tuple[AnalysisState, dict[str, Any]] | None:
    """Publish an orphaned complete segment left between rename and state commit."""

    root = analysis_root.expanduser().resolve()
    destination = root / "segments" / f"{state.generation + 1:06d}"
    if destination.is_symlink():
        raise ValueError(f"promoted segment is not an owned directory: {destination}")
    if not destination.exists():
        return None
    if not destination.is_dir():
        raise ValueError(f"promoted segment is not an owned directory: {destination}")
    request = _load_pending_request(destination / "request.json")
    if request.base_state_sha256 != _state_sha256(state):
        raise ValueError("promoted continuation base state drift")
    manifest = load_frozen_manifest(destination)
    _verify_new_segment_link(root, state, manifest)
    _verify_completed_segment(destination, manifest)
    return publish_promoted_continuation(root, state, destination, manifest)


def promote_pending_continuation(
    analysis_root: Path,
    state: AnalysisState,
    pending_root: Path,
    manifest: FrozenAnalysisManifest,
) -> tuple[AnalysisState, dict[str, Any]]:
    """Promote a verified pending segment and atomically publish the new state."""

    root = analysis_root.expanduser().resolve()
    expected_pending = root / PENDING_SEGMENT_PATH
    if pending_root.resolve() != expected_pending.resolve():
        raise ValueError("pending continuation path drift")
    _verify_completed_segment(pending_root, manifest)
    segments_root = root / "segments"
    segments_root.mkdir(exist_ok=True)
    if segments_root.is_symlink() or not segments_root.is_dir():
        raise ValueError(f"segments path is not an owned directory: {segments_root}")
    destination = segments_root / f"{state.generation + 1:06d}"
    if destination.exists() or destination.is_symlink():
        raise ValueError(f"continuation segment already exists: {destination}")
    os.rename(pending_root, destination)
    _fsync_directory(segments_root)
    _fsync_directory(expected_pending.parent)
    return publish_promoted_continuation(root, state, destination, manifest)


def publish_promoted_continuation(
    analysis_root: Path,
    state: AnalysisState,
    segment_root: Path,
    manifest: FrozenAnalysisManifest,
) -> tuple[AnalysisState, dict[str, Any]]:
    """Publish derived views, then commit one new authoritative generation."""

    root = analysis_root.resolve()
    relative = PurePosixPath(segment_root.relative_to(root).as_posix())
    segment = _segment_record(relative, manifest)
    combined_commits = (*manifest.commits[:-1], *state.commits)
    next_state = AnalysisState(
        generation=state.generation + 1,
        commits=combined_commits,
        segments=(segment, *state.segments),
    )
    _verify_state_segments(root, next_state)
    summary = publish_analysis_state_reports(root, next_state)
    _replace_current_state(root / CURRENT_STATE_NAME, next_state.canonical_bytes())
    return next_state, summary


def publish_analysis_state_reports(
    analysis_root: Path, state: AnalysisState
) -> dict[str, Any]:
    """Publish the current logical analysis as chronological JSON and CSV."""

    root = analysis_root.resolve()
    csv_destination = root / "summary.csv"
    json_destination = root / "summary.json"
    csv_temporary, row_count = _write_state_csv(root, csv_destination, state)
    try:
        summary = _state_summary(root, state)
        if row_count != summary["selected_pairs"]:
            raise RuntimeError("sealed receipts changed during state publication")
        published = {
            **summary,
            "schema_version": ANALYSIS_STATE_REPORT_SCHEMA_VERSION,
            "state_generation": state.generation,
            "state_sha256": _state_sha256(state),
            "summary_csv": {
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


def _verify_state_segments(root: Path, state: AnalysisState) -> None:
    manifests: list[FrozenAnalysisManifest] = []
    for index, segment in enumerate(state.segments):
        segment_root = _segment_root(root, segment.relative_path)
        manifest = load_frozen_manifest(segment_root)
        checksum = hashlib.sha256(manifest.canonical_bytes()).hexdigest()
        if checksum != segment.manifest_sha256:
            raise ValueError(f"segment manifest checksum drift at index {index}")
        if segment != _segment_record(segment.relative_path, manifest):
            raise ValueError(f"segment state metadata drift at index {index}")
        _verify_completed_segment(segment_root, manifest)
        manifests.append(manifest)
    for older, newer in zip(manifests, manifests[1:]):
        if older.commits[-1] != newer.commits[0]:
            raise ValueError("analysis segment boundary drift")
        _verify_segment_compatibility(older, newer)
    combined = tuple(manifests[0].commits)
    for newer in manifests[1:]:
        combined = (*combined[:-1], *newer.commits)
    if combined != state.commits:
        raise ValueError("analysis state commit sequence drift")


def _verify_new_segment_link(
    root: Path, state: AnalysisState, manifest: FrozenAnalysisManifest
) -> None:
    newer_root = _segment_root(root, state.segments[0].relative_path)
    newer = load_frozen_manifest(newer_root)
    continuation = manifest.continuation
    if continuation is None:
        raise ValueError("continuation segment is missing its immutable link")
    if continuation.newer_segment_path != state.segments[0].relative_path:
        raise ValueError("continuation newer segment path drift")
    newer_checksum = hashlib.sha256(newer.canonical_bytes()).hexdigest()
    if continuation.newer_manifest_sha256 != newer_checksum:
        raise ValueError("continuation newer manifest checksum drift")
    if manifest.commits[-1] != continuation.boundary_commit:
        raise ValueError("continuation older boundary drift")
    if newer.commits[0] != continuation.boundary_commit:
        raise ValueError("continuation newer boundary drift")
    _verify_segment_compatibility(manifest, newer)


def _verify_completed_segment(root: Path, manifest: FrozenAnalysisManifest) -> None:
    policy = _retention_policy(root)
    plan = prepare_verified_resume(
        root, build_pair_work_items(manifest), retention_policy=policy
    )
    if next(plan.remaining_work_items, None) is not None:
        raise ValueError(f"analysis segment is not complete: {root}")
    if plan.prefix.next_sequence != len(manifest.commits) - 1:
        raise ValueError(f"analysis segment is not complete: {root}")


def _retention_policy(segment_root: Path) -> RetentionPolicy:
    receipts = _sealed_receipts(segment_root)
    try:
        _, first = next(receipts)
    except StopIteration as error:
        raise ValueError(
            f"analysis segment has no sealed receipts: {segment_root}"
        ) from error
    record = first.get("retention_policy")
    for retain_positive_xml in (False, True):
        policy = RetentionPolicy(retain_positive_xml=retain_positive_xml)
        if record == policy.record():
            return policy
    raise ValueError(f"analysis segment retention policy drift: {segment_root}")


def _verify_segment_compatibility(
    older: FrozenAnalysisManifest, newer: FrozenAnalysisManifest
) -> None:
    if older.repository_identity != newer.repository_identity:
        raise ValueError("repository identity drift across analysis segments")
    if older.configuration != newer.configuration:
        raise ValueError("configuration drift across analysis segments")
    if older.schema_versions != newer.schema_versions:
        raise ValueError("contract schema drift across analysis segments")
    for name, left, right in (
        ("srcDiff", older.srcdiff, newer.srcdiff),
        ("srcMove", older.srcmove, newer.srcmove),
    ):
        if (left.size_bytes, left.sha256) != (right.size_bytes, right.sha256):
            raise ValueError(f"{name} executable drift across analysis segments")


def _state_summary(root: Path, state: AnalysisState) -> dict[str, Any]:
    statuses: Counter[str] = Counter()
    timings: Counter[str] = Counter()
    totals: Counter[str] = Counter()
    segment_records: list[dict[str, Any]] = []
    for index, segment in enumerate(state.segments):
        segment_root = _segment_root(root, segment.relative_path)
        summary = derive_history_summary(segment_root)
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
        segment_records.append({"segment_index": index, **segment.record()})
    return {
        **dict(totals),
        "failed": sum(statuses[status] for status in FAILURE_STATUSES),
        "statuses": dict(sorted(statuses.items())),
        "timings": dict(sorted(timings.items())),
        "segment_count": len(state.segments),
        "segments": segment_records,
    }


def _write_state_csv(
    root: Path, destination: Path, state: AnalysisState
) -> tuple[Path, int]:
    temporary = destination.with_name(f".{destination.name}.tmp-{uuid.uuid4().hex}")
    count = 0
    try:
        with temporary.open("x", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(
                stream, fieldnames=STATE_SUMMARY_COLUMNS, lineterminator="\n"
            )
            writer.writeheader()
            for segment_index, segment in enumerate(state.segments):
                segment_root = _segment_root(root, segment.relative_path)
                for receipt_path, receipt in _sealed_receipts(segment_root):
                    row = _summary_row(segment_root, receipt_path, receipt)
                    row["receipt_path"] = str(
                        segment.relative_path / row["receipt_path"]
                    )
                    writer.writerow(
                        {
                            "sequence": count,
                            "segment_index": segment_index,
                            "segment_sequence": receipt["sequence"],
                            "segment_path": str(segment.relative_path),
                            **{
                                key: value
                                for key, value in row.items()
                                if key != "sequence"
                            },
                        }
                    )
                    count += 1
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return temporary, count


def _segment_record(
    relative_path: PurePosixPath, manifest: FrozenAnalysisManifest
) -> AnalysisSegment:
    return AnalysisSegment(
        relative_path=relative_path,
        manifest_sha256=hashlib.sha256(manifest.canonical_bytes()).hexdigest(),
        oldest_commit=manifest.commits[0],
        newest_commit=manifest.commits[-1],
        pair_count=len(manifest.commits) - 1,
    )


def _segment_root(root: Path, relative: PurePosixPath) -> Path:
    if relative == PurePosixPath("."):
        return root
    path = root.joinpath(*relative.parts)
    if path.is_symlink() or not path.is_dir():
        raise ValueError(f"analysis segment is not an owned directory: {path}")
    return path


def _load_segment(value: Any, index: int) -> AnalysisSegment:
    record = _object(value, f"segments[{index}]")
    _exact_fields(
        record,
        {"path", "manifest_sha256", "oldest_commit", "newest_commit", "pair_count"},
        f"segments[{index}]",
    )
    path_value = _string(record["path"], f"segments[{index}].path")
    relative = PurePosixPath(path_value)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or str(relative) != path_value
    ):
        raise ValueError(f"segments[{index}].path must be canonical and relative")
    checksum = _sha256(
        record["manifest_sha256"], f"segments[{index}].manifest_sha256"
    )
    return AnalysisSegment(
        relative_path=relative,
        manifest_sha256=checksum,
        oldest_commit=_string(record["oldest_commit"], "oldest_commit"),
        newest_commit=_string(record["newest_commit"], "newest_commit"),
        pair_count=_nonnegative_integer(record["pair_count"], "pair_count"),
    )


def _load_pending_request(path: Path) -> PendingContinuation:
    record = _load_canonical_json(path)
    _exact_fields(
        record,
        {"schema_version", "requested_pair_count", "base_state_sha256"},
        "pending continuation",
    )
    _exact_version(record, "schema_version", PENDING_CONTINUATION_SCHEMA_VERSION)
    request = PendingContinuation(
        requested_pair_count=_positive_integer(
            record["requested_pair_count"], "requested_pair_count"
        ),
        base_state_sha256=_sha256(
            record["base_state_sha256"], "base_state_sha256"
        ),
    )
    if path.read_bytes() != canonical_pretty_json_bytes(request.record()):
        raise ValueError("pending continuation request is not canonically encoded")
    return request


def _load_canonical_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"analysis state file is not a regular file: {path}")
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"analysis state file is unreadable: {path}") from error
    return _object(value, str(path))


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def _object(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be an object")
    return value


def _exact_fields(record: dict[str, Any], expected: set[str], context: str) -> None:
    if set(record) != expected:
        raise ValueError(f"{context} fields do not match schema")


def _exact_version(record: dict[str, Any], field: str, expected: int) -> None:
    value = record[field]
    if isinstance(value, bool) or not isinstance(value, int) or value != expected:
        raise ValueError(f"unsupported {field}: {value!r}")


def _string(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value or "\0" in value:
        raise ValueError(f"{context} must be a non-empty string")
    return value


def _string_tuple(value: Any, context: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{context} must be an array")
    result = tuple(
        _string(item, f"{context}[{index}]")
        for index, item in enumerate(value)
    )
    if len(result) < 2 or len(set(result)) != len(result):
        raise ValueError(f"{context} must contain unique adjacent history commits")
    return result


def _nonnegative_integer(value: Any, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{context} must be a non-negative integer")
    return value


def _positive_integer(value: Any, context: str) -> int:
    result = _nonnegative_integer(value, context)
    if result == 0:
        raise ValueError(f"{context} must be positive")
    return result


def _sha256(value: Any, context: str) -> str:
    text = _string(value, context)
    if len(text) != 64 or any(
        character not in "0123456789abcdef" for character in text
    ):
        raise ValueError(f"{context} must be 64 lowercase hexadecimal digits")
    return text


def _state_sha256(state: AnalysisState) -> str:
    return hashlib.sha256(state.canonical_bytes()).hexdigest()


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            hasher.update(block)
    return hasher.hexdigest()


def _publish_new_file(path: Path, content: bytes) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        with temporary.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _replace_current_state(path: Path, content: bytes) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        with temporary.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode):
            raise ValueError(f"not a directory: {directory}")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
