#!/usr/bin/env python3
"""Run the supported compiled BigCloneBench pair sets as one suite."""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
TESTS_ROOT = REPO_ROOT / "tests"
for import_root in (REPO_ROOT, TESTS_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from benchmarks.bigclonebench.compile import DEFAULT_DATA_ROOT, ensure_compiled_dataset
from benchmarks.bigclonebench.evaluate import SCORING_ORACLE_VERSION
from benchmarks.bigclonebench.generate import BCE_DIR
from benchmarks.bigclonebench.pipeline import build_corpus, evaluate_corpus
from benchmarks.bigclonebench.selection import DEFAULT_SAMPLE_SIZE, create_selection
from benchmarks.bigclonebench.snapshot import materialize_compiled_selection
from benchmarks.contracts import RunMode
from benchmarks.process import write_json_atomic
from benchmarks.progress import ProgressDisplay
from benchmarks.provenance import utc_now
from support.tooling import find_srcdiff, find_srcmove


PAIR_SETS = (
    ("type1", "Type 1"),
    ("type2", "Type 2"),
    ("known-false-positive", "Known false positives"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--bce-dir", type=Path, default=BCE_DIR)
    parser.add_argument("--mode", choices=("sample", "census"), default="sample")
    parser.add_argument(
        "--role", choices=("tuning", "evaluation"), default="tuning"
    )
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--sample-size", type=int, default=DEFAULT_SAMPLE_SIZE)
    parser.add_argument("--verify-source", action="store_true")
    parser.add_argument("--srcdiff", type=Path)
    parser.add_argument("--srcmove", type=Path)
    parser.add_argument("--srcdiff-timeout", type=float, default=60.0)
    parser.add_argument("--srcmove-timeout", type=float, default=300.0)
    return parser.parse_args()


def _timed(call: Callable[[], Any]) -> tuple[Any, float]:
    started = time.monotonic()
    result = call()
    return result, time.monotonic() - started


def _activity(
    progress: ProgressDisplay,
) -> tuple[Callable[[str, str], None], dict[str, int]]:
    counts = {"running": 0, "reused": 0, "completed": 0, "failed": 0}
    completed = 0

    def report(activity: str, case_id: str) -> None:
        nonlocal completed
        if activity in counts:
            counts[activity] += 1
        if activity == "running":
            progress.update(completed, detail=case_id)
        elif activity in {"accepted", "completed", "reused", "failed"}:
            completed += 1
            progress.update(completed, detail=case_id)

    return report, counts


def _attempt_resources(run_dir: Path, run_manifest: Mapping[str, Any]) -> dict[str, Any]:
    process_seconds = 0.0
    peak_rss: int | None = None
    for case in run_manifest.get("cases", []):
        attempt_id = case.get("attempt_id")
        if not isinstance(attempt_id, str):
            continue
        path = run_dir / "attempts" / attempt_id / "attempt.json"
        try:
            attempt = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        elapsed = attempt.get("process_elapsed_seconds")
        if isinstance(elapsed, (int, float)):
            process_seconds += float(elapsed)
        resource = attempt.get("resource_usage", {})
        observed_peak = resource.get("peak_rss_bytes")
        if isinstance(observed_peak, int):
            peak_rss = max(peak_rss or 0, observed_peak)
    return {"process_seconds": process_seconds, "peak_rss_bytes": peak_rss}


def _pair_result(
    *,
    pair_set: str,
    label: str,
    selection_manifest: Mapping[str, Any],
    selection_reused: bool,
    snapshot: Any,
    snapshot_disposition: str,
    corpus: Any,
    corpus_disposition: str,
    run_dir: Path,
    run_manifest: Mapping[str, Any],
    summary: Mapping[str, Any],
    timings: Mapping[str, float],
) -> dict[str, Any]:
    counts = summary["counts"]
    resources = _attempt_resources(run_dir, run_manifest)
    detected = counts["oracle_pass"] + counts["wrong_classification"]
    return {
        "pair_set": pair_set,
        "label": label,
        "selection_id": selection_manifest["selection_id"],
        "selection_reused": selection_reused,
        "input_snapshot_id": snapshot.snapshot_id,
        "snapshot_disposition": snapshot_disposition,
        "corpus_id": corpus.corpus_id,
        "corpus_disposition": corpus_disposition,
        "run_id": run_manifest["run_id"],
        "run_directory": str(run_dir),
        "counts": dict(counts),
        "metrics": {
            "whole_fragment_detected": detected,
            "strictly_classified": counts["oracle_pass"],
            "rejected": counts["oracle_pass"],
            "accepted": counts.get("srcmove_false_positive", 0),
            "incidental": counts.get("negative_incidental_move_passes", 0),
        },
        "selection_counts": dict(selection_manifest["counts"]),
        "timings": {**dict(timings), **resources},
    }


def run_suite(args: argparse.Namespace) -> tuple[Path, dict[str, Any], bool]:
    data_root = args.data_root.expanduser().resolve()
    srcdiff = find_srcdiff(REPO_ROOT, args.srcdiff)
    srcmove = find_srcmove(REPO_ROOT, args.srcmove)
    if srcdiff is None:
        raise ValueError("srcdiff not found; pass --srcdiff")
    if srcmove is None:
        raise ValueError("srcMove not found; pass --srcmove")

    (compiled_result, compile_seconds) = _timed(
        lambda: ensure_compiled_dataset(
            data_root=data_root,
            bce_dir=args.bce_dir,
            verify_source=args.verify_source,
        )
    )
    compiled, compiled_reused = compiled_result
    pair_results: list[dict[str, Any]] = []

    for pair_set, label in PAIR_SETS:
        with ProgressDisplay("selection", detail=f"{label} {args.mode}") as progress:
            (selection_result, selection_seconds) = _timed(
                lambda pair_set=pair_set, progress=progress: create_selection(
                    compiled,
                    data_root=data_root,
                    pair_set=pair_set,
                    mode=args.mode,
                    role=args.role,
                    sample_size=args.sample_size,
                    seed=args.seed,
                    progress=progress,
                )
            )
            selection_dir, selection_manifest, selection_reused = selection_result
            progress.finish(
                f"{selection_manifest['counts']['selected_frames']:,} tests",
                completion="reused" if selection_reused else "created",
            )

        (snapshot_result, snapshot_seconds) = _timed(
            lambda selection=selection_dir: materialize_compiled_selection(
                data_root=data_root, selection=selection
            )
        )
        snapshot, snapshot_disposition = snapshot_result

        with ProgressDisplay(
            "srcDiff", total=snapshot.manifest["counts"]["selected"], detail=label
        ) as progress:
            callback, activity = _activity(progress)
            (corpus, corpus_seconds) = _timed(
                lambda: build_corpus(
                    data_root=data_root,
                    input_snapshot=snapshot,
                    srcdiff=srcdiff,
                    timeout_seconds=args.srcdiff_timeout,
                    retry_failed=False,
                    activity_callback=callback,
                )
            )
            corpus_disposition = "created" if activity["running"] else "reused"
            progress.finish(
                f"{corpus.manifest['counts']['semantic_eligible']:,} eligible",
                completion=corpus_disposition,
            )

        eligible = corpus.manifest["counts"]["semantic_eligible"]
        with ProgressDisplay("srcMove", total=eligible, detail=label) as progress:
            callback, _ = _activity(progress)
            (evaluation, evaluation_seconds) = _timed(
                lambda: evaluate_corpus(
                    data_root=data_root,
                    corpus=corpus,
                    srcmove=srcmove,
                    timeout_seconds=args.srcmove_timeout,
                    mode=RunMode.DEVELOPMENT,
                    activity_callback=callback,
                )
            )
            run_dir, run_manifest, summary = evaluation
            progress.finish(
                f"{summary['counts']['oracle_pass']:,}/{summary['counts']['selected']:,} oracle passes"
            )

        pair_results.append(
            _pair_result(
                pair_set=pair_set,
                label=label,
                selection_manifest=selection_manifest,
                selection_reused=selection_reused,
                snapshot=snapshot,
                snapshot_disposition=snapshot_disposition,
                corpus=corpus,
                corpus_disposition=corpus_disposition,
                run_dir=run_dir,
                run_manifest=run_manifest,
                summary=summary,
                timings={
                    "selection_seconds": selection_seconds,
                    "snapshot_seconds": snapshot_seconds,
                    "srcdiff_stage_seconds": corpus_seconds,
                    "srcmove_stage_seconds": evaluation_seconds,
                },
            )
        )

    suite_id = f"suite-{utc_now().replace(':', '').replace('+', '-')}-{uuid.uuid4()}"
    suite_dir = data_root / "bigclonebench" / "suite-runs" / suite_id
    suite = {
        "schema_version": 1,
        "suite_id": suite_id,
        "created_at": utc_now(),
        "request": {
            "mode": args.mode,
            "role": args.role,
            "seed": args.seed,
            "sample_size": args.sample_size,
            "verify_source": args.verify_source,
        },
        "compiled_dataset": {
            "dataset_id": compiled.dataset_id,
            "disposition": "reused" if compiled_reused else "created",
            "seconds": compile_seconds,
        },
        "scoring_oracle_version": SCORING_ORACLE_VERSION,
        "pair_sets": pair_results,
    }
    write_json_atomic(suite_dir / "summary.json", suite)
    passed = all(
        result["counts"]["oracle_pass"] == result["counts"]["selected"]
        for result in pair_results
    )
    return suite_dir, suite, passed


def _seconds(value: float) -> str:
    return f"{value:.3f}s"


def _print_report(directory: Path, suite: Mapping[str, Any]) -> None:
    dataset = suite["compiled_dataset"]
    print()
    print("BigCloneBench suite")
    print(
        f"  dataset: {dataset['dataset_id']} "
        f"({dataset['disposition']}; {_seconds(dataset['seconds'])})"
    )
    print()
    for result in suite["pair_sets"]:
        counts = result["counts"]
        metrics = result["metrics"]
        elapsed = result["timings"]["process_seconds"]
        if result["pair_set"] == "known-false-positive":
            measurement = (
                f"rejected {metrics['rejected']:,}/{counts['selected']:,}; "
                f"accepted {metrics['accepted']:,}; incidental {metrics['incidental']:,}"
            )
        else:
            measurement = (
                f"detected {metrics['whole_fragment_detected']:,}/{counts['selected']:,}; "
                f"classified {metrics['strictly_classified']:,}/{counts['selected']:,}"
            )
        print(f"  {result['label']:<22} {measurement}   srcMove {_seconds(elapsed)}")
        timings = result["timings"]
        print(
            " " * 26
            + f"selection {_seconds(timings['selection_seconds'])} "
            f"({'reused' if result['selection_reused'] else 'created'}); "
            f"snapshot {_seconds(timings['snapshot_seconds'])} "
            f"({result['snapshot_disposition']}); "
            f"srcDiff {_seconds(timings['srcdiff_stage_seconds'])} "
            f"({result['corpus_disposition']})"
        )

    unique_tests = sum(item["counts"]["selected"] for item in suite["pair_sets"])
    source_rows = sum(
        item["selection_counts"]["selected_source_rows"]
        for item in suite["pair_sets"]
    )
    eligible = sum(item["counts"]["eligible"] for item in suite["pair_sets"])
    srcmove_seconds = sum(
        item["timings"]["process_seconds"] for item in suite["pair_sets"]
    )
    peak_values = [
        item["timings"]["peak_rss_bytes"]
        for item in suite["pair_sets"]
        if item["timings"]["peak_rss_bytes"] is not None
    ]
    throughput = eligible / srcmove_seconds if srcmove_seconds else None
    peak = max(peak_values) if peak_values else None
    print()
    print(
        f"  unique tests {unique_tests:,}   source rows {source_rows:,}   "
        f"srcDiff eligible {eligible:,}"
    )
    print(
        f"  srcMove total {_seconds(srcmove_seconds)}   throughput "
        f"{throughput:.2f}/s" if throughput is not None else
        f"  srcMove total {_seconds(srcmove_seconds)}   throughput unavailable"
    )
    print(
        f"  peak memory {peak / (1024 * 1024):.1f} MiB"
        if peak
        else "  peak memory unavailable"
    )
    print(f"  summary: {directory / 'summary.json'}")


def main() -> int:
    args = parse_args()
    try:
        directory, suite, passed = run_suite(args)
        _print_report(directory, suite)
        return 0 if passed else 1
    except (OSError, RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
