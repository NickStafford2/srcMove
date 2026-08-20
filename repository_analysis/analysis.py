"""Idempotent target-driven repository analysis orchestration."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .coordinator import CoordinatorStats, run_pairs_from_sequence
from .database import (
    AnalysisDatabase,
    StoredBatch,
    analysis_database_exists,
)
from .git import (
    first_parent_distance,
    retain_history,
    retained_history_ref,
    resolve_commit,
    select_older_first_parent_history,
    verify_frozen_commits,
)
from .inputs import (
    AnalysisConfiguration,
    ExecutableObservation,
    RepositoryIdentity,
    build_pair_work_items,
    freeze_analysis_inputs,
    observe_executable,
    verify_resume_inputs,
)
from .locking import AnalysisOperationLock
from .retention import RetentionPolicy
from .tools import admit_executable
from .worker import PairExecutor, remove_ephemeral_tree


DEFAULT_BATCH_PAIR_LIMIT = 100
LEGACY_STATE_MARKERS = (
    "current.json",
    "manifest.json",
    "pending",
    "segments",
    "receipts",
)


@dataclass(frozen=True, slots=True)
class AnalysisTarget:
    kind: str
    value: int | str | None

    def database_value(self) -> str | None:
        return None if self.value is None else str(self.value)


@dataclass(frozen=True, slots=True)
class AnalyzeResult:
    verified_pair_count: int
    execution: CoordinatorStats
    summary: dict[str, Any]


class _DatabasePublisher:
    def __init__(
        self,
        database: AnalysisDatabase,
        batch: StoredBatch,
        first_sequence: int,
        invocation_id: str,
    ) -> None:
        self.database = database
        self.batch = batch
        self.next_sequence = first_sequence
        self.invocation_id = invocation_id

    def __call__(self, outcome) -> None:
        if outcome.work_item.sequence != self.next_sequence:
            raise ValueError(
                "database outcomes must be published in sequence; "
                f"expected {self.next_sequence}, got {outcome.work_item.sequence}"
            )
        self.database.record_outcome(
            self.batch, outcome, invocation_id=self.invocation_id
        )
        self.next_sequence += 1


def analyze_repository(
    *,
    analysis_root: Path,
    target: AnalysisTarget,
    jobs: int,
    repository: Path | None = None,
    start: str | None = None,
    repository_identity: RepositoryIdentity | None = None,
    configuration: AnalysisConfiguration | None = None,
    srcdiff_path: Path | None = None,
    srcmove_path: Path | None = None,
) -> AnalyzeResult:
    """Create, resume, or extend one analysis toward an absolute target."""

    if jobs <= 0:
        raise ValueError("jobs must be positive")
    _validate_target(target)
    root = analysis_root.expanduser().absolute()
    with AnalysisOperationLock(root, command="analyze") as operation:
        invocation_started = time.monotonic()
        remove_ephemeral_tree(root / "scratch", root)
        if analysis_database_exists(root):
            database = AnalysisDatabase.open(root)
        else:
            database = _create_database(
                root,
                target,
                repository=repository,
                start=start,
                repository_identity=repository_identity,
                configuration=configuration,
                srcdiff_path=srcdiff_path,
                srcmove_path=srcmove_path,
            )
        with database:
            assert operation.started_at is not None
            database.begin_invocation(
                operation.invocation_id,
                target_kind=target.kind,
                target_value=target.database_value(),
                jobs=jobs,
                started_at=operation.started_at,
            )
            try:
                result = _advance_analysis(
                    database,
                    root=root,
                    invocation_id=operation.invocation_id,
                    target=target,
                    jobs=jobs,
                    repository=repository,
                    start=start,
                    repository_identity=repository_identity,
                    configuration=configuration,
                    srcdiff_path=srcdiff_path,
                    srcmove_path=srcmove_path,
                )
            except BaseException as error:
                database.finish_invocation(
                    operation.invocation_id,
                    result=(
                        "interrupted"
                        if isinstance(error, KeyboardInterrupt)
                        else "failed"
                    ),
                    ended_at=_utc_now(),
                    wall_seconds=time.monotonic() - invocation_started,
                    error=str(error) or type(error).__name__,
                )
                raise
            invocation = database.finish_invocation(
                operation.invocation_id,
                result=(
                    "target_reached_with_failures"
                    if result.summary["failed"]
                    else "target_reached"
                ),
                ended_at=_utc_now(),
                wall_seconds=time.monotonic() - invocation_started,
            )
            result.summary["invocation"] = invocation.record()
            return result


def _advance_analysis(
    database: AnalysisDatabase,
    *,
    root: Path,
    invocation_id: str,
    target: AnalysisTarget,
    jobs: int,
    repository: Path | None,
    start: str | None,
    repository_identity: RepositoryIdentity | None,
    configuration: AnalysisConfiguration | None,
    srcdiff_path: Path | None,
    srcmove_path: Path | None,
) -> AnalyzeResult:
    verified = 0
    aggregate_execution = _zero_stats(jobs)
    while True:
        state = database.analysis()
        template = database.latest_manifest()
        _verify_supplied_definition(
            template,
            newest_commit=state.newest_commit,
            start=start,
            repository=repository,
            repository_identity=repository_identity,
            configuration=configuration,
            srcdiff_path=srcdiff_path,
            srcmove_path=srcmove_path,
        )
        desired_total = _desired_total_pairs(database, template, target)
        pending = database.pending_batch()
        if pending is not None:
            pending_total = state.completed_pair_count + pending.pair_count
            if desired_total is not None and desired_total < pending_total:
                raise ValueError(
                    "requested target is smaller than frozen pending work; "
                    f"resume at least {pending_total} total pairs"
                )
            prefix, execution = _execute_pending_batch(
                database,
                pending,
                jobs=jobs,
                scratch_root=root / "scratch" / invocation_id,
                srcdiff_path=srcdiff_path,
                srcmove_path=srcmove_path,
                invocation_id=invocation_id,
            )
            verified += prefix
            aggregate_execution = _combine_stats(aggregate_execution, execution)
            database.commit_pending_batch(pending)
            continue
        if state.history_exhausted:
            break
        if desired_total is not None and state.completed_pair_count >= desired_total:
            break
        manifest, reaches_root = _plan_next_batch(
            database, template, state, target, desired_total
        )
        if len(manifest.commits) < 2:
            raise RuntimeError(
                "repository has no older adjacent pair at the analysis frontier"
            )
        database.add_pending_batch(
            manifest,
            batch_id=uuid.uuid4().hex,
            target_kind=target.kind,
            target_value=target.database_value(),
            reaches_root=reaches_root,
            retention_policy=RetentionPolicy(),
        )
    return AnalyzeResult(
        verified_pair_count=verified,
        execution=aggregate_execution,
        summary=database.summary(),
    )


def analysis_status(analysis_root: Path) -> dict[str, Any]:
    """Return committed coverage without taking the writer lock."""

    with AnalysisDatabase.open(analysis_root, read_only=True) as database:
        with database.read_snapshot():
            summary = database.summary()
            pending = database.pending_batch()
            summary["pending"] = (
                None
                if pending is None
                else {
                    "batch_id": pending.batch_id,
                    "pair_count": pending.pair_count,
                    "completed_prefix": database.completed_prefix(pending),
                    "target_kind": pending.target_kind,
                    "target_value": pending.target_value,
                }
            )
            invocation = database.latest_invocation()
            summary["invocation"] = (
                None if invocation is None else invocation.record()
            )
            return summary


def analysis_pair_details(
    analysis_root: Path, distance_from_newest: int
) -> dict[str, Any]:
    """Return compact evidence for one previously committed pair."""

    with AnalysisDatabase.open(analysis_root, read_only=True) as database:
        with database.read_snapshot():
            return database.pair_details(distance_from_newest)


def _create_database(
    root: Path,
    target: AnalysisTarget,
    *,
    repository: Path | None,
    start: str,
    repository_identity: RepositoryIdentity | None,
    configuration: AnalysisConfiguration | None,
    srcdiff_path: Path | None,
    srcmove_path: Path | None,
) -> AnalysisDatabase:
    legacy = [name for name in LEGACY_STATE_MARKERS if (root / name).exists()]
    if legacy:
        raise ValueError(
            "analysis root contains unsupported legacy state: "
            + ", ".join(legacy)
            + "; choose a new analysis root"
        )
    missing = [
        name
        for name, value in (
            ("--repository", repository),
            ("--repository-id", repository_identity),
            ("--srcdiff", srcdiff_path),
            ("--srcmove", srcmove_path),
        )
        if value is None
    ]
    if missing:
        raise ValueError(
            "new analysis requires " + ", ".join(missing)
        )
    assert repository is not None
    assert repository_identity is not None
    assert srcdiff_path is not None
    assert srcmove_path is not None
    history = _select_initial_history(repository, start or "HEAD", target)
    if len(history.commits) < 2:
        raise RuntimeError("repository history contains no adjacent commit pair")
    srcdiff = admit_executable(srcdiff_path, root, role="srcdiff")
    srcmove = admit_executable(srcmove_path, root, role="srcmove")
    manifest = freeze_analysis_inputs(
        repository=repository,
        repository_identity=repository_identity,
        commits=history.commits,
        configuration=configuration or AnalysisConfiguration(),
        srcdiff=srcdiff,
        srcmove=srcmove,
    )
    ref = retained_history_ref(manifest.canonical_bytes())
    retain_history(manifest.repository, ref, history.resolved_start)
    return AnalysisDatabase.create(
        root,
        manifest,
        batch_id=uuid.uuid4().hex,
        target_kind=target.kind,
        target_value=target.database_value(),
        reaches_root=history.history_exhausted,
        retention_policy=RetentionPolicy(),
    )


def _select_initial_history(repository: Path, start: str, target: AnalysisTarget):
    if target.kind == "total_pairs":
        assert isinstance(target.value, int)
        return select_older_first_parent_history(
            repository,
            start,
            pair_count=min(target.value, DEFAULT_BATCH_PAIR_LIMIT),
        )
    if target.kind == "through":
        assert isinstance(target.value, str)
        _require_full_commit_target(repository, target.value)
        distance = first_parent_distance(repository, start, target.value)
        return select_older_first_parent_history(
            repository,
            start,
            pair_count=min(distance, DEFAULT_BATCH_PAIR_LIMIT),
        )
    return select_older_first_parent_history(
        repository, start, pair_count=DEFAULT_BATCH_PAIR_LIMIT
    )


def _desired_total_pairs(
    database: AnalysisDatabase,
    template,
    target: AnalysisTarget,
) -> int | None:
    if target.kind == "total_pairs":
        assert isinstance(target.value, int)
        return target.value
    if target.kind == "all":
        return None
    assert isinstance(target.value, str)
    _require_full_commit_target(template.repository, target.value)
    return first_parent_distance(
        template.repository,
        database.analysis().newest_commit,
        target.value,
    )


def _plan_next_batch(database, template, state, target, desired_total):
    boundary = state.oldest_completed_commit or state.newest_commit
    if desired_total is None:
        history = select_older_first_parent_history(
            template.repository,
            boundary,
            pair_count=DEFAULT_BATCH_PAIR_LIMIT,
        )
    else:
        remaining = min(
            desired_total - state.completed_pair_count,
            DEFAULT_BATCH_PAIR_LIMIT,
        )
        if remaining <= 0:
            raise RuntimeError("analysis target planning received no remaining work")
        history = select_older_first_parent_history(
            template.repository, boundary, pair_count=remaining
        )
    manifest = freeze_analysis_inputs(
        repository=template.repository,
        repository_identity=template.repository_identity,
        commits=history.commits,
        configuration=template.configuration,
        srcdiff=template.srcdiff,
        srcmove=template.srcmove,
    )
    return manifest, history.history_exhausted


def _execute_pending_batch(
    database: AnalysisDatabase,
    batch: StoredBatch,
    *,
    jobs: int,
    scratch_root: Path,
    srcdiff_path: Path | None,
    srcmove_path: Path | None,
    invocation_id: str,
) -> tuple[int, CoordinatorStats]:
    frozen = database.pending_manifest(batch)
    srcdiff = observe_executable(frozen.srcdiff.requested_path)
    srcmove = observe_executable(frozen.srcmove.requested_path)
    manifest = verify_resume_inputs(
        frozen,
        repository_identity=frozen.repository_identity,
        configuration=frozen.configuration,
        srcdiff=srcdiff,
        srcmove=srcmove,
    )
    verify_frozen_commits(
        manifest.repository,
        manifest.commits,
        retained_ref=retained_history_ref(
            database.initial_manifest().canonical_bytes()
        ),
    )
    work = build_pair_work_items(manifest)
    prefix = database.completed_prefix(batch)
    executor = PairExecutor(scratch_root)
    publisher = _DatabasePublisher(database, batch, prefix, invocation_id)
    execution = run_pairs_from_sequence(
        iter(work[prefix:]),
        executor,
        publisher,
        worker_count=jobs,
        first_sequence=prefix,
        acknowledge_pair=executor.acknowledge,
    )
    return prefix, execution


def _verify_supplied_definition(
    template,
    *,
    newest_commit: str,
    start: str | None,
    repository: Path | None,
    repository_identity: RepositoryIdentity | None,
    configuration: AnalysisConfiguration | None,
    srcdiff_path: Path | None,
    srcmove_path: Path | None,
) -> None:
    if (
        start is not None
        and resolve_commit(template.repository, start) != newest_commit
    ):
        raise ValueError("start revision drift from existing analysis")
    if repository is not None and repository.expanduser().resolve(strict=True) != template.repository:
        raise ValueError("repository path drift from existing analysis")
    if (
        repository_identity is not None
        and repository_identity != template.repository_identity
    ):
        raise ValueError("repository identity drift from existing analysis")
    if configuration is not None and configuration != template.configuration:
        raise ValueError("configuration drift from existing analysis")
    for name, path, frozen in (
        ("srcDiff", srcdiff_path, template.srcdiff),
        ("srcMove", srcmove_path, template.srcmove),
    ):
        if path is None:
            continue
        observed = observe_executable(path)
        if (observed.size_bytes, observed.sha256) != (
            frozen.size_bytes,
            frozen.sha256,
        ):
            raise ValueError(f"{name} executable drift from existing analysis")


def _validate_target(target: AnalysisTarget) -> None:
    if target.kind == "total_pairs":
        if (
            isinstance(target.value, bool)
            or not isinstance(target.value, int)
            or target.value <= 0
        ):
            raise ValueError("total-pairs target must be a positive integer")
    elif target.kind == "through":
        if not isinstance(target.value, str) or not target.value or "\0" in target.value:
            raise ValueError("through target must be a non-empty revision")
    elif target.kind == "all":
        if target.value is not None:
            raise ValueError("all-history target must not have a value")
    else:
        raise ValueError(f"unknown analysis target: {target.kind!r}")


def _require_full_commit_target(repository: Path, value: str) -> None:
    resolved = resolve_commit(repository, value)
    if value != resolved:
        raise ValueError(
            "--through must be a complete commit object ID so retries cannot "
            "change meaning"
        )


def _zero_stats(jobs: int) -> CoordinatorStats:
    return CoordinatorStats(jobs, 0, 0, 0, 0, 0)


def _combine_stats(left: CoordinatorStats, right: CoordinatorStats) -> CoordinatorStats:
    return CoordinatorStats(
        worker_count=right.worker_count,
        submitted_count=left.submitted_count + right.submitted_count,
        completed_count=left.completed_count + right.completed_count,
        published_count=left.published_count + right.published_count,
        max_queued_work=max(left.max_queued_work, right.max_queued_work),
        max_unpublished_outcomes=max(
            left.max_unpublished_outcomes, right.max_unpublished_outcomes
        ),
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
