"""Low-overhead, opt-in timing records for BigMoveBench orchestration."""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Mapping, TextIO


RUNNER_PROFILE_SCHEMA_VERSION = 2


class RunnerProfiler:
    """Write one JSONL timing record for each newly executed case attempt."""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._stream: TextIO | None = self.path.open(
            "x", encoding="utf-8", buffering=1
        )
        self._record: dict[str, Any] | None = None
        self._started_ns: int | None = None

    def close(self) -> None:
        if self._stream is None:
            return
        try:
            self._stream.close()
        except OSError as error:
            self._warn(error)
        self._stream = None

    @staticmethod
    def _warn(error: OSError) -> None:
        print(
            f"warning: runner profiling disabled after output failure: {error}",
            file=sys.stderr,
        )

    def begin_case(
        self,
        *,
        case_id: str,
        ordinal: int,
        run_id: str,
        started_ns: int,
        phases_ms: Mapping[str, float],
        counters: Mapping[str, int],
    ) -> None:
        if self._stream is None:
            return
        if self._record is not None:
            raise RuntimeError("runner profile already has an active case")
        self._started_ns = started_ns
        self._record = {
            "schema_version": RUNNER_PROFILE_SCHEMA_VERSION,
            "record_type": "case",
            "case_id": case_id,
            "ordinal": ordinal,
            "run_id": run_id,
            "phases_ms": dict(phases_ms),
            "counters": dict(counters),
        }

    def identify_attempt(self, attempt_id: str, attempt_ordinal: int) -> None:
        if self._record is None:
            return
        self._record["attempt_id"] = attempt_id
        self._record["attempt_ordinal"] = attempt_ordinal

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

    def attempt_callback(
        self, stage: str
    ) -> Callable[[str, float, Mapping[str, int]], None]:
        def record(
            name: str, seconds: float, counters: Mapping[str, int]
        ) -> None:
            if name == "process_supervision":
                self.add_phase(f"runner.{stage}_supervision_ms", seconds)
            elif name == "xml_validation":
                self.add_phase(f"runner.{stage}_validation_ms", seconds)
            elif name == "attempt_setup":
                self.add_phase("runner.attempt_setup_ms", seconds)
            elif name == "attempt_started_write":
                # This callback runs after spawn and overlaps the child window.
                self.add_phase("runner.attempt_started_write_ms", seconds)
            elif name in {"attempt_capture_write", "attempt_terminal_write"}:
                self.add_phase("runner.attempt_write_ms", seconds)
                self.add_phase(f"runner.{name}_ms", seconds)
            else:
                raise ValueError(f"unknown attempt profile event: {name}")

            profiled_counters = {
                f"runner.{key}": value for key, value in counters.items()
            }
            if name == "xml_validation" and "validation_bytes" in counters:
                profiled_counters[
                    f"runner.{stage}_validation_bytes"
                ] = counters["validation_bytes"]
            if name in {"attempt_started_write", "attempt_terminal_write"}:
                label = name.removeprefix("attempt_").removesuffix("_write")
                if "json_bytes" in counters:
                    profiled_counters[
                        f"runner.attempt_{label}_json_bytes"
                    ] = counters["json_bytes"]
            self.add_counters(profiled_counters)

        return record

    def discard_case(self) -> None:
        self._record = None
        self._started_ns = None

    def finish_case(self, outcome: str) -> None:
        if self._stream is None:
            self.discard_case()
            return
        if self._record is None or self._started_ns is None:
            raise RuntimeError("runner profile has no active case")
        self._record["outcome"] = outcome
        self._record["phases_ms"]["runner.case_total_ms"] = (
            time.perf_counter_ns() - self._started_ns
        ) / 1_000_000.0
        serialized = (
            json.dumps(self._record, sort_keys=True, separators=(",", ":")) + "\n"
        )
        try:
            self._stream.write(serialized)
            self._stream.flush()
        except OSError as error:
            self._warn(error)
            try:
                self._stream.close()
            except OSError:
                pass
            self._stream = None
        finally:
            self.discard_case()
