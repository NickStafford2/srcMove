"""Authoritative transactional state for large repository analyses."""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import stat
import uuid
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .compact import compact_pair_outcome
from .contracts import PairOutcome
from .inputs import (
    FrozenAnalysisManifest,
    build_pair_work_items,
    canonical_json_bytes,
    load_frozen_manifest_bytes,
)
from .retention import RetentionPolicy


DATABASE_NAME = "analysis.sqlite3"
DATABASE_SCHEMA_VERSION = 2
DATABASE_APPLICATION_ID = 0x53524D41  # "SRMA"
TARGET_KINDS = {"total_pairs", "through", "all"}
TERMINAL_PAIR_STATUSES = {
    "completed",
    "no_analyzable_change",
    "export_failed",
    "srcdiff_failed",
    "srcmove_failed",
    "orchestration_failed",
}
INVOCATION_RESULTS = {
    "running",
    "target_reached",
    "target_reached_with_failures",
    "failed",
    "interrupted",
}


@dataclass(frozen=True, slots=True)
class StoredAnalysis:
    revision: int
    definition_sha256: str
    newest_commit: str
    oldest_completed_commit: str | None
    completed_pair_count: int
    history_exhausted: bool


@dataclass(frozen=True, slots=True)
class StoredBatch:
    batch_id: str
    base_revision: int
    target_kind: str
    target_value: str | None
    manifest_sha256: str
    oldest_commit: str
    newest_commit: str
    pair_count: int
    reaches_root: bool
    status: str


@dataclass(frozen=True, slots=True)
class StoredInvocation:
    invocation_id: str
    created_order: int
    target_kind: str
    target_value: str | None
    jobs: int
    started_at: str
    last_durable_at: str
    ended_at: str | None
    result: str
    wall_seconds: float | None
    error: str | None

    def record(self) -> dict[str, Any]:
        return {
            "invocation_id": self.invocation_id,
            "target_kind": self.target_kind,
            "target_value": self.target_value,
            "jobs": self.jobs,
            "started_at": self.started_at,
            "last_durable_at": self.last_durable_at,
            "ended_at": self.ended_at,
            "result": self.result,
            "wall_seconds": self.wall_seconds,
            "error": self.error,
        }


