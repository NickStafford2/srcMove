"""Supported application interface for repository-history analysis."""

from .analysis import (
    AnalysisTarget,
    AnalyzeResult,
    analysis_identity,
    analysis_list_pairs,
    analysis_pair_details,
    analysis_status,
    analyze_repository,
)

from .inputs import (
    AnalysisConfiguration,
    RepositoryIdentity,
)

__all__ = [
    "AnalysisTarget",
    "AnalyzeResult",
    "AnalysisConfiguration",
    "RepositoryIdentity",
    "analysis_identity",
    "analysis_pair_details",
    "analysis_list_pairs",
    "analysis_status",
    "analyze_repository",
]
