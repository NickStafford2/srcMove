"""Production repository-history analysis primitives."""

from .chain import (
    AnalysisSegment,
    AnalysisState,
    initialize_analysis_state,
    load_verified_analysis_state,
    publish_analysis_state_reports,
)
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
from .inputs import (
    AnalysisConfiguration,
    AnalysisContinuation,
    ExecutableObservation,
    FrozenAnalysisManifest,
    RepositoryIdentity,
    build_pair_work_items,
    freeze_analysis_inputs,
    load_frozen_manifest,
    observe_executable,
    pair_fingerprint,
    pair_fingerprint_bytes,
    persist_frozen_manifest,
    verify_resume_inputs,
)
from .reporting import (
    PairReceiptPublisher,
    derive_history_summary,
    pair_receipt,
    publish_history_reports,
)
from .retention import RetentionPolicy
from .resume import (
    ResumeStats,
    prepare_verified_resume,
    resume_pairs,
)
from .worker import PairExecutor

__all__ = [
    "CoordinatorStats",
    "CaptureObservation",
    "ChangedPath",
    "AnalysisConfiguration",
    "AnalysisContinuation",
    "AnalysisSegment",
    "AnalysisState",
    "ExecutableObservation",
    "FrozenAnalysisManifest",
    "PairOutcome",
    "PairExecutor",
    "PairReceiptPublisher",
    "PairStatus",
    "PairWorkItem",
    "ProcessOutcome",
    "RetentionPolicy",
    "ResumeStats",
    "RepositoryIdentity",
    "VerifiedArtifact",
    "WorkerExecutionError",
    "build_pair_work_items",
    "derive_history_summary",
    "pair_receipt",
    "publish_history_reports",
    "prepare_verified_resume",
    "freeze_analysis_inputs",
    "load_frozen_manifest",
    "load_verified_analysis_state",
    "observe_executable",
    "pair_fingerprint",
    "pair_fingerprint_bytes",
    "persist_frozen_manifest",
    "publish_analysis_state_reports",
    "initialize_analysis_state",
    "resume_pairs",
    "run_pairs",
    "verify_resume_inputs",
]