class AnalysisDatabase:
    """One SQLite database containing frozen work and committed compact state."""

    def __init__(self, root: Path, connection: sqlite3.Connection) -> None:
        self.root = root
        self.path = root / DATABASE_NAME
        self.connection = connection
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self._verify_schema()

    @classmethod
    def create(
        cls,
        analysis_root: Path,
        manifest: FrozenAnalysisManifest,
        *,
        batch_id: str,
        target_kind: str,
        target_value: str | None,
        reaches_root: bool,
        retention_policy: RetentionPolicy,
    ) -> AnalysisDatabase:
        root = _owned_root(analysis_root)
        path = root / DATABASE_NAME
        if path.exists() or path.is_symlink():
            raise ValueError(f"analysis database already exists: {path}")
        temporary = root / f".{DATABASE_NAME}.tmp-{uuid.uuid4().hex}"
        connection = sqlite3.connect(temporary, isolation_level=None)
        try:
            connection.execute("PRAGMA journal_mode = DELETE")
            connection.execute("PRAGMA synchronous = FULL")
            connection.execute(f"PRAGMA application_id = {DATABASE_APPLICATION_ID}")
            connection.execute(f"PRAGMA user_version = {DATABASE_SCHEMA_VERSION}")
            connection.executescript(_SCHEMA)
            database = cls(root, connection)
            definition = _definition_bytes(manifest, retention_policy)
            with database._transaction():
                database.connection.execute(
                    """
                    INSERT INTO analysis(
                        singleton, revision, definition_json, definition_sha256,
                        newest_commit, oldest_completed_commit,
                        completed_pair_count, history_exhausted
                    ) VALUES (1, 0, ?, ?, ?, NULL, 0, 0)
                    """,
                    (
                        definition,
                        hashlib.sha256(definition).hexdigest(),
                        manifest.commits[-1],
                    ),
                )
                database._insert_pending_batch(
                    manifest,
                    batch_id=batch_id,
                    target_kind=target_kind,
                    target_value=target_value,
                    reaches_root=reaches_root,
                    expected_revision=0,
                    retention_policy=retention_policy,
                )
            database.close()
            connection = None
            _fsync_file(temporary)
            os.link(temporary, path)
            temporary.unlink()
            _fsync_directory(root)
            return cls.open(root)
        except BaseException:
            if connection is not None:
                connection.close()
            raise
        finally:
            temporary.unlink(missing_ok=True)

    @classmethod
    def open(
        cls, analysis_root: Path, *, read_only: bool = False
    ) -> AnalysisDatabase:
        root = _existing_owned_root(analysis_root)
        path = root / DATABASE_NAME
        if not read_only:
            _recover_interrupted_publication(root, path)
        _require_owned_database(path)
        connection = sqlite3.connect(
            path.as_uri() + "?mode=ro" if read_only else path,
            isolation_level=None,
            uri=read_only,
        )
        try:
            database = cls(root, connection)
            if not read_only:
                connection.execute("PRAGMA journal_mode = WAL")
                connection.execute("PRAGMA synchronous = FULL")
            return database
        except BaseException:
            connection.close()
            raise

    def __enter__(self) -> AnalysisDatabase:
        return self

    def __exit__(self, exception_type, exception, traceback) -> None:
        self.close()

    def close(self) -> None:
        self.connection.close()

    @contextmanager
    def read_snapshot(self):
        """Keep related read-only queries on one committed SQLite snapshot."""

        self.connection.execute("BEGIN")
        try:
            yield
        finally:
            self.connection.execute("ROLLBACK")

    def begin_invocation(
        self,
        invocation_id: str,
        *,
        target_kind: str,
        target_value: str | None,
        jobs: int,
        started_at: str,
    ) -> StoredInvocation:
        """Record one run and reconcile a writer that never finalized."""

        _validate_invocation_id(invocation_id)
        _validate_target(target_kind, target_value)
        if isinstance(jobs, bool) or not isinstance(jobs, int) or jobs <= 0:
            raise ValueError("invocation jobs must be a positive integer")
        started = _text(started_at, "invocation start time")
        with self._transaction():
            self.connection.execute(
                """
                UPDATE invocations
                SET ended_at = ?, result = 'interrupted',
                    error = COALESCE(error, 'writer ended before invocation finalized')
                WHERE result = 'running'
                """,
                (started,),
            )
            created_order = int(
                self.connection.execute(
                    "SELECT COALESCE(MAX(created_order), -1) + 1 FROM invocations"
                ).fetchone()[0]
            )
            self.connection.execute(
                """
                INSERT INTO invocations(
                    invocation_id, created_order, target_kind, target_value,
                    jobs, started_at, last_durable_at, ended_at, result,
                    wall_seconds, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 'running', NULL, NULL)
                """,
                (
                    invocation_id,
                    created_order,
                    target_kind,
                    target_value,
                    jobs,
                    started,
                    started,
                ),
            )
        return self.invocation(invocation_id)

    def finish_invocation(
        self,
        invocation_id: str,
        *,
        result: str,
        ended_at: str,
        wall_seconds: float,
        error: str | None = None,
    ) -> StoredInvocation:
        """Finalize exactly one running invocation."""

        _validate_invocation_id(invocation_id)
        if result not in INVOCATION_RESULTS - {"running"}:
            raise ValueError(f"invalid terminal invocation result: {result!r}")
        ended = _text(ended_at, "invocation end time")
        if (
            isinstance(wall_seconds, bool)
            or not isinstance(wall_seconds, (int, float))
            or not math.isfinite(wall_seconds)
            or wall_seconds < 0
        ):
            raise ValueError("invocation wall time must be finite and nonnegative")
        if error is not None:
            error = _text(error, "invocation error")
        with self._transaction():
            changed = self.connection.execute(
                """
                UPDATE invocations
                SET ended_at = ?, last_durable_at = ?, result = ?,
                    wall_seconds = ?, error = ?
                WHERE invocation_id = ? AND result = 'running'
                """,
                (
                    ended,
                    ended,
                    result,
                    float(wall_seconds),
                    error,
                    invocation_id,
                ),
            ).rowcount
            if changed != 1:
                raise ValueError("invocation is missing or already finalized")
        return self.invocation(invocation_id)

    def invocation(self, invocation_id: str) -> StoredInvocation:
        _validate_invocation_id(invocation_id)
        row = self.connection.execute(
            "SELECT * FROM invocations WHERE invocation_id = ?",
            (invocation_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"unknown analysis invocation: {invocation_id}")
        return _stored_invocation(row)

    def latest_invocation(self) -> StoredInvocation | None:
        row = self.connection.execute(
            "SELECT * FROM invocations ORDER BY created_order DESC LIMIT 1"
        ).fetchone()
        return None if row is None else _stored_invocation(row)

    def analysis(self) -> StoredAnalysis:
        row = self.connection.execute(
            """
            SELECT revision, definition_json, definition_sha256, newest_commit,
                   oldest_completed_commit, completed_pair_count,
                   history_exhausted
            FROM analysis WHERE singleton = 1
            """
        ).fetchone()
        if row is None:
            raise ValueError("analysis database is missing its singleton state")
        definition = bytes(row["definition_json"])
        definition_sha256 = _sha256(row["definition_sha256"], "definition")
        if hashlib.sha256(definition).hexdigest() != definition_sha256:
            raise ValueError("analysis definition checksum drift")
        return StoredAnalysis(
            revision=_nonnegative_integer(row["revision"], "analysis revision"),
            definition_sha256=definition_sha256,
            newest_commit=_text(row["newest_commit"], "newest commit"),
            oldest_completed_commit=(
                None
                if row["oldest_completed_commit"] is None
                else _text(row["oldest_completed_commit"], "oldest completed commit")
            ),
            completed_pair_count=_nonnegative_integer(
                row["completed_pair_count"], "completed pair count"
            ),
            history_exhausted=_boolean(row["history_exhausted"], "history exhausted"),
        )

    def pending_batch(self) -> StoredBatch | None:
        rows = self.connection.execute(
            """
            SELECT batch_id, base_revision, target_kind, target_value,
                   manifest_sha256, oldest_commit, newest_commit, pair_count,
                   reaches_root, status
            FROM batches WHERE status = 'pending'
            """
        ).fetchall()
        if len(rows) > 1:
            raise ValueError("analysis database contains multiple pending batches")
        return None if not rows else _stored_batch(rows[0])

    def latest_manifest(self) -> FrozenAnalysisManifest:
        row = self.connection.execute(
            """
            SELECT batch_id, base_revision, target_kind, target_value,
                   manifest_json, manifest_sha256, oldest_commit, newest_commit,
                   pair_count, reaches_root, status
            FROM batches
            ORDER BY created_order DESC LIMIT 1
            """
        ).fetchone()
        if row is None:
            raise ValueError("analysis database contains no frozen batch manifest")
        batch = _stored_batch(row)
        manifest = self._manifest_from_row(row, batch)
        self._verify_batch_pairs(batch, manifest)
        return manifest

    def initial_manifest(self) -> FrozenAnalysisManifest:
        """Load the first batch, whose digest names the fixed retained Git ref."""

        row = self.connection.execute(
            """
            SELECT batch_id, base_revision, target_kind, target_value,
                   manifest_json, manifest_sha256, oldest_commit, newest_commit,
                   pair_count, reaches_root, status
            FROM batches
            ORDER BY created_order ASC LIMIT 1
            """
        ).fetchone()
        if row is None:
            raise ValueError("analysis database contains no initial batch manifest")
        batch = _stored_batch(row)
        manifest = self._manifest_from_row(row, batch)
        self._verify_batch_pairs(batch, manifest)
        return manifest

    def pending_manifest(self, batch: StoredBatch) -> FrozenAnalysisManifest:
        row = self.connection.execute(
            """
            SELECT batch_id, base_revision, target_kind, target_value,
                   manifest_json, manifest_sha256, oldest_commit, newest_commit,
                   pair_count, reaches_root, status
            FROM batches WHERE batch_id = ? AND status = 'pending'
            """,
            (batch.batch_id,),
        ).fetchone()
        if row is None:
            raise ValueError("pending analysis batch changed while being loaded")
        stored = _stored_batch(row)
        if stored != batch:
            raise ValueError("pending analysis batch metadata drift")
        manifest = self._manifest_from_row(row, batch)
        self._verify_batch_pairs(batch, manifest)
        return manifest

    def add_pending_batch(
        self,
        manifest: FrozenAnalysisManifest,
        *,
        batch_id: str,
        target_kind: str,
        target_value: str | None,
        reaches_root: bool,
        retention_policy: RetentionPolicy,
    ) -> StoredBatch:
        state = self.analysis()
        if state.history_exhausted:
            raise ValueError("analysis already reached the repository root")
        with self._transaction():
            self._insert_pending_batch(
                manifest,
                batch_id=batch_id,
                target_kind=target_kind,
                target_value=target_value,
                reaches_root=reaches_root,
                expected_revision=state.revision,
                retention_policy=retention_policy,
            )
        pending = self.pending_batch()
        if pending is None:
            raise RuntimeError("pending analysis batch was not published")
        return pending

    def _insert_pending_batch(
        self,
        manifest: FrozenAnalysisManifest,
        *,
        batch_id: str,
        target_kind: str,
        target_value: str | None,
        reaches_root: bool,
        expected_revision: int,
        retention_policy: RetentionPolicy,
    ) -> None:
        if self.pending_batch() is not None:
            raise ValueError("analysis already contains pending work")
        _validate_batch_id(batch_id)
        _validate_target(target_kind, target_value)
        if not isinstance(reaches_root, bool):
            raise ValueError("analysis batch reaches_root must be a Boolean")
        state = self.analysis()
        if state.revision != expected_revision:
            raise ValueError("analysis state revision changed before batch planning")
        boundary = state.oldest_completed_commit or state.newest_commit
        if manifest.commits[-1] != boundary:
            raise ValueError("new analysis batch does not start at the completed boundary")
        definition = _definition_bytes(manifest, retention_policy)
        if hashlib.sha256(definition).hexdigest() != state.definition_sha256:
            raise ValueError("analysis definition drift across batches")
        manifest_content = manifest.canonical_bytes()
        pair_count = len(manifest.commits) - 1
        created_order_row = self.connection.execute(
            "SELECT COALESCE(MAX(created_order), -1) + 1 AS value FROM batches"
        ).fetchone()
        assert created_order_row is not None
        created_order = int(created_order_row["value"])
        self.connection.execute(
            """
            INSERT INTO batches(
                batch_id, created_order, base_revision, target_kind, target_value,
                manifest_json, manifest_sha256, oldest_commit, newest_commit,
                pair_count, reaches_root, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
            """,
            (
                batch_id,
                created_order,
                expected_revision,
                target_kind,
                target_value,
                manifest_content,
                hashlib.sha256(manifest_content).hexdigest(),
                manifest.commits[0],
                manifest.commits[-1],
                pair_count,
                int(reaches_root),
            ),
        )
        completed_before = state.completed_pair_count
        for item in build_pair_work_items(manifest):
            distance = completed_before + pair_count - 1 - item.sequence
            self.connection.execute(
                """
                INSERT INTO pairs(
                    batch_id, batch_sequence, distance_from_newest,
                    old_commit, new_commit, pair_fingerprint, status
                ) VALUES (?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    batch_id,
                    item.sequence,
                    distance,
                    item.old_commit,
                    item.new_commit,
                    item.fingerprint,
                ),
            )
        changed = self.connection.execute(
            "UPDATE analysis SET revision = revision + 1 WHERE singleton = 1 AND revision = ?",
            (expected_revision,),
        ).rowcount
        if changed != 1:
            raise ValueError("analysis state revision changed during batch planning")

    def record_outcome(
        self,
        batch: StoredBatch,
        outcome: PairOutcome,
        *,
        invocation_id: str | None = None,
    ) -> None:
        item = outcome.work_item
        compact = compact_pair_outcome(outcome)
        if compact.status not in TERMINAL_PAIR_STATUSES:
            raise ValueError(f"pair outcome has non-terminal status: {compact.status!r}")
        row = self.connection.execute(
            """
            SELECT old_commit, new_commit, pair_fingerprint, status
            FROM pairs WHERE batch_id = ? AND batch_sequence = ?
            """,
            (batch.batch_id, item.sequence),
        ).fetchone()
        if row is None:
            raise ValueError("pair outcome is not part of the pending batch")
        expected = (row["old_commit"], row["new_commit"], row["pair_fingerprint"])
        observed = (item.old_commit, item.new_commit, item.fingerprint)
        if observed != expected:
            raise ValueError("pair outcome identity drift from pending batch")
        with self._transaction():
            changed = self.connection.execute(
                """
                UPDATE pairs
                SET status = ?, changed_path_count = ?, analyzable_path_count = ?,
                    metrics_json = ?, timings_json = ?, error = ?,
                    evidence_json = ?, results_size_bytes = ?, results_sha256 = ?
                WHERE batch_id = ? AND batch_sequence = ? AND status IS NULL
                """,
                (
                    compact.status,
                    compact.changed_path_count,
                    compact.analyzable_path_count,
                    compact.metrics_json,
                    compact.timings_json,
                    compact.error,
                    compact.evidence_json,
                    compact.results_size_bytes,
                    compact.results_sha256,
                    batch.batch_id,
                    item.sequence,
                ),
            ).rowcount
            if changed != 1:
                raise ValueError("pair outcome was already sealed or is not pending")
            for move in compact.moves:
                self.connection.execute(
                    """
                    INSERT INTO moves(
                        batch_id, batch_sequence, move_ordinal, match_kind,
                        from_xpaths_json, to_xpaths_json,
                        from_text_digests_json, to_text_digests_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        batch.batch_id,
                        item.sequence,
                        move.ordinal,
                        move.match_kind,
                        move.from_xpaths_json,
                        move.to_xpaths_json,
                        move.from_text_digests_json,
                        move.to_text_digests_json,
                    ),
                )
            if invocation_id is not None:
                _validate_invocation_id(invocation_id)
                changed = self.connection.execute(
                    """
                    UPDATE invocations SET last_durable_at = ?
                    WHERE invocation_id = ? AND result = 'running'
                    """,
                    (_utc_now(), invocation_id),
                ).rowcount
                if changed != 1:
                    raise ValueError("pair outcome has no running invocation")

    def completed_prefix(self, batch: StoredBatch) -> int:
        rows = self.connection.execute(
            """
            SELECT batch_sequence, status FROM pairs
            WHERE batch_id = ? ORDER BY batch_sequence
            """,
            (batch.batch_id,),
        ).fetchall()
        prefix = 0
        found_pending = False
        for expected, row in enumerate(rows):
            if row["batch_sequence"] != expected:
                raise ValueError("pending batch pair sequence drift")
            if row["status"] is None:
                found_pending = True
            elif found_pending:
                raise ValueError("pending batch contains a noncontiguous sealed prefix")
            else:
                prefix += 1
        if len(rows) != batch.pair_count:
            raise ValueError("pending batch pair count drift")
        return prefix

    def commit_pending_batch(self, batch: StoredBatch) -> StoredAnalysis:
        state = self.analysis()
        if state.revision != batch.base_revision + 1:
            raise ValueError("analysis revision drift from pending batch")
        if self.completed_prefix(batch) != batch.pair_count:
            raise ValueError("analysis batch is not complete")
        manifest = self.pending_manifest(batch)
        if manifest.commits[0] != batch.oldest_commit:
            raise ValueError("pending batch oldest boundary drift")
        with self._transaction():
            changed = self.connection.execute(
                "UPDATE batches SET status = 'completed' WHERE batch_id = ? AND status = 'pending'",
                (batch.batch_id,),
            ).rowcount
            if changed != 1:
                raise ValueError("pending analysis batch changed before commit")
            changed = self.connection.execute(
                """
                UPDATE analysis
                SET revision = revision + 1,
                    oldest_completed_commit = ?,
                    completed_pair_count = completed_pair_count + ?,
                    history_exhausted = ?
                WHERE singleton = 1 AND revision = ?
                """,
                (
                    batch.oldest_commit,
                    batch.pair_count,
                    int(batch.reaches_root),
                    state.revision,
                ),
            ).rowcount
            if changed != 1:
                raise ValueError("analysis revision changed during batch commit")
        return self.analysis()

    def summary(self) -> dict[str, Any]:
        """Derive a compact current summary from committed database rows."""

        statuses: Counter[str] = Counter()
        timings: Counter[str] = Counter()
        totals: Counter[str] = Counter()
        rows = self.connection.execute(
            """
            SELECT p.status, p.changed_path_count, p.analyzable_path_count,
                   p.metrics_json, p.timings_json
            FROM pairs AS p
            JOIN batches AS b ON b.batch_id = p.batch_id
            WHERE b.status = 'completed'
            ORDER BY p.distance_from_newest DESC
            """
        )
        selected_pairs = 0
        for row in rows:
            status = _text(row["status"], "pair status")
            if status not in TERMINAL_PAIR_STATUSES:
                raise ValueError(f"unknown stored pair status: {status!r}")
            statuses[status] += 1
            selected_pairs += 1
            metrics = _json_object(bytes(row["metrics_json"]), "pair metrics")
            pair_timings = _json_object(bytes(row["timings_json"]), "pair timings")
            for name in (
                "move_count",
                "move_group_count",
                "move_pair_count",
                "annotated_region_count",
            ):
                value = metrics.get(name, 0)
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    raise ValueError(f"stored pair metric {name!r} is malformed")
                totals[name] += value
            for name, value in pair_timings.items():
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                    or value < 0
                ):
                    raise ValueError(f"stored pair timing {name!r} is malformed")
                timings[name] += float(value)
        state = self.analysis()
        if selected_pairs != state.completed_pair_count:
            raise ValueError("completed analysis coverage drifts from stored pairs")
        return {
            "schema_version": DATABASE_SCHEMA_VERSION,
            "revision": state.revision,
            "completed_pair_count": selected_pairs,
            "oldest_completed_commit": state.oldest_completed_commit,
            "newest_commit": state.newest_commit,
            "history_exhausted": state.history_exhausted,
            "completed": statuses["completed"],
            "no_analyzable_change": statuses["no_analyzable_change"],
            "failed": sum(
                statuses[name]
                for name in TERMINAL_PAIR_STATUSES
                if name.endswith("_failed")
            ),
            "statuses": dict(sorted(statuses.items())),
            "move_count": totals["move_count"],
            "move_group_count": totals["move_group_count"],
            "move_pair_count": totals["move_pair_count"],
            "annotated_region_count": totals["annotated_region_count"],
            "timings": dict(sorted(timings.items())),
        }

    def pair_details(self, distance_from_newest: int) -> dict[str, Any]:
        """Load compact evidence for one committed pair without regenerating it."""

        distance = _nonnegative_integer(
            distance_from_newest, "distance from newest"
        )
        row = self.connection.execute(
            """
            SELECT p.batch_id, p.batch_sequence, p.old_commit, p.new_commit,
                   p.pair_fingerprint, p.status, p.changed_path_count,
                   p.analyzable_path_count, p.metrics_json, p.timings_json,
                   p.error, p.evidence_json, p.results_size_bytes,
                   p.results_sha256
            FROM pairs AS p
            JOIN batches AS b ON b.batch_id = p.batch_id
            WHERE p.distance_from_newest = ? AND b.status = 'completed'
            """,
            (distance,),
        ).fetchone()
        if row is None:
            raise ValueError(
                f"no committed pair exists at distance {distance} from newest"
            )
        metrics = _json_object(bytes(row["metrics_json"]), "pair metrics")
        moves = []
        move_rows = self.connection.execute(
            """
            SELECT move_ordinal, match_kind, from_xpaths_json, to_xpaths_json,
                   from_text_digests_json, to_text_digests_json
            FROM moves WHERE batch_id = ? AND batch_sequence = ?
            ORDER BY move_ordinal
            """,
            (row["batch_id"], row["batch_sequence"]),
        )
        for expected_ordinal, move in enumerate(move_rows):
            if move["move_ordinal"] != expected_ordinal:
                raise ValueError("stored move ordinal sequence drift")
            moves.append(
                {
                    "ordinal": expected_ordinal,
                    "match_kind": _text(move["match_kind"], "move match kind"),
                    "from_xpaths": _json_array(
                        bytes(move["from_xpaths_json"]), "move from xpaths"
                    ),
                    "to_xpaths": _json_array(
                        bytes(move["to_xpaths_json"]), "move to xpaths"
                    ),
                    "from_text_digests": _json_array(
                        bytes(move["from_text_digests_json"]),
                        "move from text digests",
                    ),
                    "to_text_digests": _json_array(
                        bytes(move["to_text_digests_json"]),
                        "move to text digests",
                    ),
                }
            )
        if metrics.get("move_count", 0) != len(moves):
            raise ValueError("stored move rows drift from pair move count")
        evidence = row["evidence_json"]
        return {
            "distance_from_newest": distance,
            "old_commit": _text(row["old_commit"], "old commit"),
            "new_commit": _text(row["new_commit"], "new commit"),
            "pair_fingerprint": _text(
                row["pair_fingerprint"], "pair fingerprint"
            ),
            "status": _text(row["status"], "pair status"),
            "changed_path_count": _nonnegative_integer(
                row["changed_path_count"], "changed path count"
            ),
            "analyzable_path_count": _nonnegative_integer(
                row["analyzable_path_count"], "analyzable path count"
            ),
            "metrics": metrics,
            "timings": _json_object(bytes(row["timings_json"]), "pair timings"),
            "error": row["error"],
            "failure_evidence": (
                None
                if evidence is None
                else _json_object(bytes(evidence), "pair failure evidence")
            ),
            "results_observation": (
                None
                if row["results_sha256"] is None
                else {
                    "size_bytes": _nonnegative_integer(
                        row["results_size_bytes"], "results size"
                    ),
                    "sha256": _sha256(row["results_sha256"], "results"),
                }
            ),
            "moves": moves,
        }

    def _manifest_from_row(
        self, row: sqlite3.Row, batch: StoredBatch
    ) -> FrozenAnalysisManifest:
        content = bytes(row["manifest_json"])
        if hashlib.sha256(content).hexdigest() != batch.manifest_sha256:
            raise ValueError("analysis batch manifest checksum drift")
        manifest = load_frozen_manifest_bytes(
            content, context=f"analysis batch {batch.batch_id}"
        )
        if (
            manifest.commits[0] != batch.oldest_commit
            or manifest.commits[-1] != batch.newest_commit
            or len(manifest.commits) - 1 != batch.pair_count
        ):
            raise ValueError("analysis batch metadata drift from frozen manifest")
        return manifest

    def _verify_batch_pairs(
        self, batch: StoredBatch, manifest: FrozenAnalysisManifest
    ) -> None:
        rows = self.connection.execute(
            """
            SELECT batch_sequence, old_commit, new_commit, pair_fingerprint
            FROM pairs WHERE batch_id = ? ORDER BY batch_sequence
            """,
            (batch.batch_id,),
        )
        expected = build_pair_work_items(manifest)
        count = 0
        for count, (row, item) in enumerate(zip(rows, expected), start=1):
            if (
                row["batch_sequence"] != item.sequence
                or row["old_commit"] != item.old_commit
                or row["new_commit"] != item.new_commit
                or row["pair_fingerprint"] != item.fingerprint
            ):
                raise ValueError("analysis batch pair identity drift")
        if count != len(expected) or next(rows, None) is not None:
            raise ValueError("analysis batch pair count drift")

    @contextmanager
    def _transaction(self):
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise
        else:
            try:
                self.connection.execute("COMMIT")
            except BaseException:
                if self.connection.in_transaction:
                    self.connection.execute("ROLLBACK")
                raise

    def _verify_schema(self) -> None:
        application_id = int(
            self.connection.execute("PRAGMA application_id").fetchone()[0]
        )
        version = int(self.connection.execute("PRAGMA user_version").fetchone()[0])
        if application_id != DATABASE_APPLICATION_ID:
            raise ValueError("file is not a repository-analysis database")
        if version != DATABASE_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported analysis database schema: {version}; "
                "start a fresh analysis root"
            )


