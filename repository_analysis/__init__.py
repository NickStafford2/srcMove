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
from .reporting import PairReceiptPublisher, pair_receipt
from .retention import RetentionPolicy
from .worker import PairExecutor

__all__ = [
    "CoordinatorStats",
    "CaptureObservation",
    "ChangedPath",
    "PairOutcome",
    "PairExecutor",
    "PairReceiptPublisher",
    "PairStatus",
    "PairWorkItem",
    "ProcessOutcome",
    "RetentionPolicy",
    "VerifiedArtifact",
    "WorkerExecutionError",
    "pair_receipt",
    "run_pairs",
]
