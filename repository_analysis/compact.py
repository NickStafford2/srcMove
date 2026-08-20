"""Compact durable observations derived from one terminal pair outcome."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import stat
from dataclasses import dataclass
from typing import Any

from .contracts import (
    COMPACT_PAIR_SCHEMA_VERSION,
    CaptureObservation,
    PairOutcome,
    ProcessOutcome,
)
from .inputs import canonical_json_bytes
from .results import normalize_compactable_results


COMPACT_FAILURE_LOG_LIMIT = 64 * 1024


@dataclass(frozen=True, slots=True)
class CompactMove:
    ordinal: int
    match_kind: str
    from_xpaths_json: bytes
    to_xpaths_json: bytes
    from_text_digests_json: bytes
    to_text_digests_json: bytes


@dataclass(frozen=True, slots=True)
class CompactPair:
    status: str
    changed_path_count: int
    analyzable_path_count: int
    metrics_json: bytes
    timings_json: bytes
    error: str | None
    evidence_json: bytes | None
    results_size_bytes: int | None
    results_sha256: str | None
    moves: tuple[CompactMove, ...]


def compact_pair_outcome(outcome: PairOutcome) -> CompactPair:
    """Preserve queryable move evidence without retaining raw source bodies."""

    status = outcome.status.value
    metrics = _metrics(outcome)
    timings = _timings(outcome)
    moves: tuple[CompactMove, ...] = ()
    results_size: int | None = None
    results_sha256: str | None = None
    if status == "completed":
        results = [
            artifact
            for artifact in outcome.artifacts
            if artifact.kind == "json_results"
            and artifact.validation_status == "valid"
        ]
        if len(results) != 1:
            raise ValueError("completed pair requires one valid results artifact")
        artifact = results[0]
        content = _read_verified_file(
            artifact.path, artifact.size_bytes, artifact.sha256, "srcMove results"
        )
        results_size = len(content)
        results_sha256 = artifact.sha256
        moves, nested_metrics = _compact_results(content, metrics)
        metrics.update(nested_metrics)
    evidence = (
        _failure_evidence(outcome) if status.endswith("_failed") else None
    )
    return CompactPair(
        status=status,
        changed_path_count=len(outcome.changed_paths),
        analyzable_path_count=len(outcome.analyzable_paths),
        metrics_json=canonical_json_bytes(metrics),
        timings_json=canonical_json_bytes(timings),
        error=outcome.error,
        evidence_json=(
            None if evidence is None else canonical_json_bytes(evidence)
        ),
        results_size_bytes=results_size,
        results_sha256=results_sha256,
        moves=moves,
    )


def _compact_results(
    content: bytes, scalar_metrics: dict[str, Any]
) -> tuple[tuple[CompactMove, ...], dict[str, Any]]:
    try:
        value = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("admitted srcMove results became unreadable") from error
    if not isinstance(value, dict):
        raise ValueError("admitted srcMove results must contain an object")
    moves, nested = normalize_compactable_results(value)
    if scalar_metrics.get("move_count") != len(moves):
        raise ValueError("srcMove results moves do not match the admitted move count")
    compact_moves = tuple(
        _compact_move(move, ordinal) for ordinal, move in enumerate(moves)
    )
    return compact_moves, nested


def _compact_move(value: Any, ordinal: int) -> CompactMove:
    if not isinstance(value, dict):
        raise ValueError(f"srcMove move {ordinal} must be an object")
    match_kind = value.get("match_kind")
    if not isinstance(match_kind, str) or not match_kind:
        raise ValueError(f"srcMove move {ordinal} has no match kind")
    from_xpaths = _string_array(value.get("from_xpaths"), "from_xpaths", ordinal)
    to_xpaths = _string_array(value.get("to_xpaths"), "to_xpaths", ordinal)
    from_texts = _string_array(
        value.get("from_raw_texts"), "from_raw_texts", ordinal
    )
    to_texts = _string_array(value.get("to_raw_texts"), "to_raw_texts", ordinal)
    return CompactMove(
        ordinal=ordinal,
        match_kind=match_kind,
        from_xpaths_json=canonical_json_bytes(from_xpaths),
        to_xpaths_json=canonical_json_bytes(to_xpaths),
        from_text_digests_json=canonical_json_bytes(_text_digests(from_texts)),
        to_text_digests_json=canonical_json_bytes(_text_digests(to_texts)),
    )


def _string_array(value: Any, name: str, ordinal: int) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"srcMove move {ordinal} field {name!r} must be a string array")
    return value


def _text_digests(values: list[str]) -> list[dict[str, Any]]:
    result = []
    for value in values:
        content = value.encode("utf-8")
        result.append(
            {
                "size_bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    return result


def _metrics(outcome: PairOutcome) -> dict[str, Any]:
    result = dict(outcome.metrics)
    for name, value in result.items():
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(f"pair metric {name!r} must be finite")
        if not isinstance(value, (str, int, float, bool)) and value is not None:
            raise ValueError(f"pair metric {name!r} is not compact scalar data")
    return dict(sorted(result.items()))


def _timings(outcome: PairOutcome) -> dict[str, float]:
    result = dict(outcome.timings)
    for name, value in result.items():
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
        ):
            raise ValueError(f"pair timing {name!r} must be finite and non-negative")
        result[name] = float(value)
    return dict(sorted(result.items()))


def _failure_evidence(outcome: PairOutcome) -> dict[str, Any]:
    return {
        "srcdiff": _process_evidence(outcome.srcdiff_process),
        "srcmove": _process_evidence(outcome.srcmove_process),
    }


def _process_evidence(process: ProcessOutcome | None) -> dict[str, Any] | None:
    if process is None:
        return None
    return {
        "termination_status": process.termination_status,
        "exit_code": process.exit_code,
        "signal_number": process.signal_number,
        "timed_out": process.timed_out,
        "spawn_error": process.spawn_error,
        "elapsed_seconds": process.elapsed_seconds,
        "cleanup_signals": list(process.cleanup_signals),
        "process_group_cleaned": process.process_group_cleaned,
        "peak_rss_bytes": process.peak_rss_bytes,
        "oom_kill_observed": process.oom_kill_observed,
        "validation_error": process.validation_error,
        "stdout": _capture_evidence(process.stdout),
        "stderr": _capture_evidence(process.stderr),
        "output_artifact": (
            None
            if process.output_artifact is None
            else {
                "size_bytes": process.output_artifact.size_bytes,
                "sha256": process.output_artifact.sha256,
                "kind": process.output_artifact.kind,
                "validation_status": process.output_artifact.validation_status,
            }
        ),
    }


def _capture_evidence(capture: CaptureObservation) -> dict[str, Any]:
    retained = b""
    if capture.path is not None:
        retained = _read_file(capture.path, "bounded process capture")
    if len(retained) != capture.retained_bytes:
        raise ValueError("bounded process capture size changed before publication")
    if len(retained) > COMPACT_FAILURE_LOG_LIMIT:
        half = COMPACT_FAILURE_LOG_LIMIT // 2
        retained = retained[:half] + retained[-half:]
    return {
        "total_bytes": capture.total_bytes,
        "runtime_retained_bytes": capture.retained_bytes,
        "durable_retained_bytes": len(retained),
        "runtime_omitted_bytes": capture.omitted_bytes,
        "durable_omitted_bytes": capture.total_bytes - len(retained),
        "truncated": capture.truncated,
        "sha256": capture.sha256,
        "retained_base64": (
            None if not retained else base64.b64encode(retained).decode("ascii")
        ),
        "retained_sha256": (
            None if not retained else hashlib.sha256(retained).hexdigest()
        ),
    }


def _read_verified_file(
    path, expected_size: int, expected_sha256: str, context: str
) -> bytes:
    content = _read_file(path, context)
    if len(content) != expected_size:
        raise ValueError(f"{context} size changed before compact publication")
    if hashlib.sha256(content).hexdigest() != expected_sha256:
        raise ValueError(f"{context} checksum changed before compact publication")
    return content


def _read_file(path, context: str) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError(f"{context} is not a regular file")
        blocks: list[bytes] = []
        while block := os.read(descriptor, 1024 * 1024):
            blocks.append(block)
        return b"".join(blocks)
    finally:
        os.close(descriptor)
