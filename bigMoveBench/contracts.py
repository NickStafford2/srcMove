"""Contracts for BigMoveBench's staged dataset workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable


class SemanticStatus(StrEnum):
    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"
    NOT_APPLICABLE = "not_applicable"
    NOT_CHECKED = "not_checked"


@dataclass(frozen=True)
class InputPair:
    """Old/new source pair to freeze in a BigMoveBench input snapshot."""

    case_id: str
    original: Path
    modified: Path
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MaterializedInputPair:
    """One pair written directly into BigMoveBench snapshot staging."""

    case_id: str
    original: Mapping[str, Any]
    modified: Mapping[str, Any]
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SemanticResult:
    """BigMoveBench eligibility after generic srcDiff XML admission."""

    status: SemanticStatus
    details: Mapping[str, Any] = field(default_factory=dict)


class DatasetAdapter(Protocol):
    """Supply source pairs and validate their BigMoveBench eligibility."""

    name: str
    version: int

    def input_pairs(self) -> Sequence[InputPair]: ...

    def validate_semantics(
        self, case: InputPair, srcdiff_xml: Path
    ) -> SemanticResult: ...


@runtime_checkable
class SnapshotMaterializingAdapter(Protocol):
    """Write canonical inputs directly into snapshot staging."""

    name: str
    version: int

    def materialize_input_pairs(
        self, sources_root: Path, excluded_suffixes: Sequence[str]
    ) -> Sequence[MaterializedInputPair]: ...
