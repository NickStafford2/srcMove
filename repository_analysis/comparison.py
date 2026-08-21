"""Run one explicit commit pair without publishing history-analysis state."""

from __future__ import annotations

import os
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path

from .configuration import load_history_configuration
from .contracts import PairOutcome, PairStatus, PairWorkItem, VerifiedArtifact
from .coordinator import run_pairs
from .database import AnalysisDatabase, analysis_database_exists
from .git import resolve_commit
from .inputs import (
    FrozenAnalysisManifest,
    observe_executable,
    pair_fingerprint,
    verify_resume_inputs,
)
from .locking import AnalysisOperationLock
from .worker import PairExecutor, remove_ephemeral_tree


@dataclass(frozen=True, slots=True)
class ComparisonResult:
    """One explicit pair outcome and the non-canonical files copied from it."""

    outcome: PairOutcome
    saved_paths: tuple[Path, ...]


def compare_commits(
    *,
    analysis_root: Path,
    repository: Path,
    old_revision: str,
    new_revision: str | None,
    save: str,
) -> ComparisonResult:
    """Execute and save one pair while leaving SQLite and coverage untouched."""

    if save not in {"all", "srcdiff", "srcmove"}:
        raise ValueError(f"unsupported comparison artifact selection: {save!r}")

    root = analysis_root.expanduser().absolute()
    requested_repository = repository.expanduser().resolve(strict=True)
    load_history_configuration(root)
    if not analysis_database_exists(root):
        raise ValueError(
            f"repository analysis has no canonical results: {root}; "
            "run srcmove-history run first"
        )
    with AnalysisOperationLock(root, command="compare") as operation:
        with AnalysisDatabase.open(root, read_only=True) as database:
            frozen = database.initial_manifest()
        if frozen.repository != requested_repository:
            raise ValueError("repository path drift from existing analysis")

        manifest = verify_resume_inputs(
            frozen,
            repository_identity=frozen.repository_identity,
            configuration=load_history_configuration(root).analysis,
            srcdiff=observe_executable(frozen.srcdiff.resolved_path),
            srcmove=observe_executable(frozen.srcmove.resolved_path),
        )
        if new_revision is None:
            new_commit = resolve_commit(requested_repository, old_revision)
            try:
                old_commit = resolve_commit(requested_repository, f"{new_commit}^1")
            except RuntimeError as error:
                raise ValueError(
                    f"commit has no first parent: {new_commit}"
                ) from error
        else:
            old_commit = resolve_commit(requested_repository, old_revision)
            new_commit = resolve_commit(requested_repository, new_revision)
        item = _comparison_item(manifest, old_commit, new_commit)
        scratch = root / "scratch" / f"compare-{operation.invocation_id}"
        executor = PairExecutor(scratch)
        outcomes: list[PairOutcome] = []
        saved_paths: list[Path] = []

        def publish(outcome: PairOutcome) -> None:
            outcomes.append(outcome)
            selected = _selected_artifacts(outcome, save)
            if not selected:
                return
            destination = _comparison_directory(root, old_commit, new_commit)
            for artifact in selected:
                target = destination / artifact.path.name
                _copy_atomically(artifact.path, target)
                saved_paths.append(target)

        try:
            run_pairs(
                [item],
                executor,
                publish,
                worker_count=1,
                acknowledge_pair=executor.acknowledge,
            )
        finally:
            remove_ephemeral_tree(scratch, root)

    if len(outcomes) != 1:
        raise RuntimeError("explicit comparison did not produce exactly one outcome")
    return ComparisonResult(outcomes[0], tuple(saved_paths))


def _comparison_item(
    manifest: FrozenAnalysisManifest, old_commit: str, new_commit: str
) -> PairWorkItem:
    configuration = manifest.configuration
    return PairWorkItem(
        sequence=0,
        old_commit=old_commit,
        new_commit=new_commit,
        fingerprint=pair_fingerprint(manifest, old_commit, new_commit),
        repository=manifest.repository,
        selected_directory=configuration.selected_directory,
        excluded_suffixes=configuration.excluded_suffixes,
        srcdiff=manifest.srcdiff.resolved_path,
        srcmove=manifest.srcmove.resolved_path,
        srcdiff_timeout_seconds=configuration.srcdiff_timeout_seconds,
        srcmove_timeout_seconds=configuration.srcmove_timeout_seconds,
        use_position=configuration.use_position,
        source_encoding=configuration.source_encoding,
    )


def _selected_artifacts(
    outcome: PairOutcome, selection: str
) -> tuple[VerifiedArtifact, ...]:
    names = {
        "srcdiff": {"srcdiff.xml"},
        "srcmove": {"srcmove.xml", "results.json"},
        "all": {"srcdiff.xml", "srcmove.xml", "results.json"},
    }[selection]
    return tuple(
        artifact
        for artifact in outcome.artifacts
        if artifact.path.name in names and artifact.validation_status == "valid"
    )


def _comparison_directory(root: Path, old_commit: str, new_commit: str) -> Path:
    comparisons = _owned_directory(root / "comparisons")
    return _owned_directory(comparisons / f"{old_commit}-to-{new_commit}")


def _owned_directory(path: Path) -> Path:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        path.mkdir()
        metadata = path.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise ValueError(f"comparison output is not an owned directory: {path}")
    return path


def _copy_atomically(source: Path, destination: Path) -> None:
    temporary = destination.parent / f".{destination.name}.tmp-{uuid.uuid4().hex}"
    try:
        with source.open("rb") as input_stream, temporary.open("xb") as output_stream:
            while block := input_stream.read(1024 * 1024):
                output_stream.write(block)
            output_stream.flush()
            os.fsync(output_stream.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def comparison_succeeded(result: ComparisonResult) -> bool:
    return result.outcome.status in {
        PairStatus.COMPLETED,
        PairStatus.NO_ANALYZABLE_CHANGE,
    }
