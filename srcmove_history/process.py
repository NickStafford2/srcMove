"""History-specific tool execution and artifact admission."""

from __future__ import annotations

import hashlib
import json
import os
import time
import xml.etree.ElementTree as ET
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from srcmove_runtime.process_supervision import CaptureResult, run_supervised_process

from .contracts import CaptureObservation, ProcessOutcome, VerifiedArtifact
from .results import normalize_compactable_results


DEFAULT_LOG_LIMIT = 1024 * 1024
DEFAULT_TIMEOUT_GRACE_SECONDS = 5.0
# These versions are fingerprint inputs; bump them when admission semantics change.
SRCDIFF_XML_VALIDATOR_SCHEMA_VERSION = 1
SRCMOVE_RESULTS_VALIDATOR_SCHEMA_VERSION = 2
SRCML_NAMESPACE = "http://www.srcML.org/srcML/src"
SRCDIFF_NAMESPACES = {
    "http://www.srcML.org/srcDiff",
    "http://www.srcML.org/srcDiff/diff",
}
ArtifactValidator = Callable[[Path], VerifiedArtifact]


class ArtifactValidationError(RuntimeError):
    """A produced artifact could not be admitted."""

    def __init__(
        self, message: str, artifact: VerifiedArtifact | None = None
    ) -> None:
        super().__init__(message)
        self.artifact = artifact


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> tuple[int, str]:
    hasher = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            hasher.update(block)
            size += len(block)
    return size, hasher.hexdigest()


def validate_xml_artifact(
    path: Path, *, shape: str, producing_stage: str
) -> VerifiedArtifact:
    """Admit a srcDiff-shaped XML file and record its checksum."""

    if shape not in {"archive", "single_file"}:
        raise ValueError(f"unknown srcDiff XML shape: {shape}")
    try:
        size, checksum = _sha256_file(path)
    except FileNotFoundError as error:
        raise ArtifactValidationError("output XML is missing") from error
    if size == 0:
        raise ArtifactValidationError(
            "output XML is empty",
            _invalid_artifact(
                path, size, checksum, producing_stage, shape, "empty"
            ),
        )

    namespaces: set[str] = set()
    try:
        parsed = ET.iterparse(path, events=("start-ns",))
        for _, namespace in parsed:
            namespaces.add(namespace[1])
        root = parsed.root
    except (ET.ParseError, OSError) as error:
        message = f"output XML is malformed: {error}"
        raise ArtifactValidationError(
            message,
            _invalid_artifact(
                path, size, checksum, producing_stage, shape, "malformed", message
            ),
        ) from error
    if root.tag != f"{{{SRCML_NAMESPACE}}}unit":
        message = "root must be a srcML unit element"
        raise ArtifactValidationError(
            message,
            _invalid_artifact(
                path,
                size,
                checksum,
                producing_stage,
                shape,
                "invalid_structure",
                message,
            ),
        )
    if not namespaces.intersection(SRCDIFF_NAMESPACES):
        message = "srcDiff namespace declaration is missing"
        raise ArtifactValidationError(
            message,
            _invalid_artifact(
                path,
                size,
                checksum,
                producing_stage,
                shape,
                "invalid_structure",
                message,
            ),
        )
    child_units = tuple(
        child for child in root if child.tag == f"{{{SRCML_NAMESPACE}}}unit"
    )
    if shape == "archive" and not child_units:
        message = "archive output must contain child unit elements"
        raise ArtifactValidationError(
            message,
            _invalid_artifact(
                path,
                size,
                checksum,
                producing_stage,
                shape,
                "invalid_structure",
                message,
            ),
        )
    if shape == "single_file" and child_units:
        message = "single-file output must not contain child unit elements"
        raise ArtifactValidationError(
            message,
            _invalid_artifact(
                path,
                size,
                checksum,
                producing_stage,
                shape,
                "invalid_structure",
                message,
            ),
        )
    return VerifiedArtifact(
        path=path,
        size_bytes=size,
        sha256=checksum,
        kind="xml",
        validation_status="valid",
        producing_stage=producing_stage,
        shape=shape,
    )


def _invalid_artifact(
    path: Path,
    size: int,
    checksum: str,
    producing_stage: str,
    shape: str,
    status: str,
    error: str | None = None,
) -> VerifiedArtifact:
    return VerifiedArtifact(
        path=path,
        size_bytes=size,
        sha256=checksum,
        kind="xml",
        validation_status=status,
        producing_stage=producing_stage,
        shape=shape,
        details=(("error", error),) if error is not None else (),
    )


