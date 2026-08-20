"""Strict verification and continuation of sealed repository analyses."""

from __future__ import annotations

import hashlib
import os
import stat
import uuid
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .contracts import PairWorkItem
from .coordinator import CoordinatorStats, PairAcknowledger, PairExecutor
from .coordinator import _run_pairs_from_sequence
from .reporting import PairReceiptPublisher, _receipt_status, _sealed_receipts
from .retention import DEFAULT_RETENTION_POLICY, RetentionPolicy


@dataclass(frozen=True, slots=True)
class _VerifiedReceiptPrefix:
    """Proof that receipts before ``next_sequence`` match frozen work."""

    analysis_root: Path
    next_sequence: int
    retention_policy: tuple[tuple[str, object], ...]


@dataclass(frozen=True, slots=True)
class VerifiedResumePlan:
    """A verified immutable prefix and the unconsumed requested work."""

    prefix: _VerifiedReceiptPrefix
    remaining_work_items: Iterator[PairWorkItem]


@dataclass(frozen=True, slots=True)
class ResumeStats:
    """Observations from verification, new execution, and report rebuild."""

    verified_count: int
    execution: CoordinatorStats
    summary: dict[str, Any]


def prepare_verified_resume(
    analysis_root: Path,
    work_items: Iterable[PairWorkItem],
    *,
    retention_policy: RetentionPolicy = DEFAULT_RETENTION_POLICY,
) -> VerifiedResumePlan:
    """Verify the contiguous sealed prefix against frozen requested work."""

    root = analysis_root.resolve()
    requested = iter(work_items)
    expected_policy = retention_policy.record()
    verified_count = 0
    for receipt_path, receipt in _sealed_receipts(root):
        try:
            item = next(requested)
        except StopIteration as error:
            raise ValueError(
                f"sealed receipt has no requested work item: {receipt_path}"
            ) from error
        _verify_work_identity(receipt, item, verified_count, receipt_path)
        _verify_receipt(root, receipt, expected_policy, receipt_path)
        verified_count += 1
    return VerifiedResumePlan(
        prefix=_VerifiedReceiptPrefix(
            root, verified_count, tuple(sorted(expected_policy.items()))
        ),
        remaining_work_items=requested,
    )


def resume_pairs(
    work_items: Iterable[PairWorkItem],
    execute_pair: PairExecutor,
    *,
    analysis_root: Path,
    worker_count: int,
    work_queue_capacity: int | None = None,
    outcome_capacity: int | None = None,
    acknowledge_pair: PairAcknowledger | None = None,
    retention_policy: RetentionPolicy = DEFAULT_RETENTION_POLICY,
) -> ResumeStats:
    """Verify existing receipts, execute only the suffix, and rebuild reports."""

    plan = prepare_verified_resume(
        analysis_root, work_items, retention_policy=retention_policy
    )
    publisher = PairReceiptPublisher(
        analysis_root, retention_policy=retention_policy
    )
    publisher._next_sequence = plan.prefix.next_sequence
    execution = _run_pairs_from_sequence(
        _preserve_unsealed_pair_evidence(
            plan.remaining_work_items,
            plan.prefix.analysis_root,
            plan.prefix.next_sequence,
        ),
        execute_pair,
        publisher,
        worker_count=worker_count,
        first_sequence=plan.prefix.next_sequence,
        work_queue_capacity=work_queue_capacity,
        outcome_capacity=outcome_capacity,
        acknowledge_pair=acknowledge_pair,
    )
    summary = publisher.finalize()
    return ResumeStats(plan.prefix.next_sequence, execution, summary)


def _verify_work_identity(
    receipt: Mapping[str, Any],
    item: PairWorkItem,
    expected_sequence: int,
    receipt_path: Path,
) -> None:
    if item.sequence != expected_sequence:
        raise ValueError(
            "requested pair sequences must be contiguous and start at zero; "
            f"expected {expected_sequence}, got {item.sequence}"
        )
    expected = {
        "sequence": item.sequence,
        "old_commit": item.old_commit,
        "new_commit": item.new_commit,
        "pair_fingerprint": item.fingerprint,
    }
    for field, value in expected.items():
        if receipt.get(field) != value:
            raise ValueError(
                f"sealed receipt {field} drift at {receipt_path}: "
                f"expected {value!r}, got {receipt.get(field)!r}"
            )