def analysis_database_exists(analysis_root: Path) -> bool:
    path = analysis_root.expanduser().absolute() / DATABASE_NAME
    return path.exists() or path.is_symlink()


def _definition_bytes(
    manifest: FrozenAnalysisManifest, retention_policy: RetentionPolicy
) -> bytes:
    return canonical_json_bytes(
        {
            "repository_path": str(manifest.repository),
            "repository_identity": manifest.repository_identity.record(),
            "configuration": manifest.configuration.record(),
            "executables": {
                "srcdiff": {
                    "size_bytes": manifest.srcdiff.size_bytes,
                    "sha256": manifest.srcdiff.sha256,
                },
                "srcmove": {
                    "size_bytes": manifest.srcmove.size_bytes,
                    "sha256": manifest.srcmove.sha256,
                },
            },
            "fingerprint_schema_versions": manifest.schema_versions.record(),
            "retention_policy": retention_policy.record(),
        }
    )


def _stored_batch(row: sqlite3.Row) -> StoredBatch:
    status = _text(row["status"], "batch status")
    if status not in {"pending", "completed"}:
        raise ValueError(f"unknown analysis batch status: {status!r}")
    target_kind = _text(row["target_kind"], "target kind")
    target_value = row["target_value"]
    if target_value is not None:
        target_value = _text(target_value, "target value")
    _validate_target(target_kind, target_value)
    return StoredBatch(
        batch_id=_text(row["batch_id"], "batch ID"),
        base_revision=_nonnegative_integer(row["base_revision"], "base revision"),
        target_kind=target_kind,
        target_value=target_value,
        manifest_sha256=_sha256(row["manifest_sha256"], "manifest"),
        oldest_commit=_text(row["oldest_commit"], "oldest commit"),
        newest_commit=_text(row["newest_commit"], "newest commit"),
        pair_count=_positive_integer(row["pair_count"], "batch pair count"),
        reaches_root=_boolean(row["reaches_root"], "reaches root"),
        status=status,
    )


