"""Frozen evidence-retention policy for SQLite repository analysis."""

from __future__ import annotations

from dataclasses import dataclass


RETENTION_POLICY_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    """The only retention mode currently implemented by the SQLite runtime."""

    mode: str = "compact"

    def __post_init__(self) -> None:
        if self.mode != "compact":
            raise ValueError(f"unsupported repository-analysis retention: {self.mode}")

    def record(self) -> dict[str, object]:
        return {
            "schema_version": RETENTION_POLICY_SCHEMA_VERSION,
            "mode": self.mode,
            "successful_pairs": "metrics_xpaths_and_text_digests",
            "failed_pairs": "bounded_process_evidence",
            "tool_outputs": "discard_after_compaction",
            "materialized_inputs": "ephemeral",
        }
