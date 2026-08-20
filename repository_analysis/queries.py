"""Immutable read models for one repository analysis snapshot."""

from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeAlias

from .database import (
    TERMINAL_PAIR_STATUSES,
    AnalysisDatabase,
    StoredInvocation,
)
from .inputs import canonical_json_bytes


QUERY_SCHEMA_VERSION = 1
FAILURE_PAIR_STATUSES = tuple(
    sorted(status for status in TERMINAL_PAIR_STATUSES if status.endswith("_failed"))
)

FrozenScalar: TypeAlias = None | bool | int | float | str


@dataclass(frozen=True, slots=True)
class FrozenObject:
    items: tuple[tuple[str, "FrozenJson"], ...]


@dataclass(frozen=True, slots=True)
class FrozenArray:
    items: tuple["FrozenJson", ...]


FrozenJson: TypeAlias = FrozenScalar | FrozenObject | FrozenArray


@dataclass(frozen=True, slots=True)
class NamedCount:
    name: str
    count: int


@dataclass(frozen=True, slots=True)
class NamedSeconds:
    name: str
    seconds: float


@dataclass(frozen=True, slots=True)
class CoverageSnapshot:
    committed: int
    checkpointed: int

    @property
    def durable(self) -> int:
        return self.committed + self.checkpointed


@dataclass(frozen=True, slots=True)
class MoveCounts:
    moves: int
    groups: int
    pairs: int
    annotated_regions: int


@dataclass(frozen=True, slots=True)
class PendingSnapshot:
    batch_id: str
    pair_count: int
    completed_prefix: int
    target_kind: str
    target_value: str | None


@dataclass(frozen=True, slots=True)
class InvocationSnapshot:
    invocation_id: str
    target_kind: str
    target_value: str | None
    jobs: int
    started_at: str
    last_durable_at: str
    ended_at: str | None
    result: str
    wall_seconds: float | None
    error: str | None

    @classmethod
    def from_stored(cls, invocation: StoredInvocation) -> "InvocationSnapshot":
        return cls(**invocation.record())

    def record(self) -> dict[str, Any]:
        return {
            field: getattr(self, field)
            for field in self.__dataclass_fields__
        }


@dataclass(frozen=True, slots=True)
class StatusSnapshot:
    schema_version: int
    revision: int
    coverage: CoverageSnapshot
    oldest_completed_commit: str | None
    newest_commit: str
    history_exhausted: bool
    statuses: tuple[NamedCount, ...]
    moves: MoveCounts
    timings: tuple[NamedSeconds, ...]
    pending: PendingSnapshot | None
    invocation: InvocationSnapshot | None

    def record(self) -> dict[str, Any]:
        statuses = {item.name: item.count for item in self.statuses}
        return {
            "schema_version": self.schema_version,
            "revision": self.revision,
            "completed_pair_count": self.coverage.committed,
            "checkpointed_pair_count": self.coverage.checkpointed,
            "durable_pair_count": self.coverage.durable,
            "oldest_completed_commit": self.oldest_completed_commit,
            "newest_commit": self.newest_commit,
            "history_exhausted": self.history_exhausted,
            "completed": statuses.get("completed", 0),
            "no_analyzable_change": statuses.get("no_analyzable_change", 0),
            "failed": sum(
                count for name, count in statuses.items() if name.endswith("_failed")
            ),
            "statuses": statuses,
            "move_count": self.moves.moves,
            "move_group_count": self.moves.groups,
            "move_pair_count": self.moves.pairs,
            "annotated_region_count": self.moves.annotated_regions,
            "timings": {item.name: item.seconds for item in self.timings},
            "pending": (
                None
                if self.pending is None
                else {
                    field: getattr(self.pending, field)
                    for field in self.pending.__dataclass_fields__
                }
            ),
            "invocation": (
                None if self.invocation is None else self.invocation.record()
            ),
        }


@dataclass(frozen=True, slots=True)
class PairListItem:
    number: int
    distance_from_newest: int
    old_commit: str
    new_commit: str
    status: str
    changed_path_count: int
    analyzable_path_count: int
    move_count: int
    elapsed_seconds: float
    checkpointed: bool
    invocation_id: str

    def record(self) -> dict[str, Any]:
        return {
            field: getattr(self, field)
            for field in self.__dataclass_fields__
        }


@dataclass(frozen=True, slots=True)
class PairPage:
    items: tuple[PairListItem, ...]
    next_cursor: int | None

    def record(self) -> dict[str, Any]:
        return {
            "items": [item.record() for item in self.items],
            "next_cursor": self.next_cursor,
        }