def _stored_invocation(row: sqlite3.Row) -> StoredInvocation:
    result = _text(row["result"], "invocation result")
    if result not in INVOCATION_RESULTS:
        raise ValueError(f"unknown invocation result: {result!r}")
    target_kind = _text(row["target_kind"], "invocation target kind")
    target_value = row["target_value"]
    if target_value is not None:
        target_value = _text(target_value, "invocation target value")
    _validate_target(target_kind, target_value)
    wall_seconds = row["wall_seconds"]
    if wall_seconds is not None:
        if (
            isinstance(wall_seconds, bool)
            or not isinstance(wall_seconds, (int, float))
            or not math.isfinite(wall_seconds)
            or wall_seconds < 0
        ):
            raise ValueError("stored invocation wall time is malformed")
        wall_seconds = float(wall_seconds)
    return StoredInvocation(
        invocation_id=_text(row["invocation_id"], "invocation ID"),
        created_order=_nonnegative_integer(
            row["created_order"], "invocation order"
        ),
        target_kind=target_kind,
        target_value=target_value,
        jobs=_positive_integer(row["jobs"], "invocation jobs"),
        started_at=_text(row["started_at"], "invocation start time"),
        last_durable_at=_text(
            row["last_durable_at"], "invocation last durable time"
        ),
        ended_at=(
            None
            if row["ended_at"] is None
            else _text(row["ended_at"], "invocation end time")
        ),
        result=result,
        wall_seconds=wall_seconds,
        error=(
            None
            if row["error"] is None
            else _text(row["error"], "invocation error")
        ),
    )


