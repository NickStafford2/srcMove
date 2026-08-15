"""Repository inputs adapted to the shared benchmark pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from benchmarks.contracts import (
    PreparedCase,
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
        self.case = PreparedCase(
            case_id=case_id,
            original=original,
            modified=modified,
            metadata=metadata or {},
        )

    def prepare(self) -> Sequence[PreparedCase]:
        return [self.case]

    def validate_semantics(
        self, case: PreparedCase, srcdiff_xml: Path
    ) -> SemanticResult:
        return SemanticResult(SemanticStatus.NOT_APPLICABLE)
