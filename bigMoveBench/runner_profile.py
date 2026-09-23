"""Low-overhead, opt-in timing records for BigMoveBench orchestration."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Mapping, TextIO


RUNNER_PROFILE_SCHEMA_VERSION = 1


class RunnerProfiler:
    """Write one recoverable JSONL timing record for each completed case."""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._stream: TextIO = self.path.open("a", encoding="utf-8", buffering=1)
        self._record: dict[str, Any] | None = None
        self._started_ns: int | None = None

    def close(self) -> None:
        self._stream.close()

    def begin_case(
        self,
        *,
        case_id: str,
        ordinal: int,
        started_ns: int,
        phases_ms: Mapping[str, float],
        counters: Mapping[str, int],
    ) -> None:
        if self._record is not None:
            raise RuntimeError("runner profile already has an active case")
        self._started_ns = started_ns
        self._record = {
            "schema_version": RUNNER_PROFILE_SCHEMA_VERSION,
            "record_type": "case",
            "case_id": case_id,
            "ordinal": ordinal,
            "phases_ms": dict(phases_ms),
            "counters": dict(counters),
        }

    def add_phase(self, name: str, seconds: float) -> None:
        if self._record is None:
            return
        phases = self._record["phases_ms"]
        phases[name] = phases.get(name, 0.0) + seconds * 1000.0

    def add_counters(self, counters: Mapping[str, int]) -> None:
        if self._record is None:
            return
        values = self._record["counters"]
        for name, value in counters.items():
            values[name] = values.get(name, 0) + value

    def finish_case(self, outcome: str) -> None:
        if self._record is None or self._started_ns is None:
            raise RuntimeError("runner profile has no active case")
        self._record["outcome"] = outcome
        self._record["phases_ms"]["runner.case_total_ms"] = (
            time.perf_counter_ns() - self._started_ns
        ) / 1_000_000.0
        self._stream.write(
            json.dumps(self._record, sort_keys=True, separators=(",", ":")) + "\n"
        )
        self._stream.flush()
        self._record = None
        self._started_ns = None
