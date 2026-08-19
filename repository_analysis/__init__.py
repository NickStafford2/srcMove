"""Production repository-history analysis primitives."""

from .contracts import PairOutcome, PairStatus, PairWorkItem
from .coordinator import (
    Coordinator,
    CoordinatorStats,
    WorkerExecutionError,
)

__all__ = [
    "Coordinator",
    "CoordinatorStats",
    "PairOutcome",
    "PairStatus",
    "PairWorkItem",
    "WorkerExecutionError",
]
