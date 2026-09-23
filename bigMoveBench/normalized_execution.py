#!/usr/bin/env python3
"""Execute normalized BigMoveBench cases through a serial SQLite journal."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any, TextIO


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarking.execution import (
    ATTEMPT_SCHEMA_VERSION,
    execute_attempt,
    recover_interrupted_attempts,
)
from benchmarking.identity import canonical_json
from benchmarking.provenance import observe_executable, sha256_file, utc_now
from benchmarking.srcdiff_validation import validate_srcdiff_xml
from benchmarking.storage import write_json_atomic
from benchmarking.tooling import find_srcdiff, find_srcmove
from bigMoveBench.adapter import SEMANTIC_ORACLE_VERSION, validate_srcdiff_semantics
from bigMoveBench.benchmark_cases import (
    SerialBenchmarkCaseRunner,
    VerifiedBenchmarkCases,
    load_benchmark_cases,
)
from bigMoveBench.contracts import InputPair, SemanticStatus
from bigMoveBench.evaluate import (
    OUTCOMES,
    SCORING_ORACLE_VERSION,
    _score_completed_case,
    validate_results_output,
)
from bigMoveBench.paths import DEFAULT_CACHE_ROOT
from bigMoveBench.progress import ProgressDisplay
from bigMoveBench.runner_profile import RunnerProfiler
from bigMoveBench.selection import TYPE3_STRATA
from bigMoveBench.srcdiff_cache import DevelopmentSrcdiffCache


EXECUTION_JOURNAL_SCHEMA_VERSION = 1
EXECUTION_JOURNAL_APPLICATION_ID = 0x424D4A31
EXECUTION_JOURNAL_USER_VERSION = 1
RETRYABLE_FAILURES = {
    "upstream_failure",
    "srcmove_tool_failure",
    "oracle_failure",
}
FAILED_OUTCOMES = RETRYABLE_FAILURES | {"srcdiff_semantic_ineligible"}
ActivityCallback = Callable[[str, str], None]
TransactionCallback = Callable[[float], None]
CASE_CSV_FIELDS = (
    "case_id",
    "ordinal",
    "outcome",
    "case_kind",
    "clone_type",
    "syntactic_type",
    "expected_match_kind",
    "observed_match_kind",
    "move_count",
    "semantic_status",
    "semantic_reason",
    "type3_both_similarity",
    "type3_strength_stratum",
    "functionality_id",
    "function_id_one",
    "function_id_two",
    "min_tokens",
    "raw_text_identical",
    "from_text_validation",
    "to_text_validation",
    "input_sha256",
    "attempt_id",
    "attempt_ordinal",
    "srcdiff_attempt_id",
    "srcmove_attempt_id",
    "failures",
)


def _json(value: Any) -> str:
    return canonical_json(value).decode("utf-8")


def _relative(path: Path, parent: Path) -> str:
    return path.resolve().relative_to(parent.resolve()).as_posix()


def _schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        f"""
PRAGMA application_id = {EXECUTION_JOURNAL_APPLICATION_ID};
PRAGMA user_version = {EXECUTION_JOURNAL_USER_VERSION};
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = FULL;

CREATE TABLE run_metadata (
  singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
  schema_version INTEGER NOT NULL,
  run_id TEXT NOT NULL UNIQUE,
  benchmark_cases_id TEXT NOT NULL,
  benchmark_cases_manifest_sha256 TEXT NOT NULL
    CHECK (length(benchmark_cases_manifest_sha256) = 64),
  created_at TEXT NOT NULL,
  completed_at TEXT,
  status TEXT NOT NULL CHECK (status IN ('running', 'completed')),
  configuration_json TEXT NOT NULL,
  provenance_json TEXT NOT NULL
) STRICT;

CREATE TABLE attempts (
  attempt_id TEXT PRIMARY KEY,
  case_id TEXT NOT NULL,
  attempt_ordinal INTEGER NOT NULL CHECK (attempt_ordinal >= 0),
  attempt_identity_sha256 TEXT NOT NULL
    CHECK (length(attempt_identity_sha256) = 64),
  status TEXT NOT NULL CHECK (status IN ('running', 'interrupted', 'terminal')),
  started_at TEXT NOT NULL,
  completed_at TEXT,
  outcome TEXT,
  srcdiff_attempt_id TEXT,
  srcdiff_attempt_path TEXT,
  srcdiff_admitted INTEGER CHECK (srcdiff_admitted IN (0, 1)),
  srcdiff_record_json TEXT,
  semantic_status TEXT,
  semantic_details_json TEXT,
  srcmove_attempt_id TEXT,
  srcmove_attempt_path TEXT,
  srcmove_completed INTEGER CHECK (srcmove_completed IN (0, 1)),
  srcmove_record_json TEXT,
  oracle_failures_json TEXT,
  text_validation_json TEXT,
  oracle_results_json TEXT,
  UNIQUE (case_id, attempt_ordinal),
  CHECK (
    (status = 'terminal' AND completed_at IS NOT NULL AND outcome IS NOT NULL)
    OR status != 'terminal'
  )
) STRICT;

CREATE INDEX attempts_case_status_idx
  ON attempts(case_id, status, attempt_ordinal DESC);
