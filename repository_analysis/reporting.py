"""Deterministic coordinator-owned publication for pair outcomes."""

from __future__ import annotations

import json
import os
import uuid
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .contracts import (
    CaptureObservation,
    PairOutcome,
    ProcessOutcome,
    VerifiedArtifact,
)


PAIR_RECEIPT_SCHEMA_VERSION = 1
HISTORY_SUMMARY_SCHEMA_VERSION = 1
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


def _publish_new_file(path: Path, content: bytes) -> None:
    """Atomically create ``path`` without replacing an existing receipt."""

    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        with temporary.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class PairReceiptPublisher:
    """Publish ordered receipts and retain only constant-size summary state."""

    def __init__(self, analysis_root: Path) -> None:
        self.analysis_root = analysis_root.resolve()
        self.pairs_directory = self.analysis_root / "pairs"
        self.pairs_directory.mkdir(parents=True, exist_ok=True)
        self._next_sequence = 0
        self._statuses: Counter[str] = Counter()
        self._move_count = 0
        self._move_group_count = 0
        self._move_pair_count = 0
        self._annotated_region_count = 0
        self._timings: Counter[str] = Counter()

    def __call__(self, outcome: PairOutcome) -> None:
        sequence = outcome.work_item.sequence
        if sequence != self._next_sequence:
            raise ValueError(
                "pair receipts must be published in contiguous sequence order; "
                f"expected {self._next_sequence}, got {sequence}"
            )
        receipt = pair_receipt(outcome)
        destination = self.pairs_directory / f"{sequence:06d}.json"
        _publish_new_file(destination, _canonical_json(receipt))
        self._next_sequence += 1
        status = outcome.status.value
        self._statuses[status] += 1
        metrics = dict(outcome.metrics)
        if status == "completed":
            self._move_count += int(metrics.get("move_count", 0))
            self._move_group_count += int(metrics.get("move_group_count", 0))
            self._move_pair_count += int(metrics.get("move_pair_count", 0))
            self._annotated_region_count += int(
                metrics.get("annotated_region_count", 0)
            )
        for name, seconds in outcome.timings:
            self._timings[name] += seconds

    def summary(self) -> dict[str, Any]:
        """Return a deterministic aggregate of receipts published so far."""

        return {
            "schema_version": HISTORY_SUMMARY_SCHEMA_VERSION,
            "selected_pairs": self._next_sequence,
            "completed": self._statuses["completed"],
            "no_analyzable_change": self._statuses["no_analyzable_change"],
            "failed": sum(self._statuses[status] for status in FAILURE_STATUSES),
            "statuses": dict(sorted(self._statuses.items())),
            "move_count": self._move_count,
            "move_group_count": self._move_group_count,
            "move_pair_count": self._move_pair_count,
            "annotated_region_count": self._annotated_region_count,
            "timings": dict(sorted(self._timings.items())),
        }