@dataclass(frozen=True, slots=True)
class PairDetailSnapshot:
    number: int
    distance_from_newest: int
    old_commit: str
    new_commit: str
    pair_fingerprint: str
    status: str
    invocation_id: str
    changed_path_count: int
    analyzable_path_count: int
    metrics: FrozenJson
    timings: FrozenJson
    error: str | None
    failure_evidence: FrozenJson
    results_observation: FrozenJson
    moves: FrozenJson

    def record(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "distance_from_newest": self.distance_from_newest,
            "old_commit": self.old_commit,
            "new_commit": self.new_commit,
            "pair_fingerprint": self.pair_fingerprint,
            "status": self.status,
            "invocation_id": self.invocation_id,
            "changed_path_count": self.changed_path_count,
            "analyzable_path_count": self.analyzable_path_count,
            "metrics": _thaw_json(self.metrics),
            "timings": _thaw_json(self.timings),
            "error": self.error,
            "failure_evidence": _thaw_json(self.failure_evidence),
            "results_observation": _thaw_json(self.results_observation),
            "moves": _thaw_json(self.moves),
        }


class AnalysisReader:
    """Read one self-consistent snapshot without taking the writer lock."""

    def __init__(self, analysis_root: Path) -> None:
        self.analysis_root = analysis_root

    def status(self) -> StatusSnapshot:
        with AnalysisDatabase.open(self.analysis_root, read_only=True) as database:
            with database.read_snapshot():
                state = database.analysis()
                pending = database.pending_batch()
                rows = database.connection.execute(
                    """
                    SELECT p.status, p.metrics_json, p.timings_json,
                           b.status AS batch_status
                    FROM pairs AS p
                    JOIN batches AS b ON b.batch_id = p.batch_id
                    WHERE p.status IS NOT NULL
                    ORDER BY p.distance_from_newest
                    """
                )
                statuses: Counter[str] = Counter()
                totals: Counter[str] = Counter()
                timings: Counter[str] = Counter()
                checkpointed = 0
                for row in rows:
                    status = _terminal_status(row["status"])
                    statuses[status] += 1
                    checkpointed += row["batch_status"] == "pending"
                    metrics = _json_object(row["metrics_json"], "pair metrics")
                    pair_timings = _json_object(row["timings_json"], "pair timings")
                    for name in (
                        "move_count", "move_group_count", "move_pair_count",
                        "annotated_region_count",
                    ):
                        totals[name] += _count(metrics.get(name, 0), name)
                    for name, value in pair_timings.items():
                        timings[name] += _seconds(value, name)
                if sum(statuses.values()) != state.completed_pair_count + checkpointed:
                    raise ValueError(
                        "durable analysis coverage drifts from stored pairs"
                    )
                stored_invocation = database.latest_invocation()
                return StatusSnapshot(
                    schema_version=QUERY_SCHEMA_VERSION,
                    revision=state.revision,
                    coverage=CoverageSnapshot(state.completed_pair_count, checkpointed),
                    oldest_completed_commit=state.oldest_completed_commit,
                    newest_commit=state.newest_commit,
                    history_exhausted=state.history_exhausted,
                    statuses=tuple(
                        NamedCount(name, count)
                        for name, count in sorted(statuses.items())
                    ),
                    moves=MoveCounts(
                        totals["move_count"], totals["move_group_count"],
                        totals["move_pair_count"], totals["annotated_region_count"],
                    ),
                    timings=tuple(
                        NamedSeconds(name, seconds)
                        for name, seconds in sorted(timings.items())
                    ),
                    pending=(
                        None if pending is None else PendingSnapshot(
                            pending.batch_id, pending.pair_count,
                            database.completed_prefix(pending), pending.target_kind,
                            pending.target_value,
                        )
                    ),
                    invocation=(
                        None if stored_invocation is None
                        else InvocationSnapshot.from_stored(stored_invocation)
                    ),
                )

    def list_pairs(
        self,
        *,
        status: str | None = None,
        failed: bool = False,
        with_moves: bool = False,
        limit: int = 50,
        after_distance: int | None = None,
        oldest_first: bool = False,
    ) -> PairPage:
        if status is not None and status not in TERMINAL_PAIR_STATUSES:
            raise ValueError(f"unknown pair status: {status!r}")
        for value, name in (
            (failed, "failed"),
            (with_moves, "with_moves"),
            (oldest_first, "oldest_first"),
        ):
            if not isinstance(value, bool):
                raise ValueError(f"{name} must be a Boolean")
        if sum((status is not None, failed, with_moves)) > 1:
            raise ValueError("status, failed, and with_moves filters are exclusive")
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 1000
        ):
            raise ValueError("pair list limit must be between 1 and 1000")
        if after_distance is not None and (
            isinstance(after_distance, bool) or not isinstance(after_distance, int)
            or after_distance < 0
        ):
            raise ValueError("pair list cursor must be a nonnegative integer")
        clauses = ["p.status IS NOT NULL"]
        parameters: list[Any] = []
        if status is not None:
            clauses.append("p.status = ?")
            parameters.append(status)
        elif failed:
            placeholders = ", ".join("?" for _ in FAILURE_PAIR_STATUSES)
            clauses.append(f"p.status IN ({placeholders})")
            parameters.extend(FAILURE_PAIR_STATUSES)
        if with_moves:
            clauses.append(
                "EXISTS (SELECT 1 FROM moves AS m WHERE "
                "m.batch_id = p.batch_id AND m.batch_sequence = p.batch_sequence)"
            )
        direction = "DESC" if oldest_first else "ASC"
        if after_distance is not None:
            clauses.append(f"p.distance_from_newest {'<' if oldest_first else '>'} ?")
            parameters.append(after_distance)
        parameters.append(limit + 1)
        sql = f"""
            SELECT p.distance_from_newest, p.old_commit, p.new_commit, p.status,
                   p.changed_path_count, p.analyzable_path_count, p.metrics_json,
                   p.timings_json, p.outcome_invocation_id,
                   b.status AS batch_status
            FROM pairs AS p
            JOIN batches AS b ON b.batch_id = p.batch_id
            WHERE {' AND '.join(clauses)}
            ORDER BY p.distance_from_newest {direction}
            LIMIT ?
        """
        with AnalysisDatabase.open(self.analysis_root, read_only=True) as database:
            with database.read_snapshot():
                rows = database.connection.execute(sql, parameters).fetchall()
        has_more = len(rows) > limit
        rows = rows[:limit]
        items = tuple(_pair_list_item(row) for row in rows)
        return PairPage(
            items,
            items[-1].distance_from_newest if has_more and items else None,
        )

    def show(self, number: int) -> PairDetailSnapshot:
        if isinstance(number, bool) or not isinstance(number, int) or number <= 0:
            raise ValueError("pair number must be a positive integer")
        with AnalysisDatabase.open(self.analysis_root, read_only=True) as database:
            with database.read_snapshot():
                detail = database.pair_details(number - 1)
        return PairDetailSnapshot(
            number=number,
            distance_from_newest=detail["distance_from_newest"],
            old_commit=detail["old_commit"],
            new_commit=detail["new_commit"],
            pair_fingerprint=detail["pair_fingerprint"],
            status=detail["status"],
            invocation_id=detail["invocation_id"],
            changed_path_count=detail["changed_path_count"],
            analyzable_path_count=detail["analyzable_path_count"],
            metrics=_freeze_json(detail["metrics"]),
            timings=_freeze_json(detail["timings"]),
            error=detail["error"],
            failure_evidence=_freeze_json(detail["failure_evidence"]),
            results_observation=_freeze_json(detail["results_observation"]),
            moves=_freeze_json(detail["moves"]),
        )


