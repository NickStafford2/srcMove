"""Production repository-history analysis primitives."""

from .contracts import (
    CaptureObservation,
    ChangedPath,
    PairOutcome,
    PairStatus,
    PairWorkItem,
    ProcessOutcome,
    VerifiedArtifact,
)
from .coordinator import (
    Coordinator,
    CoordinatorStats,
    WorkerExecutionError,
)
from .worker import PairExecutor

__all__ = [
    "Coordinator",
    "CoordinatorStats",
    "CaptureObservation",
    "ChangedPath",
    "PairOutcome",
    "PairExecutor",
    "PairStatus",
    "PairWorkItem",
    "ProcessOutcome",
    "VerifiedArtifact",
    "WorkerExecutionError",
]