CREATE INDEX attempts_outcome_idx ON attempts(outcome) WHERE status = 'terminal';
"""
    )


class ExecutionJournal:
    """Own the small transactional state for one normalized serial run."""

    def __init__(
        self,
        path: Path,
        *,
        benchmark_cases: VerifiedBenchmarkCases,
        configuration: Mapping[str, Any],
        provenance: Mapping[str, Any],
        run_id: str,
    ) -> None:
        self.path = path
        existed = path.exists()
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        if not existed:
            _schema(self.connection)
            with self.connection:
                self.connection.execute(
                    "INSERT INTO run_metadata VALUES (1,?,?,?,?,?,?,?,?,?)",
                    (
                        EXECUTION_JOURNAL_SCHEMA_VERSION,
                        run_id,
                        benchmark_cases.benchmark_cases_id,
                        benchmark_cases.manifest_sha256,
                        utc_now(),
                        None,
                        "running",
                        _json(configuration),
                        _json(provenance),
                    ),
                )
        self._validate(
            benchmark_cases=benchmark_cases,
            configuration=configuration,
            provenance=provenance,
            requested_run_id=None if existed else run_id,
        )

    def close(self) -> None:
        self.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.connection.close()

    def _validate(
        self,
        *,
        benchmark_cases: VerifiedBenchmarkCases,
        configuration: Mapping[str, Any],
        provenance: Mapping[str, Any],
        requested_run_id: str | None,
    ) -> None:
        if self.connection.execute("PRAGMA application_id").fetchone()[0] != (
            EXECUTION_JOURNAL_APPLICATION_ID
        ):
            raise ValueError("normalized execution journal application id is invalid")
        if self.connection.execute("PRAGMA user_version").fetchone()[0] != (
            EXECUTION_JOURNAL_USER_VERSION
        ):
            raise ValueError("normalized execution journal schema version is invalid")
        row = self.connection.execute("SELECT * FROM run_metadata").fetchone()
        if row is None:
            raise ValueError("normalized execution journal metadata is missing")
        expected = (
            benchmark_cases.benchmark_cases_id,
            benchmark_cases.manifest_sha256,
            _json(configuration),
            _json(provenance),
        )
        observed = (
            row["benchmark_cases_id"],
            row["benchmark_cases_manifest_sha256"],
            row["configuration_json"],
            row["provenance_json"],
        )
        if observed != expected:
            raise ValueError(
                "resumed normalized run uses different cases, tools, or configuration"
            )
        if requested_run_id is not None and row["run_id"] != requested_run_id:
            raise ValueError("normalized execution run identity does not match")

    @property
    def run_id(self) -> str:
        return str(
            self.connection.execute(
                "SELECT run_id FROM run_metadata WHERE singleton=1"
            ).fetchone()[0]
        )

    def recover_running(self) -> int:
        with self.connection:
            cursor = self.connection.execute(
                "UPDATE attempts SET status='interrupted', completed_at=? "
                "WHERE status='running'",
                (utc_now(),),
            )
        return cursor.rowcount

    def latest_terminal(self, case_id: str) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM attempts WHERE case_id=? AND status='terminal' "
            "ORDER BY attempt_ordinal DESC LIMIT 1",
            (case_id,),
        ).fetchone()

    def begin(
        self,
        case_id: str,
        identity_sha256: str,
        *,
        transaction_callback: TransactionCallback | None = None,
    ) -> tuple[str, int]:
        ordinal = int(
            self.connection.execute(
                "SELECT COALESCE(MAX(attempt_ordinal), -1) + 1 FROM attempts "
                "WHERE case_id=?",
                (case_id,),
            ).fetchone()[0]
        )
        attempt_id = f"attempt-{uuid.uuid4()}"
        transaction_started = (
            time.perf_counter() if transaction_callback is not None else None
        )
        with self.connection:
            self.connection.execute(
                "INSERT INTO attempts "
                "(attempt_id, case_id, attempt_ordinal, attempt_identity_sha256, "
                "status, started_at) VALUES (?,?,?,?,?,?)",
                (attempt_id, case_id, ordinal, identity_sha256, "running", utc_now()),
            )
        if transaction_callback is not None and transaction_started is not None:
            transaction_callback(time.perf_counter() - transaction_started)
        return attempt_id, ordinal

    def finish(
        self,
        attempt_id: str,
        record: Mapping[str, Any],
        *,
        transaction_callback: TransactionCallback | None = None,
    ) -> None:
        values = (
            utc_now(),
            record["outcome"],
            record.get("srcdiff_attempt_id"),
            record.get("srcdiff_attempt_path"),
            record.get("srcdiff_admitted"),
            _json(record.get("srcdiff_record", {})),
            record.get("semantic_status"),
            _json(record.get("semantic_details", {})),
            record.get("srcmove_attempt_id"),
            record.get("srcmove_attempt_path"),
            record.get("srcmove_completed"),
            _json(record.get("srcmove_record", {})),
            _json(record.get("oracle_failures", [])),
            _json(record.get("text_validation", {})),
            _json(record.get("oracle_results", {})),
            attempt_id,
        )
        transaction_started = (
            time.perf_counter() if transaction_callback is not None else None
        )
        with self.connection:
            cursor = self.connection.execute(
                "UPDATE attempts SET status='terminal', completed_at=?, outcome=?, "
                "srcdiff_attempt_id=?, srcdiff_attempt_path=?, srcdiff_admitted=?, "
                "srcdiff_record_json=?, semantic_status=?, semantic_details_json=?, "
                "srcmove_attempt_id=?, srcmove_attempt_path=?, srcmove_completed=?, "
                "srcmove_record_json=?, oracle_failures_json=?, "
                "text_validation_json=?, "
                "oracle_results_json=? WHERE attempt_id=? AND status='running'",
                values,
            )
        if cursor.rowcount != 1:
            raise ValueError(f"normalized attempt is not running: {attempt_id}")
        if transaction_callback is not None and transaction_started is not None:
            transaction_callback(time.perf_counter() - transaction_started)

    def completed_case_count(self) -> int:
        return int(
            self.connection.execute(
                "SELECT COUNT(DISTINCT case_id) FROM attempts WHERE status='terminal'"
            ).fetchone()[0]
        )

    def mark_completed(self) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE run_metadata SET status='completed', completed_at=? "
                "WHERE singleton=1",
                (utc_now(),),
            )

    def mark_running(self) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE run_metadata SET status='running', completed_at=NULL "
                "WHERE singleton=1"
            )

    def latest_results(self) -> Iterator[sqlite3.Row]:
        yield from self.connection.execute(
            """
