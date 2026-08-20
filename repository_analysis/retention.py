"""Policy-driven admission of worker artifacts into durable pair storage."""

from __future__ import annotations

import hashlib
import os
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path

from .contracts import CaptureObservation, PairOutcome, PairStatus, VerifiedArtifact


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    """Explicit initial retention policy for every terminal outcome class.

    Successful analyzed pairs always retain ``results.json``. Positive-pair XML
    is opt-in because the canonical design leaves that downstream inspection
    choice open. Skipped pairs retain no files. Failed pairs retain tool logs,
    admitted partial outputs, and successful intermediate tool outputs, but
    never the materialized Git input trees.
    """

    retain_positive_xml: bool = False

    def record(self) -> dict[str, object]:
        return {
            "completed_positive": (
                "results_and_xml" if self.retain_positive_xml else "results"
            ),
            "completed_zero_move": "results",
            "no_analyzable_change": "receipt_only",
            "failed": "tool_logs_and_outputs",
            "materialized_inputs": "discard_after_acknowledgement",
        }


DEFAULT_RETENTION_POLICY = RetentionPolicy()


@dataclass(frozen=True, slots=True)
class RetainedFile:
    """One file copied and checksum-verified in analysis-owned storage."""

    source: Path
    relative_path: Path
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class RetainedOutcomeFiles:
    """Durable artifact and bounded-capture admissions for one outcome."""

    artifacts: tuple[RetainedFile, ...]
    captures: tuple[RetainedFile, ...]

    def by_source(self) -> dict[Path, RetainedFile]:
        return {
            retained.source: retained
            for retained in (*self.artifacts, *self.captures)
        }


def retain_outcome_files(
    outcome: PairOutcome,
    analysis_root: Path,
    pair_directory: Path,
    *,
    policy: RetentionPolicy = DEFAULT_RETENTION_POLICY,
) -> RetainedOutcomeFiles:
    """Admit every policy-required file before a receipt may be sealed."""

    root = analysis_root.resolve()
    _require_within_root(pair_directory, root)
    pair_directory.mkdir(parents=False, exist_ok=False)
    artifacts_directory = pair_directory / "artifacts"
    artifacts_directory.mkdir(exist_ok=False)

    retained_artifacts: list[RetainedFile] = []
    retained_captures: list[RetainedFile] = []
    admitted_sources: set[Path] = set()

    for index, artifact in enumerate(outcome.artifacts):
        source = _absolute_path(artifact.path)
        if source in admitted_sources or not _retain_artifact(
            outcome, artifact, policy
        ):
            continue
        admitted_sources.add(source)
        destination = artifacts_directory / (
            f"artifact-{index:03d}-{_safe_name(source.name)}"
        )
        retained_artifacts.append(
            _admit_file(
                source,
                destination,
                root,
                expected_size=artifact.size_bytes,
                expected_sha256=artifact.sha256,
            )
        )

    if outcome.status in _FAILURE_STATUSES:
        for stage, process in (
            ("srcdiff", outcome.srcdiff_process),
            ("srcmove", outcome.srcmove_process),
        ):
            if process is None:
                continue
            for stream_name, capture in (
                ("stdout", process.stdout),
                ("stderr", process.stderr),
            ):
                if capture.path is None:
                    continue
                source = _absolute_path(capture.path)
                if source in admitted_sources:
                    continue
                admitted_sources.add(source)
                retained_captures.append(
                    _admit_capture(
                        source,
                        artifacts_directory / f"{stage}-{stream_name}.bin",
                        root,
                        capture,
                    )
                )

    _fsync_directory(artifacts_directory)
    _fsync_directory(pair_directory)
    return RetainedOutcomeFiles(
        artifacts=tuple(retained_artifacts),
        captures=tuple(retained_captures),
    )


_FAILURE_STATUSES = {
    PairStatus.EXPORT_FAILED,
    PairStatus.SRCDIFF_FAILED,
    PairStatus.SRCMOVE_FAILED,
    PairStatus.ORCHESTRATION_FAILED,
}


def _retain_artifact(
    outcome: PairOutcome, artifact: VerifiedArtifact, policy: RetentionPolicy
) -> bool:
    if artifact.kind == "git_blob":
        return False
    if outcome.status in _FAILURE_STATUSES:
        return artifact.producing_stage in {"srcdiff", "srcmove"}
    if outcome.status is not PairStatus.COMPLETED:
        return False
    if artifact.kind == "json_results":
        return True
    return (
        policy.retain_positive_xml
        and int(dict(outcome.metrics).get("move_count", 0)) > 0
        and artifact.kind == "xml"
    )


def _admit_capture(
    source: Path,
    destination: Path,
    root: Path,
    capture: CaptureObservation,
) -> RetainedFile:
    retained = _admit_file(
        source,
        destination,
        root,
        expected_size=capture.retained_bytes,
        expected_sha256=None,
    )
    if capture.retained_bytes > capture.total_bytes:
        raise ValueError("retained capture size exceeds total captured bytes")
    return retained


def _admit_file(
    source: Path,
    destination: Path,
    root: Path,
    *,
    expected_size: int,
    expected_sha256: str | None,
) -> RetainedFile:
    _require_source_file(source, root)
    _require_within_root(destination, root)
    temporary = destination.with_name(
        f".{destination.name}.tmp-{uuid.uuid4().hex}"
    )
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    source_fd = os.open(source, flags)
    try:
        source_stat = os.fstat(source_fd)
        if not stat.S_ISREG(source_stat.st_mode):
            raise ValueError(f"retained source is not a regular file: {source}")
        hasher = hashlib.sha256()
        size = 0
        with temporary.open("xb") as output:
            while block := os.read(source_fd, 1024 * 1024):
                output.write(block)
                hasher.update(block)
                size += len(block)
            output.flush()
            os.fsync(output.fileno())
        checksum = hasher.hexdigest()
        if size != expected_size:
            raise ValueError(
                f"retained source size changed for {source}: "
                f"expected {expected_size}, observed {size}"
            )
        if expected_sha256 is not None and checksum != expected_sha256:
            raise ValueError(f"retained source checksum changed for {source}")
        os.link(temporary, destination)
        _fsync_directory(destination.parent)
    finally:
        os.close(source_fd)
        temporary.unlink(missing_ok=True)
    return RetainedFile(
        source=source,
        relative_path=destination.relative_to(root),
        size_bytes=size,
        sha256=checksum,
    )


def _require_source_file(source: Path, root: Path) -> None:
    try:
        source.lstat()
    except FileNotFoundError:
        raise FileNotFoundError(f"required retained file is missing: {source}")
    if source.is_symlink():
        raise ValueError(f"refusing to retain a symbolic link: {source}")
    resolved = source.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError(f"retained source escapes analysis root: {source}") from error


def _require_within_root(path: Path, root: Path) -> None:
    absolute = _absolute_path(path)
    try:
        absolute.relative_to(root)
    except ValueError as error:
        raise ValueError(f"path escapes analysis root: {path}") from error


def _absolute_path(path: Path) -> Path:
    return Path(os.path.abspath(path))


def _safe_name(name: str) -> str:
    cleaned = "".join(
        character if character.isalnum() or character in {".", "-", "_"} else "_"
        for character in name
    )
    return cleaned or "artifact"


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
