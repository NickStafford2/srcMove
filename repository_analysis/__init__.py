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
    CoordinatorStats,
    WorkerExecutionError,
    run_pairs,
)
from .worker import PairExecutor

__all__ = [
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
    "run_pairs",
]