def _verify_receipt(
    root: Path,
    receipt: Mapping[str, Any],
    expected_policy: Mapping[str, object],
    receipt_path: Path,
) -> None:
    status = _receipt_status(receipt)
    if receipt.get("artifact_path_base") != "analysis_root":
        raise ValueError(f"sealed receipt artifact path schema drift: {receipt_path}")
    if receipt.get("retention_policy") != expected_policy:
        raise ValueError(f"sealed receipt retention policy drift: {receipt_path}")

    artifacts = receipt.get("artifacts")
    if not isinstance(artifacts, list) or not all(
        isinstance(artifact, Mapping) for artifact in artifacts
    ):
        raise ValueError(f"sealed receipt artifacts schema drift: {receipt_path}")
    metrics = receipt.get("metrics")
    if not isinstance(metrics, Mapping):
        raise ValueError(f"sealed receipt metrics schema drift: {receipt_path}")
    move_count = metrics.get("move_count", 0)
    for index, artifact in enumerate(artifacts):
        required = _artifact_required(
            status, artifact, expected_policy, move_count=move_count
        )
        _verify_artifact_record(
            root,
            artifact,
            required=required,
            context=f"{receipt_path}: artifacts[{index}]",
        )

    for process_name in ("srcdiff_process", "srcmove_process"):
        process = receipt.get(process_name)
        if process is None:
            continue
        if not isinstance(process, Mapping):
            raise ValueError(
                f"sealed receipt {process_name} schema drift: {receipt_path}"
            )
        output = process.get("output_artifact")
        if output is not None:
            if not isinstance(output, Mapping):
                raise ValueError(
                    f"sealed receipt {process_name} artifact schema drift: "
                    f"{receipt_path}"
                )
            required = _artifact_required(
                status, output, expected_policy, move_count=move_count
            )
            _verify_artifact_record(
                root,
                output,
                required=required,
                context=f"{receipt_path}: {process_name}.output_artifact",
            )
        for stream_name in ("stdout", "stderr"):
            capture = process.get(stream_name)
            if not isinstance(capture, Mapping):
                raise ValueError(
                    f"sealed receipt {process_name}.{stream_name} schema drift: "
                    f"{receipt_path}"
                )
            _verify_capture_record(
                root,
                capture,
                retained_by_policy=status.endswith("_failed"),
                context=f"{receipt_path}: {process_name}.{stream_name}",
            )


def _artifact_required(
    status: str,
    artifact: Mapping[str, Any],
    policy: Mapping[str, object],
    *,
    move_count: Any,
) -> bool:
    if status.endswith("_failed"):
        return (
            artifact.get("kind") != "git_blob"
            and artifact.get("producing_stage") in {"srcdiff", "srcmove"}
        )
    if status != "completed":
        return False
    if artifact.get("kind") == "json_results":
        return True
    return (
        policy.get("completed_positive") == "results_and_xml"
        and isinstance(move_count, int)
        and not isinstance(move_count, bool)
        and move_count > 0
        and artifact.get("kind") == "xml"
    )


def _verify_artifact_record(
    root: Path,
    artifact: Mapping[str, Any],
    *,
    required: bool,
    context: str,
) -> None:
    retention = artifact.get("retention")
    path = artifact.get("path")
    if required:
        if retention != "analysis_owned" or not isinstance(path, str):
            raise ValueError(f"required retained artifact is missing: {context}")
    elif retention != "not_retained" or path is not None:
        raise ValueError(f"unexpected retained artifact: {context}")
    if path is not None:
        _verify_file(
            root,
            path,
            artifact.get("size_bytes"),
            artifact.get("sha256"),
            context,
        )


def _verify_capture_record(
    root: Path,
    capture: Mapping[str, Any],
    *,
    retained_by_policy: bool,
    context: str,
) -> None:
    path = capture.get("path")
    checksum = capture.get("retained_sha256")
    total_bytes = capture.get("total_bytes")
    retained_bytes = capture.get("retained_bytes")
    omitted_bytes = capture.get("omitted_bytes")
    truncated = capture.get("truncated")
    stream_sha256 = capture.get("sha256")
    for name, value in (
        ("total_bytes", total_bytes),
        ("retained_bytes", retained_bytes),
        ("omitted_bytes", omitted_bytes),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"capture {name} schema drift: {context}")
    if (
        retained_bytes > total_bytes
        or omitted_bytes != total_bytes - retained_bytes
        or not isinstance(truncated, bool)
        or truncated != (retained_bytes < total_bytes)
    ):
        raise ValueError(f"capture accounting schema drift: {context}")
    if (
        not isinstance(stream_sha256, str)
        or len(stream_sha256) != 64
        or any(
            character not in "0123456789abcdef" for character in stream_sha256
        )
    ):
        raise ValueError(f"capture SHA-256 schema drift: {context}")
    if retained_by_policy and total_bytes > 0 and retained_bytes == 0:
        raise ValueError(f"required retained capture is missing: {context}")
    required = retained_by_policy and total_bytes > 0
    if required:
        if not isinstance(path, str) or not isinstance(checksum, str):
            raise ValueError(f"required retained capture is missing: {context}")
    elif path is not None or checksum is not None:
        raise ValueError(f"unexpected retained capture: {context}")
    if path is not None:
        _verify_file(root, path, retained_bytes, checksum, context)