def _pair_list_item(row: Any) -> PairListItem:
    distance = _count(row["distance_from_newest"], "distance from newest")
    metrics = _json_object(row["metrics_json"], "pair metrics")
    timings = _json_object(row["timings_json"], "pair timings")
    return PairListItem(
        number=distance + 1,
        distance_from_newest=distance,
        old_commit=_text(row["old_commit"], "old commit"),
        new_commit=_text(row["new_commit"], "new commit"),
        status=_terminal_status(row["status"]),
        changed_path_count=_count(row["changed_path_count"], "changed paths"),
        analyzable_path_count=_count(
            row["analyzable_path_count"], "analyzable paths"
        ),
        move_count=_count(metrics.get("move_count", 0), "move count"),
        elapsed_seconds=_seconds(timings.get("pair_seconds", 0.0), "pair_seconds"),
        checkpointed=row["batch_status"] == "pending",
        invocation_id=_text(row["outcome_invocation_id"], "outcome invocation ID"),
    )


def _json_object(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, bytes):
        raise ValueError(f"stored {context} is malformed")
    try:
        result = json.loads(value)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"stored {context} is unreadable") from error
    if not isinstance(result, dict) or canonical_json_bytes(result) != value:
        raise ValueError(f"stored {context} is not a canonical object")
    return result


def _terminal_status(value: Any) -> str:
    status = _text(value, "pair status")
    if status not in TERMINAL_PAIR_STATUSES:
        raise ValueError(f"unknown stored pair status: {status!r}")
    return status


def _text(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value or "\0" in value:
        raise ValueError(f"stored {context} is malformed")
    return value


def _count(value: Any, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"stored {context} is malformed")
    return value


def _seconds(value: Any, context: str) -> float:
    if (
        isinstance(value, bool) or not isinstance(value, (int, float))
        or not math.isfinite(value) or value < 0
    ):
        raise ValueError(f"stored timing {context!r} is malformed")
    return float(value)


def _freeze_json(value: Any) -> FrozenJson:
    if isinstance(value, dict):
        return FrozenObject(
            tuple(
                (str(key), _freeze_json(item))
                for key, item in sorted(value.items())
            )
        )
    if isinstance(value, list):
        return FrozenArray(tuple(_freeze_json(item) for item in value))
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise ValueError("query snapshot contains unsupported JSON data")


def _thaw_json(value: FrozenJson) -> Any:
    if isinstance(value, FrozenObject):
        return {key: _thaw_json(item) for key, item in value.items}
    if isinstance(value, FrozenArray):
        return [_thaw_json(item) for item in value.items]
    return value
