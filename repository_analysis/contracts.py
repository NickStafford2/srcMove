"""Immutable values exchanged by repository-analysis workers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


# Bump when the normalized terminal pair-result contract changes.
PAIR_OUTCOME_SCHEMA_VERSION = 1
COMPACT_PAIR_SCHEMA_VERSION = 1


class PairStatus(str, Enum):
    """Terminal status of one adjacent commit pair."""

    COMPLETED = "completed"
    NO_ANALYZABLE_CHANGE = "no_analyzable_change"
    EXPORT_FAILED = "export_failed"
    SRCDIFF_FAILED = "srcdiff_failed"
    SRCMOVE_FAILED = "srcmove_failed"
    ORCHESTRATION_FAILED = "orchestration_failed"


@dataclass(frozen=True, slots=True)
class ChangedPath:
    """One content path reported by Git's raw diff inventory."""

    status: str
    path: str
    old_mode: str
    new_mode: str
    old_blob: str
    new_blob: str

    @property
    def exists_in_old(self) -> bool:
        return self.old_mode != "000000"

    @property
    def exists_in_new(self) -> bool:
        return self.new_mode != "000000"

    @property
    def content_changed(self) -> bool:
        return self.old_blob != self.new_blob


@dataclass(frozen=True, slots=True)
class PairWorkItem:
    """Frozen inputs for one adjacent commit pair.

    Optional execution fields preserve the small coordinator contract while
    allowing the production executor to reject incomplete work explicitly.
    """

    sequence: int
    old_commit: str
    new_commit: str
    fingerprint: str
    repository: Path | None = None
    selected_directory: str | None = None
    excluded_suffixes: tuple[str, ...] = ()
    srcdiff: Path | None = None
    srcmove: Path | None = None
    srcdiff_timeout_seconds: float = 1800.0
    srcmove_timeout_seconds: float = 300.0
    use_position: bool = False
    source_encoding: str = "UTF-8"

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise ValueError("pair sequence must be non-negative")
        if not self.old_commit or not self.new_commit:
            raise ValueError("pair commits must be non-empty")
        if not self.fingerprint:
            raise ValueError("pair fingerprint must be non-empty")
        if self.srcdiff_timeout_seconds <= 0 or self.srcmove_timeout_seconds <= 0:
            raise ValueError("tool timeouts must be positive")


@dataclass(frozen=True, slots=True)
class VerifiedArtifact:
    """An owned file admitted immediately after it was produced."""

    path: Path
    size_bytes: int
    sha256: str
    kind: str
    validation_status: str
    producing_stage: str
    producing_command: tuple[str, ...] = ()
    shape: str | None = None
    details: tuple[tuple[str, Any], ...] = ()
    retention: str = "worker_owned"


@dataclass(frozen=True, slots=True)
class CaptureObservation:
    """Bounded stdout or stderr retained on disk."""

    path: Path | None
    total_bytes: int
    retained_bytes: int
    omitted_bytes: int
    truncated: bool
    sha256: str


@dataclass(frozen=True, slots=True)
class ProcessOutcome:
    """Complete, bounded evidence from one supervised tool invocation."""

    command: tuple[str, ...]
    working_directory: Path
    started_at: str
    completed_at: str
    elapsed_seconds: float
    termination_status: str
    exit_code: int | None
    signal_number: int | None
    timed_out: bool
    spawn_error: str | None
    cleanup_signals: tuple[int, ...]
    process_group_cleaned: bool
    stdout: CaptureObservation
    stderr: CaptureObservation
    peak_rss_bytes: int | None
    oom_kill_observed: bool
    output_artifact: VerifiedArtifact | None
    validation_error: str | None

    @property
    def admitted(self) -> bool:
        return (
            self.termination_status == "exited"
            and self.exit_code == 0
            and self.output_artifact is not None
            and self.validation_error is None
        )


@dataclass(frozen=True, slots=True)
class PairOutcome:
    """Immutable terminal result returned by a worker."""

    work_item: PairWorkItem
    status: PairStatus
    changed_paths: tuple[ChangedPath, ...] = ()
    analyzable_paths: tuple[ChangedPath, ...] = ()
    srcdiff_process: ProcessOutcome | None = None
    srcmove_process: ProcessOutcome | None = None
    artifacts: tuple[VerifiedArtifact, ...] = ()
    metrics: tuple[tuple[str, Any], ...] = ()
    timings: tuple[tuple[str, float], ...] = ()
    error: str | None = None