def _preserve_unsealed_pair_evidence(
    work_items: Iterator[PairWorkItem], root: Path, first_sequence: int
) -> Iterator[PairWorkItem]:
    """Move an interrupted durable pair directory aside before retrying it."""

    first = True
    for item in work_items:
        if first:
            if item.sequence != first_sequence:
                raise ValueError(
                    "pair sequences must be contiguous from the verified starting "
                    f"sequence; expected {first_sequence}, got {item.sequence}"
                )
            _preserve_pair_directory(root, first_sequence)
            first = False
        yield item


def _preserve_pair_directory(root: Path, sequence: int) -> None:
    source = root / "pairs" / f"{sequence:06d}"
    try:
        metadata = source.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError(f"unsealed pair evidence is not an owned directory: {source}")
    evidence_root = root / "unsealed-pairs"
    if evidence_root.exists():
        evidence_metadata = evidence_root.lstat()
        if stat.S_ISLNK(evidence_metadata.st_mode) or not stat.S_ISDIR(
            evidence_metadata.st_mode
        ):
            raise ValueError(
                f"unsealed evidence path is not an owned directory: {evidence_root}"
            )
    else:
        evidence_root.mkdir()
        _fsync_directory(root)
    destination = evidence_root / f"pair-{sequence:06d}-{uuid.uuid4().hex}"
    os.rename(source, destination)
    _fsync_directory(source.parent)
    _fsync_directory(evidence_root)


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _verify_file(
    root: Path,
    relative_path: str,
    expected_size: Any,
    expected_sha256: Any,
    context: str,
) -> None:
    relative = _safe_relative_path(relative_path, context)
    if (
        isinstance(expected_size, bool)
        or not isinstance(expected_size, int)
        or expected_size < 0
    ):
        raise ValueError(f"retained file size schema drift: {context}")
    if (
        not isinstance(expected_sha256, str)
        or len(expected_sha256) != 64
        or any(character not in "0123456789abcdef" for character in expected_sha256)
    ):
        raise ValueError(f"retained file SHA-256 schema drift: {context}")

    descriptor = _open_owned_file(root, relative, context)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError(f"retained path is not a regular file: {context}")
        if metadata.st_size != expected_size:
            raise ValueError(f"retained file size drift: {context}")
        hasher = hashlib.sha256()
        while block := os.read(descriptor, 1024 * 1024):
            hasher.update(block)
    finally:
        os.close(descriptor)
    if hasher.hexdigest() != expected_sha256:
        raise ValueError(f"retained file checksum drift: {context}")


def _open_owned_file(
    root: Path, relative: PurePosixPath, context: str
) -> int:
    """Open a retained file without following any path-component symlink."""

    directory_flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        directory_flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        directory_flags |= os.O_NOFOLLOW
    file_flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        file_flags |= os.O_NOFOLLOW

    descriptors: list[int] = []
    try:
        descriptors.append(os.open(root, directory_flags))
        for part in relative.parts[:-1]:
            descriptors.append(
                os.open(part, directory_flags, dir_fd=descriptors[-1])
            )
        descriptor = os.open(
            relative.parts[-1], file_flags, dir_fd=descriptors[-1]
        )
    except FileNotFoundError as error:
        raise ValueError(f"required retained file is missing: {context}") from error
    except OSError as error:
        raise ValueError(
            "retained path is not a regular file or contains a symbolic link: "
            f"{context}"
        ) from error
    finally:
        for directory_descriptor in reversed(descriptors):
            os.close(directory_descriptor)
    return descriptor


def _safe_relative_path(value: str, context: str) -> PurePosixPath:
    if not value or "\\" in value:
        raise ValueError(f"retained artifact path is not relative: {context}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError(f"retained artifact path is not relative: {context}")
    return path
