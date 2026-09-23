"""Small value types shared by BigMoveBench execution stages."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping


class SemanticStatus(StrEnum):
    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"
    NOT_APPLICABLE = "not_applicable"
    NOT_CHECKED = "not_checked"


@dataclass(frozen=True)
class InputPair:
    """One materialized old/new source pair being evaluated."""

    case_id: str
    original: Path
    modified: Path
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SemanticResult:
    """BigMoveBench eligibility after generic srcDiff XML admission."""

    status: SemanticStatus
    details: Mapping[str, Any] = field(default_factory=dict)
