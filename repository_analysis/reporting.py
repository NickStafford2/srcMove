"""Deterministic coordinator-owned publication for pair outcomes."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import uuid
from collections import Counter
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from .contracts import (
    CaptureObservation,
    PairOutcome,
    ProcessOutcome,
    VerifiedArtifact,
)
from .retention import (
    DEFAULT_RETENTION_POLICY,
    RetainedFile,
    RetentionPolicy,
    retain_outcome_files,
)


PAIR_RECEIPT_SCHEMA_VERSION = 2
HISTORY_SUMMARY_SCHEMA_VERSION = 1
HISTORY_REPORT_SCHEMA_VERSION = 2
_MOVE_COUNT_METRICS = (
    "move_count",
    "move_group_count",
    "move_pair_count",
    "annotated_region_count",
)
SUMMARY_COLUMNS = (
    "sequence",
    "old_commit",
    "new_commit",
    "pair_fingerprint",
    "status",
    "changed_paths",
    "analyzable_changed_paths",
    "move_count",
    "move_group_count",
    "move_pair_count",
    "annotated_region_count",
    "pair_seconds",
    "inventory_seconds",
    "materialization_seconds",
    "srcdiff_seconds",
    "srcmove_seconds",
    "results_validation_seconds",
    "error",
    "receipt_path",
)
FAILURE_STATUSES = {
    "export_failed",
    "srcdiff_failed",
    "srcmove_failed",
    "orchestration_failed",
}


def _artifact_record(artifact: VerifiedArtifact) -> dict[str, Any]:
    return {
        "path": str(artifact.path),
        "size_bytes": artifact.size_bytes,
        "sha256": artifact.sha256,
        "kind": artifact.kind,
        "validation_status": artifact.validation_status,
        "producing_stage": artifact.producing_stage,
        "producing_command": list(artifact.producing_command),
        "shape": artifact.shape,
        "details": dict(artifact.details),
        "retention": artifact.retention,
    }


def _capture_record(capture: CaptureObservation) -> dict[str, Any]:
    return {
        "path": None if capture.path is None else str(capture.path),
        "total_bytes": capture.total_bytes,
        "retained_bytes": capture.retained_bytes,
        "omitted_bytes": capture.omitted_bytes,
        "truncated": capture.truncated,
        "sha256": capture.sha256,
    }


def _process_record(process: ProcessOutcome | None) -> dict[str, Any] | None:
    if process is None:
        return None
    return {
        "command": list(process.command),
        "working_directory": str(process.working_directory),
        "started_at": process.started_at,
        "completed_at": process.completed_at,
        "elapsed_seconds": process.elapsed_seconds,
        "termination_status": process.termination_status,
        "exit_code": process.exit_code,
        "signal_number": process.signal_number,
        "timed_out": process.timed_out,
        "spawn_error": process.spawn_error,
        "cleanup_signals": list(process.cleanup_signals),
        "process_group_cleaned": process.process_group_cleaned,
        "stdout": _capture_record(process.stdout),
        "stderr": _capture_record(process.stderr),
        "peak_rss_bytes": process.peak_rss_bytes,
        "oom_kill_observed": process.oom_kill_observed,
        "output_artifact": (
            None
            if process.output_artifact is None
            else _artifact_record(process.output_artifact)
        ),
        "validation_error": process.validation_error,
        "admitted": process.admitted,
    }


def pair_receipt(outcome: PairOutcome) -> dict[str, Any]:
    """Return the versioned JSON value published for one immutable outcome."""

    item = outcome.work_item
    return {
        "schema_version": PAIR_RECEIPT_SCHEMA_VERSION,
        "sealed": False,
        "sequence": item.sequence,
        "old_commit": item.old_commit,
        "new_commit": item.new_commit,
        "pair_fingerprint": item.fingerprint,
        "status": outcome.status.value,
        "changed_paths": [
            {
                "status": change.status,
                "path": change.path,
                "old_mode": change.old_mode,
                "new_mode": change.new_mode,
                "old_blob": change.old_blob,
                "new_blob": change.new_blob,
            }
            for change in outcome.changed_paths
        ],
        "path_counts": {
            "changed": len(outcome.changed_paths),
            "analyzable": len(outcome.analyzable_paths),
        },
        "metrics": dict(outcome.metrics),
        "timings": dict(outcome.timings),
        "srcdiff_process": _process_record(outcome.srcdiff_process),
        "srcmove_process": _process_record(outcome.srcmove_process),
        "artifacts": [_artifact_record(artifact) for artifact in outcome.artifacts],
        "error": outcome.error,
    }


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _pretty_json(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _publish_new_file(path: Path, content: bytes) -> None:
    """Atomically create ``path`` without replacing an existing receipt."""

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


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _sealed_receipt(
    outcome: PairOutcome,
    retained_files: dict[Path, RetainedFile],
    policy: RetentionPolicy,
) -> dict[str, Any]:
    receipt = pair_receipt(outcome)
    receipt["sealed"] = True
    receipt["artifact_path_base"] = "analysis_root"
    receipt["retention_policy"] = policy.record()
    for artifact in receipt["artifacts"]:
        _seal_artifact_record(artifact, retained_files)
    for process_name in ("srcdiff_process", "srcmove_process"):
        process = receipt[process_name]
        if process is None:
            continue
        output_artifact = process["output_artifact"]
        if output_artifact is not None:
            _seal_artifact_record(output_artifact, retained_files)
        for stream_name in ("stdout", "stderr"):
            capture = process[stream_name]
            source = capture["path"]
            retained = (
                None
                if source is None
                else retained_files.get(Path(os.path.abspath(source)))
            )
            capture["path"] = (
                None if retained is None else str(retained.relative_path)
            )
            capture["retained_sha256"] = (
                None if retained is None else retained.sha256
            )
    _validate_completed_seal(receipt)
    return receipt


def _validate_completed_seal(receipt: Mapping[str, Any]) -> None:
    if receipt.get("status") != "completed":
        return
    metrics = _mapping(receipt, "metrics")
    for name in _MOVE_COUNT_METRICS:
        _count(metrics, name, required=True)
    artifacts = receipt.get("artifacts")
    if not isinstance(artifacts, list) or not all(
        isinstance(artifact, Mapping) for artifact in artifacts
    ):
        raise ValueError("completed receipt artifacts must be a list of objects")
    retained_results = [
        artifact
        for artifact in artifacts
        if artifact.get("kind") == "json_results"
        and artifact.get("validation_status") == "valid"
        and artifact.get("retention") == "analysis_owned"
        and isinstance(artifact.get("path"), str)
    ]
    if len(retained_results) != 1:
        raise ValueError(
            "completed receipt requires one retained valid results.json artifact"
        )
    policy = _mapping(receipt, "retention_policy")
    if (
        policy.get("completed_positive") == "results_and_xml"
        and _count(metrics, "move_count", required=True) > 0
    ):
        retained_xml_stages = [
            artifact.get("producing_stage")
            for artifact in artifacts
            if artifact.get("kind") == "xml"
            and artifact.get("validation_status") == "valid"
            and artifact.get("retention") == "analysis_owned"
            and isinstance(artifact.get("path"), str)
        ]
        if sorted(retained_xml_stages) != ["srcdiff", "srcmove"]:
            raise ValueError(
                "completed positive receipt requires retained valid srcDiff "
                "and srcMove XML artifacts"
            )


def _validate_completed_outcome(
    outcome: PairOutcome, policy: RetentionPolicy
) -> None:
    if outcome.status.value != "completed":
        return
    metrics = dict(outcome.metrics)
    for name in _MOVE_COUNT_METRICS:
        _count(metrics, name, required=True)
    results = [
        artifact
        for artifact in outcome.artifacts
        if artifact.kind == "json_results"
        and artifact.validation_status == "valid"
    ]
    if len(results) != 1:
        raise ValueError(
            "completed outcome requires one valid results.json artifact"
        )
    if policy.retain_positive_xml and _count(
        metrics, "move_count", required=True
    ) > 0:
        xml_stages = sorted(
            artifact.producing_stage
            for artifact in outcome.artifacts
            if artifact.kind == "xml" and artifact.validation_status == "valid"
        )
        if xml_stages != ["srcdiff", "srcmove"]:
            raise ValueError(
                "completed positive outcome requires valid srcDiff and srcMove "
                "XML artifacts"
            )


def _seal_artifact_record(
    artifact: dict[str, Any], retained_files: dict[Path, RetainedFile]
) -> None:
    source = Path(os.path.abspath(artifact["path"]))
    retained = retained_files.get(source)
    if retained is None:
        artifact["path"] = None
        artifact["retention"] = "not_retained"
        return
    artifact["path"] = str(retained.relative_path)
    artifact["retention"] = "analysis_owned"


class PairReceiptPublisher:
    """Publish ordered sealed receipts and their derived history reports."""

    def __init__(
        self,
        analysis_root: Path,
        *,
        retention_policy: RetentionPolicy = DEFAULT_RETENTION_POLICY,
    ) -> None:
        self.analysis_root = analysis_root.resolve()
        self.retention_policy = retention_policy
        self.pairs_directory = self.analysis_root / "pairs"
        self.pairs_directory.mkdir(parents=True, exist_ok=True)
        self._next_sequence = 0

    def __call__(self, outcome: PairOutcome) -> None:
        sequence = outcome.work_item.sequence
        if sequence != self._next_sequence:
            raise ValueError(
                "pair receipts must be published in contiguous sequence order; "
                f"expected {self._next_sequence}, got {sequence}"
            )
        destination = self.pairs_directory / f"{sequence:06d}.json"
        if destination.exists():
            raise FileExistsError(destination)
        _validate_completed_outcome(outcome, self.retention_policy)
        pair_directory = self.pairs_directory / f"{sequence:06d}"
        retained = retain_outcome_files(
            outcome,
            self.analysis_root,
            pair_directory,
            policy=self.retention_policy,
        )
        receipt = _sealed_receipt(
            outcome, retained.by_source(), self.retention_policy
        )
        _publish_new_file(destination, _canonical_json(receipt))
        self._next_sequence += 1

    def summary(self) -> dict[str, Any]:
        """Derive a deterministic aggregate from sealed receipts."""

        return derive_history_summary(self.analysis_root)

    def finalize(self) -> dict[str, Any]:
        """Atomically publish aggregate JSON and chronological CSV views."""

        return publish_history_reports(self.analysis_root)


def derive_history_summary(analysis_root: Path) -> dict[str, Any]:
    """Return a constant-size aggregate derived only from sealed receipts."""

    statuses: Counter[str] = Counter()
    timings: Counter[str] = Counter()
    move_count = 0
    move_group_count = 0
    move_pair_count = 0
    annotated_region_count = 0
    selected_pairs = 0
    for _, receipt in _sealed_receipts(analysis_root):
        selected_pairs += 1
        status = _receipt_status(receipt)
        statuses[status] += 1
        if status == "completed":
            metrics = _mapping(receipt, "metrics")
            move_count += _count(metrics, "move_count", required=True)
            move_group_count += _count(metrics, "move_group_count", required=True)
            move_pair_count += _count(metrics, "move_pair_count", required=True)
            annotated_region_count += _count(
                metrics, "annotated_region_count", required=True
            )
        for name, seconds in _mapping(receipt, "timings").items():
            if (
                isinstance(seconds, bool)
                or not isinstance(seconds, (int, float))
                or not math.isfinite(seconds)
                or seconds < 0
            ):
                raise ValueError(f"receipt timing {name!r} must be numeric")
            timings[str(name)] += float(seconds)
    return {
        "schema_version": HISTORY_SUMMARY_SCHEMA_VERSION,
        "selected_pairs": selected_pairs,
        "completed": statuses["completed"],
        "no_analyzable_change": statuses["no_analyzable_change"],
        "failed": sum(statuses[status] for status in FAILURE_STATUSES),
        "statuses": dict(sorted(statuses.items())),
        "move_count": move_count,
        "move_group_count": move_group_count,
        "move_pair_count": move_pair_count,
        "annotated_region_count": annotated_region_count,
        "timings": dict(sorted(timings.items())),
    }


def publish_history_reports(analysis_root: Path) -> dict[str, Any]:
    """Publish replaceable views after receipt publication has stopped.

    ``summary.csv`` is the initial human browse view. A positive-artifact link
    hierarchy can be added later without changing the sealed receipt source of
    truth.
    """

    root = analysis_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    summary = derive_history_summary(root)
    csv_destination = root / "summary.csv"
    json_destination = root / "summary.json"
    csv_temporary, csv_count = _write_summary_csv_temporary(root, csv_destination)
    try:
        if csv_count != summary["selected_pairs"]:
            raise RuntimeError("sealed receipts changed during report publication")
        published_summary = {
            **summary,
            "schema_version": HISTORY_REPORT_SCHEMA_VERSION,
            "summary_csv": {
                "path": csv_destination.relative_to(root).as_posix(),
                "rows": csv_count,
                "sha256": _sha256_file(csv_temporary),
            },
        }
        json_temporary = _write_temporary(
            json_destination, _pretty_json(published_summary)
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
    return published_summary


def _sealed_receipts(
    analysis_root: Path,
) -> Iterator[tuple[Path, dict[str, Any]]]:
    root = analysis_root.resolve()
    pairs_directory = root / "pairs"
    if not pairs_directory.exists():
        return
    if not pairs_directory.is_dir() or pairs_directory.is_symlink():
        raise ValueError(f"pair receipt path is not an owned directory: {pairs_directory}")
    sequence = 0
    while True:
        path = pairs_directory / f"{sequence:06d}.json"
        if not path.exists():
            break
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"pair receipt is not a regular file: {path}")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(f"pair receipt is unreadable: {path}") from error
        if not isinstance(value, dict):
            raise ValueError(f"pair receipt must contain a JSON object: {path}")
        if value.get("schema_version") != PAIR_RECEIPT_SCHEMA_VERSION:
            raise ValueError(f"unsupported pair receipt schema: {path}")
        if value.get("sealed") is not True:
            raise ValueError(f"pair receipt is not sealed: {path}")
        if value.get("sequence") != sequence:
            raise ValueError(
                f"pair receipt sequence mismatch: expected {sequence}, "
                f"got {value.get('sequence')}"
            )
        _validate_completed_seal(value)
        yield path, value
        sequence += 1
    _reject_later_or_malformed_receipts(pairs_directory, sequence)


def _reject_later_or_malformed_receipts(
    pairs_directory: Path, expected_sequence: int
) -> None:
    with os.scandir(pairs_directory) as entries:
        for entry in entries:
            if not entry.name.endswith(".json"):
                continue
            stem = entry.name.removesuffix(".json")
            if len(stem) != 6 or not stem.isdigit():
                raise ValueError(f"malformed pair receipt filename: {entry.name}")
            sequence = int(stem)
            if sequence >= expected_sequence:
                raise ValueError(
                    "pair receipts must be contiguous; "
                    f"missing {expected_sequence:06d}.json before {entry.name}"
                )


def _receipt_status(receipt: Mapping[str, Any]) -> str:
    status = receipt.get("status")
    allowed = {"completed", "no_analyzable_change", *FAILURE_STATUSES}
    if not isinstance(status, str) or status not in allowed:
        raise ValueError(f"sealed receipt has unknown status: {status!r}")
    return status


def _mapping(receipt: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = receipt.get(name, {})
    if not isinstance(value, Mapping):
        raise ValueError(f"receipt field {name!r} must be an object")
    return value


def _count(
    values: Mapping[str, Any], name: str, *, required: bool = False
) -> int:
    if required and name not in values:
        raise ValueError(f"completed receipt is missing metric {name!r}")
    value = values.get(name, 0)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"receipt metric {name!r} must be a non-negative integer")
    return value


def _write_summary_csv_temporary(
    analysis_root: Path, destination: Path
) -> tuple[Path, int]:
    temporary = destination.with_name(f".{destination.name}.tmp-{uuid.uuid4().hex}")
    count = 0
    try:
        with temporary.open("x", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(
                stream, fieldnames=SUMMARY_COLUMNS, lineterminator="\n"
            )
            writer.writeheader()
            for receipt_path, receipt in _sealed_receipts(analysis_root):
                writer.writerow(_summary_row(analysis_root, receipt_path, receipt))
                count += 1
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return temporary, count


def _summary_row(
    analysis_root: Path,
    receipt_path: Path,
    receipt: Mapping[str, Any],
) -> dict[str, Any]:
    metrics = _mapping(receipt, "metrics")
    timings = _mapping(receipt, "timings")
    path_counts = _mapping(receipt, "path_counts")
    return {
        "sequence": receipt["sequence"],
        "old_commit": _spreadsheet_safe(receipt.get("old_commit")),
        "new_commit": _spreadsheet_safe(receipt.get("new_commit")),
        "pair_fingerprint": _spreadsheet_safe(receipt.get("pair_fingerprint")),
        "status": _receipt_status(receipt),
        "changed_paths": path_counts.get("changed"),
        "analyzable_changed_paths": path_counts.get("analyzable"),
        "move_count": metrics.get("move_count"),
        "move_group_count": metrics.get("move_group_count"),
        "move_pair_count": metrics.get("move_pair_count"),
        "annotated_region_count": metrics.get("annotated_region_count"),
        "pair_seconds": timings.get("pair_seconds"),
        "inventory_seconds": timings.get("inventory_seconds"),
        "materialization_seconds": timings.get("materialization_seconds"),
        "srcdiff_seconds": timings.get("srcdiff_seconds"),
        "srcmove_seconds": timings.get("srcmove_seconds"),
        "results_validation_seconds": timings.get("results_validation_seconds"),
        "error": _spreadsheet_safe(receipt.get("error")),
        "receipt_path": receipt_path.relative_to(analysis_root).as_posix(),
    }


def _spreadsheet_safe(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    return f"'{value}" if value.startswith(("=", "+", "-", "@")) else value


def _write_temporary(destination: Path, content: bytes) -> Path:
    temporary = destination.with_name(f".{destination.name}.tmp-{uuid.uuid4().hex}")
    try:
        with temporary.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return temporary


def _replace_derived_file(temporary: Path, destination: Path) -> None:
    os.replace(temporary, destination)
    _fsync_directory(destination.parent)


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            hasher.update(block)
    return hasher.hexdigest()