SELECT current.*
FROM attempts AS current
WHERE current.status='terminal'
  AND NOT EXISTS (
    SELECT 1 FROM attempts AS newer
    WHERE newer.case_id=current.case_id AND newer.status='terminal'
      AND newer.attempt_ordinal > current.attempt_ordinal
  )
ORDER BY current.case_id
"""
        )

    def write_cases_csv(
        self, path: Path, *, benchmark_cases_database: Path
    ) -> dict[str, Any]:
        """Stream the latest result for every case from SQL into a derived CSV."""

        self.connection.execute(
            "ATTACH DATABASE ? AS benchmark_cases",
            (str(benchmark_cases_database.resolve()),),
        )
        query = """
SELECT
  c.ordinal,
  c.case_id,
  c.pair_set,
  c.case_kind,
  c.syntactic_type,
  c.expected_match_kind,
  c.original_fragment_sha256,
  c.modified_fragment_sha256,
  c.type3_both_similarity,
  c.type3_strength_stratum,
  c.min_tokens,
  c.representative_functionality_id,
  c.representative_function_id_one,
  c.representative_function_id_two,
  a.attempt_id,
  a.attempt_ordinal,
  a.outcome,
  a.srcdiff_attempt_id,
  a.srcdiff_record_json,
  a.semantic_status,
  a.semantic_details_json,
  a.srcmove_attempt_id,
  a.oracle_failures_json,
  a.text_validation_json,
  a.oracle_results_json
FROM benchmark_cases.cases AS c
JOIN attempts AS a ON a.case_id=c.case_id AND a.status='terminal'
WHERE NOT EXISTS (
  SELECT 1 FROM attempts AS newer
  WHERE newer.case_id=a.case_id AND newer.status='terminal'
    AND newer.attempt_ordinal > a.attempt_ordinal
)
ORDER BY c.ordinal
"""
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", dir=path.parent
        )
        try:
            with os.fdopen(descriptor, "w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=CASE_CSV_FIELDS)
                writer.writeheader()
                for row in self.connection.execute(query):
                    semantic_details = json.loads(
                        row["semantic_details_json"] or "{}"
                    )
                    text_validation = json.loads(
                        row["text_validation_json"] or "{}"
                    )
                    results = json.loads(row["oracle_results_json"] or "{}")
                    srcdiff_record = json.loads(
                        row["srcdiff_record_json"] or "{}"
                    )
                    observed_kind = results.get(
                        "_oracle_observed_match_kind", ""
                    )
                    moves = results.get("moves")
                    if (
                        not observed_kind
                        and isinstance(moves, list)
                        and len(moves) == 1
                        and isinstance(moves[0], dict)
                    ):
                        observed_kind = moves[0].get("match_kind", "")
                    writer.writerow(
                        {
                            "case_id": row["case_id"],
                            "ordinal": row["ordinal"],
                            "outcome": row["outcome"],
                            "case_kind": row["case_kind"],
                            "clone_type": (
                                "known_false_positive"
                                if row["case_kind"] == "known_false_positive"
                                else f"type{row['syntactic_type']}"
                            ),
                            "syntactic_type": row["syntactic_type"],
                            "expected_match_kind": row["expected_match_kind"],
                            "observed_match_kind": observed_kind,
                            "move_count": results.get("move_count", ""),
                            "semantic_status": row["semantic_status"],
                            "semantic_reason": semantic_details.get("reason", ""),
                            "type3_both_similarity": row[
                                "type3_both_similarity"
                            ],
                            "type3_strength_stratum": row[
                                "type3_strength_stratum"
                            ],
                            "functionality_id": row[
                                "representative_functionality_id"
                            ],
                            "function_id_one": row[
                                "representative_function_id_one"
                            ],
                            "function_id_two": row[
                                "representative_function_id_two"
                            ],
                            "min_tokens": row["min_tokens"],
                            "raw_text_identical": (
                                row["original_fragment_sha256"]
                                == row["modified_fragment_sha256"]
                            ),
                            "from_text_validation": text_validation.get(
                                "from", "not_checked"
                            ),
                            "to_text_validation": text_validation.get(
                                "to", "not_checked"
                            ),
                            "input_sha256": srcdiff_record.get("xml", {}).get(
                                "sha256", ""
                            ),
                            "attempt_id": row["attempt_id"],
                            "attempt_ordinal": row["attempt_ordinal"],
                            "srcdiff_attempt_id": row["srcdiff_attempt_id"],
                            "srcmove_attempt_id": row["srcmove_attempt_id"] or "",
                            "failures": " | ".join(
                                json.loads(row["oracle_failures_json"] or "[]")
                            ),
                        }
                    )
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_name, path)
        except BaseException:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise
        finally:
            self.connection.execute("DETACH DATABASE benchmark_cases")
        return {"path": path.name, "sha256": sha256_file(path)}

    def summary(
        self,
        *,
        selected: int,
        cases_csv: Mapping[str, Any],
        benchmark_cases_database: Path,
    ) -> dict[str, Any]:
        counts = {outcome: 0 for outcome in OUTCOMES}
        strict_passes = tolerant_passes = 0
        negative_zero_move_passes = negative_incidental_move_passes = 0
        srcdiff_process_seconds = srcmove_process_seconds = 0.0
        peak_rss_bytes: int | None = None
        srcdiff_cache_hits = srcdiff_cache_misses = 0
        type3_groups: dict[str, dict[str, Any]] = {}
        self.connection.execute(
            "ATTACH DATABASE ? AS benchmark_cases",
            (str(benchmark_cases_database.resolve()),),
        )
        try:
            query = """