def _owned_root(analysis_root: Path) -> Path:
    requested = analysis_root.expanduser().absolute()
    if requested.is_symlink():
        raise ValueError(f"analysis root must not be a symbolic link: {requested}")
    requested.mkdir(parents=True, exist_ok=True)
    root = requested.resolve()
    if root.is_symlink() or not root.is_dir():
        raise ValueError(f"analysis root is not an owned directory: {root}")
    return root


def _existing_owned_root(analysis_root: Path) -> Path:
    requested = analysis_root.expanduser().absolute()
    if requested.is_symlink() or not requested.is_dir():
        raise ValueError(f"analysis root is not an owned directory: {requested}")
    root = requested.resolve()
    if root.is_symlink() or not root.is_dir():
        raise ValueError(f"analysis root is not an owned directory: {root}")
    return root


def _require_owned_database(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"analysis database is not a regular file: {path}")
    metadata = path.stat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise ValueError(f"analysis database must be one owned regular file: {path}")


def _recover_interrupted_publication(root: Path, path: Path) -> None:
    """Remove our exact temporary hard link after an interrupted first publish."""

    if path.is_symlink() or not path.is_file():
        return
    metadata = path.stat()
    if metadata.st_nlink == 1:
        return
    matches: list[Path] = []
    prefix = f".{DATABASE_NAME}.tmp-"
    with os.scandir(root) as entries:
        for entry in entries:
            if not entry.name.startswith(prefix) or entry.is_symlink():
                continue
            candidate = root / entry.name
            candidate_metadata = candidate.stat()
            if (
                candidate_metadata.st_dev,
                candidate_metadata.st_ino,
            ) == (metadata.st_dev, metadata.st_ino):
                matches.append(candidate)
    if metadata.st_nlink != 2 or len(matches) != 1:
        raise ValueError(
            f"analysis database has unexpected hard-link ownership: {path}"
        )
    matches[0].unlink()
    _fsync_directory(root)


