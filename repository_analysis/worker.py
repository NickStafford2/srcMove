"""Focused execution of one repository-history commit pair."""

from __future__ import annotations

import contextlib
import threading
import time
import uuid
from pathlib import Path
from typing import Iterator

from .contracts import (
    ChangedPath,
    PairOutcome,
    PairStatus,
    PairWorkItem,
    ProcessOutcome,
    VerifiedArtifact,
)
from .git import (
    GitBatch,
    GitMaterializationError,
    inventory_changed_paths,
)
from .process import (
    ArtifactValidationError,
    run_process,
    validate_results_artifact,
    validate_xml_artifact,
)


class PairExecutor:
    """Create one private execution session for every coordinator worker."""

    def __init__(self, analysis_root: Path, *, log_limit: int = 1024 * 1024) -> None:
        if log_limit < 2:
            raise ValueError("log_limit must be at least two bytes")
        self.analysis_root = analysis_root.resolve()
        self.log_limit = log_limit

    def __call__(self, work_item: PairWorkItem) -> PairOutcome:
        raise RuntimeError("PairExecutor must be used through run_pairs")

    @contextlib.contextmanager
    def open_worker(self) -> Iterator[_WorkerSession]:
        self.analysis_root.mkdir(parents=True, exist_ok=True)
        name = threading.current_thread().name.replace("/", "-")
        worker_directory = self.analysis_root / f"{name}-{uuid.uuid4().hex}"
        worker_directory.mkdir(exist_ok=False)
        session = _WorkerSession(worker_directory, self.log_limit)
        try:
            yield session
        finally:
            session.close()


class _WorkerSession:
    """Long-lived worker state, including its persistent Git batch process."""

    def __init__(self, directory: Path, log_limit: int) -> None:
        self.directory = directory
        self.log_limit = log_limit
        self._repository: Path | None = None
        self._git_batch: GitBatch | None = None

    def close(self) -> None:
        if self._git_batch is not None:
            self._git_batch.close()
            self._git_batch = None

    def _batch(self, repository: Path) -> GitBatch:
        resolved = repository.resolve()
        if self._repository is not None and resolved != self._repository:
            raise RuntimeError("one worker session cannot span multiple repositories")
        if self._git_batch is None:
            self._git_batch = GitBatch(resolved)
            self._repository = resolved
        return self._git_batch

    def __call__(self, item: PairWorkItem) -> PairOutcome:
        pair_started = time.monotonic()
        timings: dict[str, float] = {}
        changed = ()
        analyzable = ()
        try:
            repository, srcdiff, srcmove = _required_paths(item)
            inventory_started = time.monotonic()
            changed, analyzable = inventory_changed_paths(
                repository,
                item.old_commit,
                item.new_commit,
                item.selected_directory,
                item.excluded_suffixes,
            )
            timings["inventory_seconds"] = time.monotonic() - inventory_started
            if not analyzable:
                timings["pair_seconds"] = time.monotonic() - pair_started
                return PairOutcome(
                    work_item=item,
                    status=PairStatus.NO_ANALYZABLE_CHANGE,
                    changed_paths=changed,
                    analyzable_paths=analyzable,
                    timings=tuple(timings.items()),
                )

            pair_directory = self.directory / (
                f"pair-{item.sequence:08d}-{item.fingerprint[:12]}"
            )
            pair_directory.mkdir(exist_ok=False)
            original = pair_directory / "original"
            modified = pair_directory / "modified"
            materialize_started = time.monotonic()
            batch = self._batch(repository)
            input_artifacts = (
                *batch.materialize(analyzable, side="old", destination=original),
                *batch.materialize(analyzable, side="new", destination=modified),
            )
            timings["materialization_seconds"] = (
                time.monotonic() - materialize_started
            )
        except GitMaterializationError as error:
            return _failed_outcome(
                item,
                PairStatus.EXPORT_FAILED,
                changed,
                analyzable,
                timings,
                pair_started,
                error,
            )
        except Exception as error:
            return _failed_outcome(
                item,
                PairStatus.ORCHESTRATION_FAILED,
                changed,
                analyzable,
                timings,
                pair_started,
                error,
            )

        shape = "archive" if item.use_archive else "single_file"
        srcdiff_xml = pair_directory / "srcdiff.xml"
        srcdiff_command = [str(srcdiff)]
        if item.use_position:
            srcdiff_command.append("--position")
        if item.use_archive:
            srcdiff_command.append("--archive")
        if item.source_encoding:
            srcdiff_command.extend(["--src-encoding", item.source_encoding])
        srcdiff_command.extend(
            [str(original), str(modified), "-o", str(srcdiff_xml)]
        )
        srcdiff_started = time.monotonic()
        srcdiff_process = run_process(
            srcdiff_command,
            cwd=pair_directory,
            timeout_seconds=item.srcdiff_timeout_seconds,
            output_path=srcdiff_xml,
            validator=lambda path: validate_xml_artifact(
                path, shape=shape, producing_stage="srcdiff"
            ),
            capture_prefix="srcdiff",
            log_limit=self.log_limit,
        )
        timings["srcdiff_seconds"] = time.monotonic() - srcdiff_started
        if not srcdiff_process.admitted:
            timings["pair_seconds"] = time.monotonic() - pair_started
            return PairOutcome(
                work_item=item,
                status=PairStatus.SRCDIFF_FAILED,
                changed_paths=changed,
                analyzable_paths=analyzable,
                srcdiff_process=srcdiff_process,
                artifacts=_present_artifacts(
                    input_artifacts, srcdiff_process.output_artifact
                ),
                timings=tuple(timings.items()),
                error=_process_failure("srcDiff", srcdiff_process),
            )

        srcdiff_artifact = srcdiff_process.output_artifact
        assert srcdiff_artifact is not None
        srcmove_xml = pair_directory / "srcmove.xml"
        results_json = pair_directory / "results.json"
        srcmove_started = time.monotonic()
        srcmove_process = run_process(
            [
                str(srcmove),
                str(srcdiff_artifact.path),
                str(srcmove_xml),
                "--results",
                str(results_json),
            ],
            cwd=pair_directory,
            timeout_seconds=item.srcmove_timeout_seconds,
            output_path=srcmove_xml,
            validator=lambda path: validate_xml_artifact(
                path, shape=shape, producing_stage="srcmove"
            ),
            capture_prefix="srcmove",
            log_limit=self.log_limit,
        )
        timings["srcmove_seconds"] = time.monotonic() - srcmove_started
        artifacts = _present_artifacts(
            input_artifacts,
            srcdiff_artifact,
            srcmove_process.output_artifact,
        )
        if not srcmove_process.admitted:
            timings["pair_seconds"] = time.monotonic() - pair_started
            return PairOutcome(
                work_item=item,
                status=PairStatus.SRCMOVE_FAILED,
                changed_paths=changed,
                analyzable_paths=analyzable,
                srcdiff_process=srcdiff_process,
                srcmove_process=srcmove_process,
                artifacts=artifacts,
                timings=tuple(timings.items()),
                error=_process_failure("srcMove", srcmove_process),
            )

        results_started = time.monotonic()
        try:
            results_artifact, metrics = validate_results_artifact(
                results_json, producing_command=srcmove_process.command
            )
        except ArtifactValidationError as error:
            timings["results_validation_seconds"] = (
                time.monotonic() - results_started
            )
            timings["pair_seconds"] = time.monotonic() - pair_started
            return PairOutcome(
                work_item=item,
                status=PairStatus.SRCMOVE_FAILED,
                changed_paths=changed,
                analyzable_paths=analyzable,
                srcdiff_process=srcdiff_process,
                srcmove_process=srcmove_process,
                artifacts=_present_artifacts(artifacts, error.artifact),
                timings=tuple(timings.items()),
                error=str(error),
            )
        timings["results_validation_seconds"] = time.monotonic() - results_started
        timings["pair_seconds"] = time.monotonic() - pair_started
        return PairOutcome(
            work_item=item,
            status=PairStatus.COMPLETED,
            changed_paths=changed,
            analyzable_paths=analyzable,
            srcdiff_process=srcdiff_process,
            srcmove_process=srcmove_process,
            artifacts=(*artifacts, results_artifact),
            metrics=metrics,
            timings=tuple(timings.items()),
        )


