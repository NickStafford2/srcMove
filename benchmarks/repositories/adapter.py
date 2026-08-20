"""Repository inputs adapted to the shared benchmark pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from benchmarks.contracts import (
    InputPair,
    SemanticResult,
    SemanticStatus,
)


class RepositoryAdapter:
    name = "repository"
    version = 1

    def __init__(
        self,
        *,
        case_id: str,
        original: Path,
        modified: Path,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        self.case = InputPair(
            case_id=case_id,
            original=original,
            modified=modified,
            metadata=metadata or {},
        )

    def input_pairs(self) -> Sequence[InputPair]:
        return [self.case]

    def validate_semantics(
        self, case: InputPair, srcdiff_xml: Path
    ) -> SemanticResult:
        return SemanticResult(SemanticStatus.NOT_APPLICABLE)