def _validate_batch_id(value: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 32
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError("analysis batch ID must be 32 lowercase hexadecimal digits")


def _validate_invocation_id(value: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 32
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(
            "analysis invocation ID must be 32 lowercase hexadecimal digits"
        )


def _validate_target(kind: str, value: str | None) -> None:
    if kind not in TARGET_KINDS:
        raise ValueError(f"unknown analysis target kind: {kind!r}")
    if kind == "all" and value is not None:
        raise ValueError("all-history target must not have a value")
    if kind != "all" and (not isinstance(value, str) or not value):
        raise ValueError(f"{kind} target requires a value")
    if kind == "total_pairs":
        assert value is not None
        try:
            count = int(value)
        except ValueError as error:
            raise ValueError("total-pairs target must be a positive integer") from error
        if count <= 0 or str(count) != value:
            raise ValueError("total-pairs target must be a canonical positive integer")


def _text(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value or "\0" in value:
        raise ValueError(f"{context} must be a non-empty string")
    return value


def _json_object(content: bytes, context: str) -> dict[str, Any]:
    try:
        value = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{context} is unreadable") from error
    if not isinstance(value, dict) or canonical_json_bytes(value) != content:
        raise ValueError(f"{context} is not a canonical JSON object")
    return value


def _json_array(content: bytes, context: str) -> list[Any]:
    try:
        value = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{context} is unreadable") from error
    if not isinstance(value, list) or canonical_json_bytes(value) != content:
        raise ValueError(f"{context} is not a canonical JSON array")
    return value


def _sha256(value: Any, context: str) -> str:
    text = _text(value, context)
    if len(text) != 64 or any(
        character not in "0123456789abcdef" for character in text
    ):
        raise ValueError(f"{context} SHA-256 is malformed")
    return text


def _nonnegative_integer(value: Any, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{context} must be a non-negative integer")
    return value


def _positive_integer(value: Any, context: str) -> int:
    result = _nonnegative_integer(value, context)
    if result == 0:
        raise ValueError(f"{context} must be positive")
    return result


def _boolean(value: Any, context: str) -> bool:
    if value not in (0, 1):
        raise ValueError(f"{context} must be a SQLite Boolean")
    return bool(value)


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_file(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


_SCHEMA = """
CREATE TABLE analysis (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    revision INTEGER NOT NULL CHECK (revision >= 0),
    definition_json BLOB NOT NULL,
    definition_sha256 TEXT NOT NULL,
    newest_commit TEXT NOT NULL,
    oldest_completed_commit TEXT,
    completed_pair_count INTEGER NOT NULL CHECK (completed_pair_count >= 0),
    history_exhausted INTEGER NOT NULL CHECK (history_exhausted IN (0, 1))
) STRICT;

CREATE TABLE batches (
    batch_id TEXT PRIMARY KEY,
    created_order INTEGER NOT NULL UNIQUE CHECK (created_order >= 0),
    base_revision INTEGER NOT NULL CHECK (base_revision >= 0),
    target_kind TEXT NOT NULL CHECK (target_kind IN ('total_pairs', 'through', 'all')),
    target_value TEXT,
    manifest_json BLOB NOT NULL,
    manifest_sha256 TEXT NOT NULL,
    oldest_commit TEXT NOT NULL,
    newest_commit TEXT NOT NULL,
    pair_count INTEGER NOT NULL CHECK (pair_count > 0),
    reaches_root INTEGER NOT NULL CHECK (reaches_root IN (0, 1)),
    status TEXT NOT NULL CHECK (status IN ('pending', 'completed'))
) STRICT;

CREATE UNIQUE INDEX one_pending_batch
ON batches(status) WHERE status = 'pending';

CREATE TABLE invocations (
    invocation_id TEXT PRIMARY KEY,
    created_order INTEGER NOT NULL UNIQUE CHECK (created_order >= 0),
    target_kind TEXT NOT NULL CHECK (target_kind IN ('total_pairs', 'through', 'all')),
    target_value TEXT,
    jobs INTEGER NOT NULL CHECK (jobs > 0),
    started_at TEXT NOT NULL,
    last_durable_at TEXT NOT NULL,
    ended_at TEXT,
    result TEXT NOT NULL CHECK (
        result IN (
            'running', 'target_reached', 'target_reached_with_failures',
            'failed', 'interrupted'
        )
    ),
    wall_seconds REAL CHECK (wall_seconds >= 0),
    error TEXT,
    CHECK (
        (result = 'running' AND ended_at IS NULL AND wall_seconds IS NULL) OR
        (result <> 'running' AND ended_at IS NOT NULL)
    )
) STRICT;

CREATE UNIQUE INDEX one_running_invocation
ON invocations(result) WHERE result = 'running';

CREATE TABLE pairs (
    batch_id TEXT NOT NULL REFERENCES batches(batch_id),
    batch_sequence INTEGER NOT NULL CHECK (batch_sequence >= 0),
    distance_from_newest INTEGER NOT NULL UNIQUE CHECK (distance_from_newest >= 0),
    old_commit TEXT NOT NULL,
    new_commit TEXT NOT NULL,
    pair_fingerprint TEXT NOT NULL UNIQUE,
    status TEXT CHECK (
        status IS NULL OR status IN (
            'completed', 'no_analyzable_change', 'export_failed',
            'srcdiff_failed', 'srcmove_failed', 'orchestration_failed'
        )
    ),
    changed_path_count INTEGER CHECK (changed_path_count >= 0),
    analyzable_path_count INTEGER CHECK (analyzable_path_count >= 0),
    metrics_json BLOB,
    timings_json BLOB,
    error TEXT,
    evidence_json BLOB,
    results_size_bytes INTEGER CHECK (results_size_bytes >= 0),
    results_sha256 TEXT,
    PRIMARY KEY (batch_id, batch_sequence),
    CHECK (
        (
            status IS NULL AND changed_path_count IS NULL AND
            analyzable_path_count IS NULL AND metrics_json IS NULL AND
            timings_json IS NULL AND error IS NULL AND evidence_json IS NULL AND
            results_size_bytes IS NULL AND results_sha256 IS NULL
        ) OR (
            status IS NOT NULL AND changed_path_count IS NOT NULL AND
            analyzable_path_count IS NOT NULL AND metrics_json IS NOT NULL AND
            timings_json IS NOT NULL
        )
    )
) STRICT;

CREATE TABLE moves (
    batch_id TEXT NOT NULL,
    batch_sequence INTEGER NOT NULL,
    move_ordinal INTEGER NOT NULL CHECK (move_ordinal >= 0),
    match_kind TEXT NOT NULL,
    from_xpaths_json BLOB NOT NULL,
    to_xpaths_json BLOB NOT NULL,
    from_text_digests_json BLOB NOT NULL,
    to_text_digests_json BLOB NOT NULL,
    PRIMARY KEY (batch_id, batch_sequence, move_ordinal),
    FOREIGN KEY (batch_id, batch_sequence)
        REFERENCES pairs(batch_id, batch_sequence)
) STRICT;
"""