def _required_paths(item: PairWorkItem) -> tuple[Path, Path, Path]:
    missing = [
        name
        for name, value in (
            ("repository", item.repository),
            ("srcdiff", item.srcdiff),
            ("srcmove", item.srcmove),
        )
        if value is None
    ]
    if missing:
        raise ValueError(
            f"pair work item is missing execution fields: {', '.join(missing)}"
        )
    assert item.repository is not None
    assert item.srcdiff is not None
    assert item.srcmove is not None
    return item.repository.resolve(), item.srcdiff.resolve(), item.srcmove.resolve()


def _failed_outcome(
    item: PairWorkItem,
    status: PairStatus,
    changed: tuple[ChangedPath, ...],
    analyzable: tuple[ChangedPath, ...],
    timings: dict[str, float],
    pair_started: float,
    error: Exception,
) -> PairOutcome:
    timings["pair_seconds"] = time.monotonic() - pair_started
    return PairOutcome(
        work_item=item,
        status=status,
        changed_paths=changed,
        analyzable_paths=analyzable,
        timings=tuple(timings.items()),
        error=f"{type(error).__name__}: {error}",
    )


def _present_artifacts(
    existing: tuple[VerifiedArtifact, ...],
    *optional: VerifiedArtifact | None,
) -> tuple[VerifiedArtifact, ...]:
    return (*existing, *(artifact for artifact in optional if artifact is not None))


def _process_failure(stage: str, outcome: ProcessOutcome) -> str:
    termination = outcome.termination_status
    if termination == "exited" and outcome.exit_code != 0:
        return f"{stage} exited with code {outcome.exit_code}"
    if termination == "signaled":
        return f"{stage} terminated by signal {outcome.signal_number}"
    if termination == "timed_out":
        return f"{stage} timed out"
    if termination == "spawn_failed":
        return f"{stage} could not start: {outcome.spawn_error}"
    validation_error = outcome.validation_error
    if validation_error:
        return f"{stage} artifact validation failed: {validation_error}"
    return f"{stage} failed with termination status {termination}"