SELECT c.type3_strength_stratum, c.case_kind, a.*
FROM benchmark_cases.cases AS c
JOIN attempts AS a ON a.case_id=c.case_id AND a.status='terminal'
WHERE NOT EXISTS (
  SELECT 1 FROM attempts AS newer
  WHERE newer.case_id=a.case_id AND newer.status='terminal'
    AND newer.attempt_ordinal > a.attempt_ordinal
)
ORDER BY c.ordinal
"""
            for row in self.connection.execute(query):
                outcome = str(row["outcome"])
                counts[outcome] += 1
                validation = json.loads(row["text_validation_json"] or "{}")
                results = json.loads(row["oracle_results_json"] or "{}")
                if outcome == "oracle_pass":
                    if row["case_kind"] == "known_false_positive":
                        if results.get("move_count", 0) == 0:
                            negative_zero_move_passes += 1
                        else:
                            negative_incidental_move_passes += 1
                    elif "encoding_tolerant" in validation.values():
                        tolerant_passes += 1
                    else:
                        strict_passes += 1
                for stage in ("srcdiff", "srcmove"):
                    record = json.loads(row[f"{stage}_record_json"] or "{}")
                    if stage == "srcdiff":
                        if record.get("cache", {}).get("status") == "hit":
                            srcdiff_cache_hits += 1
                        else:
                            srcdiff_cache_misses += 1
                    elapsed = record.get("process_elapsed_seconds")
                    if isinstance(elapsed, (int, float)):
                        if stage == "srcdiff":
                            srcdiff_process_seconds += float(elapsed)
                        else:
                            srcmove_process_seconds += float(elapsed)
                    observed_peak = record.get("resource_usage", {}).get(
                        "peak_rss_bytes"
                    )
                    if isinstance(observed_peak, int):
                        peak_rss_bytes = max(peak_rss_bytes or 0, observed_peak)
                strength = row["type3_strength_stratum"]
                if strength:
                    group = type3_groups.setdefault(
                        str(strength),
                        {
                            "selected": 0,
                            "detected": 0,
                            "strictly_classified": 0,
                            "outcomes": {name: 0 for name in OUTCOMES},
                        },
                    )
                    group["selected"] += 1
                    group["detected"] += int(
                        outcome in {"oracle_pass", "wrong_classification"}
                    )
                    group["strictly_classified"] += int(outcome == "oracle_pass")
                    group["outcomes"][outcome] += 1
        finally:
            self.connection.execute("DETACH DATABASE benchmark_cases")
        for group in type3_groups.values():
            denominator = group["selected"]
            group["detection_rate"] = group["detected"] / denominator
            group["strict_classification_rate"] = (
                group["strictly_classified"] / denominator
            )
        type3_strength = {
            name: type3_groups[name]
            for name, _, _ in TYPE3_STRATA
            if name in type3_groups
        }
        completed = sum(counts.values())
        eligible = completed - counts["upstream_failure"] - counts[
            "srcdiff_semantic_ineligible"
        ]
        attempts = {
            str(row[0]): int(row[1])
            for row in self.connection.execute(
                "SELECT status, COUNT(*) FROM attempts GROUP BY status"
            )
        }
        metadata = self.connection.execute("SELECT * FROM run_metadata").fetchone()
        assert metadata is not None
        configuration = json.loads(metadata["configuration_json"])
        cache_configuration = configuration.get(
            "development_srcdiff_cache", {"enabled": False, "policy": "disabled"}
        )
        pair_set = json.loads(metadata["provenance_json"])["benchmark_cases"][
            "pair_set"
        ]
        negative_counts = (
            {
                "negative_zero_move_passes": negative_zero_move_passes,
                "negative_incidental_move_passes": negative_incidental_move_passes,
            }
            if pair_set == "known-false-positive"
            else {}
        )
        if pair_set == "known-false-positive":
            rates = {
                "end_to_end_whole_fragment_rejection": (
                    counts["oracle_pass"] / selected if selected else None
                ),
                "conditional_srcmove_whole_fragment_rejection": (
                    counts["oracle_pass"] / eligible if eligible else None
                ),
                "end_to_end_whole_fragment_false_positive": (
                    counts["srcmove_false_positive"] / selected
                    if selected
                    else None
                ),
                "conditional_srcmove_whole_fragment_false_positive": (
                    counts["srcmove_false_positive"] / eligible
                    if eligible
                    else None
                ),
            }
        else:
            rates = {
                "end_to_end_detection_and_classification": (
                    counts["oracle_pass"] / selected if selected else None
                ),
                "conditional_srcmove_detection_and_classification": (
                    counts["oracle_pass"] / eligible if eligible else None
                ),
                "end_to_end_strict_text_detection_and_classification": (
                    strict_passes / selected if selected else None
                ),
                "conditional_srcmove_strict_text_detection_and_classification": (
                    strict_passes / eligible if eligible else None
                ),
            }
        summary = {
            "schema_version": 1,
            "created_at": utc_now(),
            "run_id": metadata["run_id"],
            "benchmark_cases_id": metadata["benchmark_cases_id"],
            "benchmark_cases_manifest_sha256": metadata[
                "benchmark_cases_manifest_sha256"
            ],
            "status": "completed" if completed == selected else "running",
            "scoring_oracle": {
                "name": (
                    "bigclonebench-known-false-positive-negative"
                    if pair_set == "known-false-positive"
                    else "bigclonebench-strict"
                ),
                "version": SCORING_ORACLE_VERSION,
            },
            "counts": {
                "selected": selected,
                "eligible": eligible,
                "executed": eligible,
                **counts,
                "strict_passes": strict_passes,
                "encoding_tolerant_passes": tolerant_passes,
                **negative_counts,
            },
            "rates": rates,
            "journal": {
                "path": self.path.name,
                "attempts": attempts,
            },
            "strata": {"type3_strength": type3_strength},
            "timings": {
                "srcdiff_process_seconds": srcdiff_process_seconds,
                "srcmove_process_seconds": srcmove_process_seconds,
            },
            "resources": {"peak_rss_bytes": peak_rss_bytes},
            "development_srcdiff_cache": {
                **cache_configuration,
                "hits": srcdiff_cache_hits if cache_configuration["enabled"] else 0,
                "misses": (
                    srcdiff_cache_misses if cache_configuration["enabled"] else 0
                ),
                "suitable_for_thesis": False if cache_configuration["enabled"] else None,
            },
            "cases_csv": dict(cases_csv),
        }
        return summary


class SerialBenchmarkExecutionRunner:
    """Stream normalized evaluation through one reusable serial scratch tree."""

    def __init__(
        self,
        benchmark_cases: VerifiedBenchmarkCases,
        *,
        run_dir: Path,
        srcdiff: Path,
        srcmove: Path,
        srcdiff_timeout_seconds: float = 60.0,
        srcmove_timeout_seconds: float = 300.0,
        retry_failed: bool = False,
        scratch_root: Path | None = None,
        activity_callback: ActivityCallback | None = None,
        progress_enabled: bool = True,
        progress_stream: TextIO | None = None,
        srcdiff_observation: Mapping[str, Any] | None = None,
        srcmove_observation: Mapping[str, Any] | None = None,
        srcdiff_cache: DevelopmentSrcdiffCache | None = None,
        refresh_srcdiff_cache: bool = False,
        runner_profile_path: Path | None = None,
    ) -> None:
        self.benchmark_cases = benchmark_cases
        self.run_dir = run_dir.expanduser().resolve()
        self.srcdiff = srcdiff.expanduser().resolve()
        self.srcmove = srcmove.expanduser().resolve()
        self.srcdiff_timeout_seconds = srcdiff_timeout_seconds
        self.srcmove_timeout_seconds = srcmove_timeout_seconds
        self.retry_failed = retry_failed
        self.scratch_root = scratch_root
        self.activity_callback = activity_callback
        self.progress_enabled = progress_enabled
        self.progress_stream = progress_stream
        self.srcdiff_cache = srcdiff_cache
        self.refresh_srcdiff_cache = refresh_srcdiff_cache
        self.runner_profile_path = runner_profile_path
        self._runner_profiler: RunnerProfiler | None = None
        self.srcdiff_observation = dict(
            srcdiff_observation or observe_executable(self.srcdiff)
        )
        self.srcmove_observation = dict(
            srcmove_observation or observe_executable(self.srcmove)
        )
        self.configuration = {
            "serial_workers": 1,
            "srcdiff": {
                "position": True,
                "archive": True,
                "source_encoding": "UTF-8",
                "timeout_seconds": srcdiff_timeout_seconds,
                "semantic_oracle_version": SEMANTIC_ORACLE_VERSION,
            },
            "srcmove": {
                "timeout_seconds": srcmove_timeout_seconds,
                "output_mode": "results_only",
            },
            "scoring_oracle_version": SCORING_ORACLE_VERSION,
            "development_srcdiff_cache": {
                "enabled": srcdiff_cache is not None,
                "policy": (
                    "unversioned_development_only"
                    if srcdiff_cache is not None
                    else "disabled"
                ),
            },
        }
        self.provenance = {
            "benchmark_cases": {
                "id": benchmark_cases.benchmark_cases_id,
                "manifest_sha256": benchmark_cases.manifest_sha256,
                "pair_set": benchmark_cases.manifest["selection"]["pair_set"],
                "selection_id": benchmark_cases.manifest["selection"][
                    "selection_id"
                ],
                "compiled_dataset": dict(
                    benchmark_cases.manifest["compiled_dataset"]
                ),
                "wrapper_version": benchmark_cases.manifest["wrapper_version"],
            },
            "tools": {
                "srcdiff": self.srcdiff_observation,
                "srcmove": self.srcmove_observation,
            },
        }

    def _activity(self, status: str, case_id: str) -> None:
        if self.activity_callback is not None:
            self.activity_callback(status, case_id)

    def _profile_start(self) -> float | None:
        return time.perf_counter() if self._runner_profiler is not None else None

    def _profile_phase(self, name: str, started: float | None) -> None:
        if self._runner_profiler is not None and started is not None:
            self._runner_profiler.add_phase(name, time.perf_counter() - started)

    def _record_sqlite_transaction(self, seconds: float) -> None:
        if self._runner_profiler is not None:
            self._runner_profiler.add_phase(
                "runner.sqlite_transaction_ms", seconds
            )
            self._runner_profiler.add_counters(
                {"runner.sqlite_transactions": 1}
            )

    def _attempt_identity(self, case_id: str) -> str:
        value = {
            "benchmark_cases_id": self.benchmark_cases.benchmark_cases_id,
            "case_id": case_id,
            "srcdiff_sha256": self.srcdiff_observation.get("artifact", {}).get(
                "sha256"
            ),
            "srcmove_sha256": self.srcmove_observation.get("artifact", {}).get(
                "sha256"
            ),
            "configuration": self.configuration,
        }
        return hashlib.sha256(canonical_json(value)).hexdigest()

    def _restore_cached_srcdiff(
        self, case: InputPair, context: Mapping[str, Any]
    ) -> tuple[Path, dict[str, Any]] | None:
        if self.srcdiff_cache is None or self.refresh_srcdiff_cache:
            return None
        attempts_root = self.run_dir / "tool-attempts" / "srcdiff"
        attempts_root.mkdir(parents=True, exist_ok=True)
        temporary = attempts_root / f".cache-{uuid.uuid4()}.xml"
        restored = self.srcdiff_cache.restore(
            case_id=case.case_id,
            wrapper_version=int(case.metadata["synthetic_wrapper_version"]),
            destination=temporary,
        )
        if not restored:
            return None
        xml = validate_srcdiff_xml(temporary, "archive")
        if xml.get("status") != "valid":
            temporary.unlink(missing_ok=True)
            return None

        attempt_id = f"attempt-{uuid.uuid4()}"
        attempt_dir = attempts_root / attempt_id
        attempt_dir.mkdir(parents=False, exist_ok=False)
        output = attempt_dir / "srcdiff.xml"
        os.replace(temporary, output)
        timestamp = utc_now()
        record = {
            "schema_version": ATTEMPT_SCHEMA_VERSION,
            "attempt_id": attempt_id,
            "stage": "srcdiff",
            "case_id": case.case_id,
            "started_at": timestamp,
            "completed_at": timestamp,
            "command": [],
            "working_directory": str(case.original.parent.resolve()),
            "process_elapsed_seconds": 0.0,
            "termination": {"status": "cache_hit"},
            "resource_usage": {},
            "stdout": {"status": "not_run"},
            "stderr": {"status": "not_run"},
            "xml": xml,
            "output_path": output.name,
            "output_validation_key": "xml",
            "output_retention": "retained",
            "admitted": True,
            "context": dict(context),
            "cache": {
                "enabled": True,
                "status": "hit",
                "policy": "unversioned_development_only",
            },
        }
        write_json_atomic(attempt_dir / "attempt.json", record)
        return attempt_dir, record

    def _execute_case(self, case: InputPair, logical_attempt_id: str) -> dict[str, Any]:
        context = {
            "run_attempt_id": logical_attempt_id,
            "benchmark_cases_id": self.benchmark_cases.benchmark_cases_id,
            "benchmark_cases_manifest_sha256": self.benchmark_cases.manifest_sha256,
        }
        srcdiff_root = self.run_dir / "tool-attempts" / "srcdiff"
        cache_started = (
            self._profile_start() if self.srcdiff_cache is not None else None
        )
        cached = self._restore_cached_srcdiff(case, context)
        if self.srcdiff_cache is not None:
            self._profile_phase("runner.srcdiff_cache_ms", cache_started)
            if self._runner_profiler is not None:
                self._runner_profiler.add_counters(
                    {
                        "runner.srcdiff_cache_hits": int(cached is not None),
                        "runner.srcdiff_cache_misses": int(cached is None),
                    }
                )
        if cached is not None:
            srcdiff_dir, srcdiff_record = cached
        else:
            srcdiff_dir, srcdiff_record = execute_attempt(
                attempts_root=srcdiff_root,
                stage="srcdiff",
                case_id=case.case_id,
                command_factory=lambda output: [
                    str(self.srcdiff),
                    "--position",
                    "--archive",
                    "--src-encoding",
                    "UTF-8",
                    str(case.original),
                    str(case.modified),
                    "-o",
                    str(output),
                ],
                cwd=case.original.parent,
                timeout_seconds=self.srcdiff_timeout_seconds,
                output_validator=lambda path: validate_srcdiff_xml(path, "archive"),
                output_filename="srcdiff.xml",
                context=context,
                profile_callback=(
                    self._runner_profiler.attempt_callback("srcdiff")
                    if self._runner_profiler is not None
                    else None
                ),
            )
            if self.srcdiff_cache is not None:
                cache_record = {
                    "enabled": True,
                    "status": "refreshed" if self.refresh_srcdiff_cache else "miss",
                    "policy": "unversioned_development_only",
                }
                if srcdiff_record["admitted"]:
                    try:
                        self.srcdiff_cache.store(
                            case_id=case.case_id,
                            wrapper_version=int(
                                case.metadata["synthetic_wrapper_version"]
                            ),
                            source=srcdiff_dir / "srcdiff.xml",
                        )
                        cache_record["stored"] = True
                    except OSError as error:
                        cache_record["stored"] = False
                        cache_record["error"] = f"{type(error).__name__}: {error}"
                srcdiff_record["cache"] = cache_record
                write_json_atomic(srcdiff_dir / "attempt.json", srcdiff_record)
        result: dict[str, Any] = {
            "outcome": "upstream_failure",
            "srcdiff_attempt_id": srcdiff_record["attempt_id"],
            "srcdiff_attempt_path": _relative(srcdiff_dir, self.run_dir),
            "srcdiff_admitted": int(bool(srcdiff_record["admitted"])),
            "srcdiff_record": srcdiff_record,
            "semantic_status": SemanticStatus.NOT_CHECKED.value,
            "semantic_details": {},
            "srcmove_completed": 0,
            "oracle_failures": [],
            "text_validation": {"from": "not_checked", "to": "not_checked"},
            "oracle_results": {},
        }
        if not srcdiff_record["admitted"]:
            return result

        srcdiff_process_seconds = srcdiff_record.get("process_elapsed_seconds")
        if self._runner_profiler is not None and isinstance(
            srcdiff_process_seconds, (int, float)
        ):
            self._runner_profiler.add_phase(
                "runner.srcdiff_process_ms", float(srcdiff_process_seconds)
            )
        semantic_started = self._profile_start()
        semantic = validate_srcdiff_semantics(case, srcdiff_dir / "srcdiff.xml")
        self._profile_phase("runner.semantic_validation_ms", semantic_started)
        result["semantic_status"] = semantic.status.value
        result["semantic_details"] = dict(semantic.details)
        if semantic.status != SemanticStatus.ELIGIBLE:
            result["outcome"] = "srcdiff_semantic_ineligible"
            return result

        srcmove_root = self.run_dir / "tool-attempts" / "srcmove"
        srcmove_dir, srcmove_record = execute_attempt(
            attempts_root=srcmove_root,
            stage="srcmove",
            case_id=case.case_id,
            command_factory=lambda output: [
                str(self.srcmove),
                str(srcdiff_dir / "srcdiff.xml"),
                "--results",
                str(output),
                "--results-only",
            ],
            cwd=self.run_dir,
            timeout_seconds=self.srcmove_timeout_seconds,
            output_validator=validate_results_output,
            output_filename="results.json",
            output_validation_key="results",
            context=context
            | {
                "srcdiff_attempt_id": srcdiff_record["attempt_id"],
                "srcdiff_sha256": srcdiff_record["xml"].get("sha256"),
                "srcmove_output_mode": "results_only",
            },
            profile_callback=(
                self._runner_profiler.attempt_callback("srcmove")
                if self._runner_profiler is not None
                else None
            ),
        )
        srcmove_process_seconds = srcmove_record.get("process_elapsed_seconds")
        if self._runner_profiler is not None and isinstance(
            srcmove_process_seconds, (int, float)
        ):
            self._runner_profiler.add_phase(
                "runner.srcmove_process_ms", float(srcmove_process_seconds)
            )
        results_path = srcmove_dir / "results.json"
        completed = bool(srcmove_record["admitted"])
        result.update(
            {
                "outcome": "srcmove_tool_failure",
                "srcmove_attempt_id": srcmove_record["attempt_id"],
                "srcmove_attempt_path": _relative(srcmove_dir, self.run_dir),
                "srcmove_completed": int(completed),
                "srcmove_record": srcmove_record,
            }
        )
        if not completed:
            return result

        scoring_started = self._profile_start()
        outcome, failures, text_validation, oracle_results = _score_completed_case(
            metadata=dict(case.metadata),
            results_path=results_path,
            srcdiff_xml=srcdiff_dir / "srcdiff.xml",
        )
        self._profile_phase("runner.scoring_ms", scoring_started)
        result.update(
            {
                "outcome": outcome,
                "oracle_failures": failures,
                "text_validation": text_validation,
                "oracle_results": oracle_results,
            }
        )
        return result

    def run(self) -> tuple[Path, dict[str, Any]]:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        if self.runner_profile_path is not None:
            profile_path = self.runner_profile_path.expanduser().resolve()
            if profile_path == self.run_dir or self.run_dir in profile_path.parents:
                raise ValueError(
                    "runner profile path must be outside the execution run directory"
                )
            self._runner_profiler = RunnerProfiler(profile_path)
        journal_path = self.run_dir / "execution.sqlite"
        run_id = self.run_dir.name
        selected = int(self.benchmark_cases.manifest["counts"]["cases"])
        pair_set = str(self.benchmark_cases.manifest["selection"]["pair_set"])
        journal: ExecutionJournal | None = None
        try:
            journal = ExecutionJournal(
                journal_path,
                benchmark_cases=self.benchmark_cases,
                configuration=self.configuration,
                provenance=self.provenance,
                run_id=run_id,
            )
            with ProgressDisplay(
                "normalized execution",
                total=selected,
                detail=pair_set,
                stream=self.progress_stream,
                enabled=self.progress_enabled,
            ) as progress:
                recover_interrupted_attempts(
                    self.run_dir / "tool-attempts" / "srcdiff"
                )
                recover_interrupted_attempts(
                    self.run_dir / "tool-attempts" / "srcmove"
                )
                journal.recover_running()
                journal.mark_running()
                visited = executed = reused = failed = 0
                with SerialBenchmarkCaseRunner(
                    self.benchmark_cases,
                    scratch_root=self.scratch_root,
                    profile_enabled=self._runner_profiler is not None,
                ) as cases:
                    for case in cases.cases():
                        previous = journal.latest_terminal(case.case_id)
                        should_retry = bool(
                            previous is not None
                            and self.retry_failed
                            and previous["outcome"] in RETRYABLE_FAILURES
                        )
                        if previous is not None and not should_retry:
                            reused += 1
                            visited += 1
                            self._activity("reused", case.case_id)
                            progress.update(
                                visited, detail=f"reused {case.case_id}"
                            )
                            cases.clear_scratch()
                            continue
                        if self._runner_profiler is not None:
                            prepared = cases.last_profile
                            if prepared is None or prepared["case_id"] != case.case_id:
                                raise RuntimeError(
                                    "benchmark-case profile identity does not match"
                                )
                            self._runner_profiler.begin_case(
                                **prepared, run_id=run_id
                            )
                        progress.update(visited, detail=f"running {case.case_id}")
                        attempt_identity = self._attempt_identity(case.case_id)
                        attempt_id, attempt_ordinal = journal.begin(
                            case.case_id,
                            attempt_identity,
                            transaction_callback=(
                                self._record_sqlite_transaction
                                if self._runner_profiler is not None
                                else None
                            ),
                        )
                        if self._runner_profiler is not None:
                            self._runner_profiler.identify_attempt(
                                attempt_id, attempt_ordinal
                            )
                        self._activity("running", case.case_id)
                        record = self._execute_case(case, attempt_id)
                        journal.finish(
                            attempt_id,
                            record,
                            transaction_callback=(
                                self._record_sqlite_transaction
                                if self._runner_profiler is not None
                                else None
                            ),
                        )
                        cleanup_started = self._profile_start()
                        removed_links = cases.clear_scratch()
                        if self._runner_profiler is not None:
                            self._profile_phase(
                                "runner.scratch_cleanup_ms", cleanup_started
                            )
                            self._runner_profiler.add_counters(
                                {"runner.scratch_links_removed": removed_links}
                            )
                            self._runner_profiler.finish_case(record["outcome"])
                        executed += 1
                        visited += 1
                        case_failed = record["outcome"] in FAILED_OUTCOMES
                        failed += int(case_failed)
                        self._activity(
                            "failed" if case_failed else "completed", case.case_id
                        )
                        progress.update(
                            visited,
                            detail=f"{record['outcome']} {case.case_id}",
                        )
                if journal.completed_case_count() != selected:
                    raise ValueError(
                        "normalized execution journal terminal case count does not "
                        "reconcile"
                    )
                journal.mark_completed()
                cases_csv = journal.write_cases_csv(
                    self.run_dir / "cases.csv",
                    benchmark_cases_database=(
                        self.benchmark_cases.directory / "benchmark_cases.sqlite"
                    ),
                )
                summary = journal.summary(
                    selected=selected,
                    cases_csv=cases_csv,
                    benchmark_cases_database=(
                        self.benchmark_cases.directory / "benchmark_cases.sqlite"
                    ),
                )
                write_json_atomic(self.run_dir / "summary.json", summary)
                progress.finish(
                    f"{executed} executed, {reused} reused, {failed} failed"
                )
                return self.run_dir, summary
        finally:
            if journal is not None:
                journal.close()
            if self._runner_profiler is not None:
                self._runner_profiler.close()
                self._runner_profiler = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("benchmark_cases", help="Benchmark-cases ID or directory.")
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    parser.add_argument(
        "--results-root", type=Path, default=Path("benchmark-results")
    )
    parser.add_argument("--resume-run", type=Path)
    parser.add_argument("--srcdiff", type=Path)
    parser.add_argument("--srcmove", type=Path)
    parser.add_argument("--srcdiff-timeout", type=float, default=60.0)
    parser.add_argument("--srcmove-timeout", type=float, default=300.0)
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument(
        "--profile-runner",
        type=Path,
        help="Write one opt-in Python orchestration timing record per case.",
    )
    parser.add_argument(
        "--cache",
        action="store_true",
        help=(
            "Reuse unversioned srcDiff XML for development only; unsuitable for "
            "thesis results."
        ),
    )
    parser.add_argument(
        "--refresh-cache",
        action="store_true",
        help="Replace development srcDiff cache entries (implies --cache).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        benchmark_cases = load_benchmark_cases(
            args.cache_root, args.benchmark_cases, verification="full"
        )
        srcdiff = find_srcdiff(REPO_ROOT, args.srcdiff)
        srcmove = find_srcmove(REPO_ROOT, args.srcmove)
        if srcdiff is None:
            raise ValueError("srcdiff not found; pass --srcdiff")
        if srcmove is None:
            raise ValueError("srcMove not found; pass --srcmove")
        run_dir = (
            args.resume_run.expanduser().resolve()
            if args.resume_run is not None
            else args.results_root.expanduser().resolve()
            / "bigMoveBench"
            / "runs"
            / (
                "normalized-"
                f"{utc_now().replace(':', '').replace('+', '-')}-{uuid.uuid4()}"
            )
        )
        _, summary = SerialBenchmarkExecutionRunner(
            benchmark_cases,
            run_dir=run_dir,
            srcdiff=srcdiff,
            srcmove=srcmove,
            srcdiff_timeout_seconds=args.srcdiff_timeout,
            srcmove_timeout_seconds=args.srcmove_timeout,
            retry_failed=args.retry_failed,
            srcdiff_cache=(
                DevelopmentSrcdiffCache(
                    args.cache_root / "development-srcdiff"
                )
                if args.cache or args.refresh_cache
                else None
            ),
            refresh_srcdiff_cache=args.refresh_cache,
            runner_profile_path=args.profile_runner,
        ).run()
        print(f"run_id={summary['run_id']}")
        print(f"directory={run_dir}")
        print(
            f"selected={summary['counts']['selected']} "
            f"oracle_pass={summary['counts']['oracle_pass']}"
        )
        cache = summary["development_srcdiff_cache"]
        if cache["enabled"]:
            print(
                "WARNING: unversioned development srcDiff cache used; "
                "this run is unsuitable for thesis results"
            )
            print(f"srcdiff_cache_hits={cache['hits']} misses={cache['misses']}")
        return 0
    except (OSError, ValueError, sqlite3.Error, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