def validate_results_artifact(
    path: Path,
    *,
    producing_stage: str = "srcmove",
    producing_command: tuple[str, ...] = (),
) -> tuple[VerifiedArtifact, tuple[tuple[str, Any], ...]]:
    """Admit srcMove JSON results and return normalized scalar metrics."""

    try:
        content = path.read_bytes()
    except FileNotFoundError as error:
        raise ArtifactValidationError("srcMove results JSON is missing") from error
    checksum = hashlib.sha256(content).hexdigest()
    try:
        value = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        message = f"srcMove results JSON is malformed: {error}"
        raise ArtifactValidationError(
            message,
            _invalid_results_artifact(
                path,
                content,
                checksum,
                producing_stage,
                producing_command,
                "malformed",
                message,
            ),
        ) from error
    if not isinstance(value, dict):
        message = "srcMove results must be a JSON object"
        raise ArtifactValidationError(
            message,
            _invalid_results_artifact(
                path,
                content,
                checksum,
                producing_stage,
                producing_command,
                "invalid_structure",
                message,
            ),
        )
    try:
        normalize_compactable_results(value)
    except ValueError as error:
        message = str(error)
        raise ArtifactValidationError(
            message,
            _invalid_results_artifact(
                path,
                content,
                checksum,
                producing_stage,
                producing_command,
                "invalid_structure",
                message,
            ),
        ) from error
    metrics = tuple(
        sorted(
            (key, metric)
            for key, metric in value.items()
            if isinstance(metric, (int, float, str, bool)) or metric is None
        )
    )
    return (
        VerifiedArtifact(
            path=path,
            size_bytes=len(content),
            sha256=checksum,
            kind="json_results",
            validation_status="valid",
            producing_stage=producing_stage,
            producing_command=producing_command,
        ),
        metrics,
    )


def _invalid_results_artifact(
    path: Path,
    content: bytes,
    checksum: str,
    producing_stage: str,
    producing_command: tuple[str, ...],
    status: str,
    error: str,
) -> VerifiedArtifact:
    return VerifiedArtifact(
        path=path,
        size_bytes=len(content),
        sha256=checksum,
        kind="json_results",
        validation_status=status,
        producing_stage=producing_stage,
        producing_command=producing_command,
        details=(("error", error),),
    )


def _persist_capture(path: Path, capture: CaptureResult) -> CaptureObservation:
    retained_path: Path | None = None
    if capture.retained:
        path.write_bytes(capture.retained)
        retained_path = path
    return CaptureObservation(
        path=retained_path,
        total_bytes=capture.total_bytes,
        retained_bytes=len(capture.retained),
        omitted_bytes=capture.omitted_bytes,
        truncated=capture.truncated,
        sha256=capture.sha256,
    )


def run_process(
    command: Sequence[str | os.PathLike[str]],
    *,
    cwd: Path,
    timeout_seconds: float,
    output_path: Path,
    validator: ArtifactValidator,
    capture_prefix: str,
    log_limit: int = DEFAULT_LOG_LIMIT,
    timeout_grace_seconds: float = DEFAULT_TIMEOUT_GRACE_SECONDS,
) -> ProcessOutcome:
    """Run one process group, bound logs, and validate its output once."""

    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if log_limit < 2:
        raise ValueError("log_limit must be at least two bytes")
    started_at = _utc_now()
    started = time.monotonic()
    result = run_supervised_process(
        command,
        cwd=cwd,
        timeout_seconds=timeout_seconds,
        timeout_grace_seconds=timeout_grace_seconds,
        capture_limit=log_limit,
    )

    stdout = _persist_capture(cwd / f"{capture_prefix}.stdout.bin", result.stdout)
    stderr = _persist_capture(cwd / f"{capture_prefix}.stderr.bin", result.stderr)
    artifact: VerifiedArtifact | None = None
    validation_error: str | None = None
    try:
        artifact = validator(output_path)
        if not artifact.producing_command:
            artifact = replace(artifact, producing_command=result.command)
    except ArtifactValidationError as error:
        artifact = error.artifact
        if artifact is not None and not artifact.producing_command:
            artifact = replace(artifact, producing_command=result.command)
        validation_error = str(error)
    except OSError as error:
        validation_error = str(error)

    return ProcessOutcome(
        command=result.command,
        working_directory=cwd.resolve(),
        started_at=started_at,
        completed_at=_utc_now(),
        elapsed_seconds=time.monotonic() - started,
        termination_status=result.termination_status,
        exit_code=result.exit_code,
        signal_number=result.signal_number,
        timed_out=result.timed_out,
        spawn_error=result.spawn_error,
        cleanup_signals=result.signals_sent,
        process_group_cleaned=result.process_group_cleaned,
        stdout=stdout,
        stderr=stderr,
        peak_rss_bytes=result.resources.peak_rss_bytes,
        oom_kill_observed=result.resources.cgroup_oom_kill_observed,
        output_artifact=artifact,
        validation_error=validation_error,
    )
