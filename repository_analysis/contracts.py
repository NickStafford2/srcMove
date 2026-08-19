"""Immutable values exchanged by repository-analysis workers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PairStatus(str, Enum):
    """Terminal status of one adjacent commit pair."""

    COMPLETED = "completed"
    NO_ANALYZABLE_CHANGE = "no_analyzable_change"
    EXPORT_FAILED = "export_failed"
    SRCDIFF_FAILED = "srcdiff_failed"
    SRCMOVE_FAILED = "srcmove_failed"
    ORCHESTRATION_FAILED = "orchestration_failed"


@dataclass(frozen=True, slots=True)
class PairWorkItem:
    """Frozen identity and ordering for one adjacent commit pair."""

    sequence: int
    old_commit: str
    new_commit: str
    fingerprint: str

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise ValueError("pair sequence must be non-negative")
        if not self.old_commit or not self.new_commit:
            raise ValueError("pair commits must be non-empty")
        if not self.fingerprint:
            raise ValueError("pair fingerprint must be non-empty")


@dataclass(frozen=True, slots=True)
class PairOutcome:
    """Small terminal reference returned by a worker."""

    work_item: PairWorkItem
    status: PairStatus
