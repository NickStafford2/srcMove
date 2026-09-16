"""Canonical BigMoveBench corpus generation and evaluation stages."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping

from bigMoveBench.adapter import (
    SEMANTIC_ORACLE_VERSION,
    validate_srcdiff_semantics,
)
from bigMoveBench.corpus import (
    VerifiedCorpus,
    VerifiedSnapshot,
    generate_corpus,
    load_corpus,
    load_input_snapshot,
    run_corpus,
)
from bigMoveBench.evaluate import write_evaluation
from benchmarking.contracts import RunMode


def build_corpus(
    *,
    data_root: Path,
    input_snapshot: VerifiedSnapshot | str | Path,
    srcdiff: Path,
    timeout_seconds: float,
    retry_failed: bool,
    activity_callback: Callable[[str, str], None] | None = None,
    srcdiff_observation: Mapping[str, Any] | None = None,
) -> VerifiedCorpus:
    """Generate the immutable srcDiff corpus for a verified input snapshot."""

    verified_snapshot = (
        input_snapshot
        if isinstance(input_snapshot, VerifiedSnapshot)
        else load_input_snapshot(data_root, input_snapshot)
    )
    snapshot_manifest = verified_snapshot.manifest
    compiled_snapshot = bool(
        isinstance(snapshot_manifest.get("source"), Mapping)
        and snapshot_manifest["source"].get("compiled_dataset_id")
    )
    return generate_corpus(
        data_root=data_root,
        input_snapshot=verified_snapshot,
        srcdiff=srcdiff,
        timeout_seconds=timeout_seconds,
        use_position=True,
        use_archive=compiled_snapshot,
        retry_failed=retry_failed,
        semantic_validator=validate_srcdiff_semantics,
        semantic_oracle={
            "name": "bigclonebench-payload-exposure",
            "version": SEMANTIC_ORACLE_VERSION,
        },
        activity_callback=activity_callback,
        srcdiff_observation=srcdiff_observation,
    )


def evaluate_corpus(
    *,
    data_root: Path,
    results_root: Path | None = None,
    corpus: VerifiedCorpus | str | Path,
    srcmove: Path,
    timeout_seconds: float,
    mode: RunMode,
    activity_callback: Callable[[str, str], None] | None = None,
    srcmove_observation: Mapping[str, Any] | None = None,
) -> tuple[Path, dict, dict]:
    """Run srcMove over a verified corpus and write its scored evaluation."""

    verified_corpus = (
        corpus
        if isinstance(corpus, VerifiedCorpus)
        else load_corpus(data_root, corpus)
    )
    run_dir, run_manifest = run_corpus(
        data_root=data_root,
        results_root=results_root,
        corpus=verified_corpus,
        srcmove=srcmove,
        timeout_seconds=timeout_seconds,
        mode=mode,
        require_semantic_eligible=True,
        activity_callback=activity_callback,
        srcmove_observation=srcmove_observation,
    )
    summary = write_evaluation(
        run_dir=run_dir,
        run_manifest=run_manifest,
        corpus_dir=verified_corpus.directory,
        corpus_manifest=verified_corpus.manifest,
    )
    return run_dir, run_manifest, summary
