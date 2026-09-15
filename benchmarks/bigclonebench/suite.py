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

from benchmarks.bigclonebench.compile import ensure_compiled_dataset
from benchmarks.bigclonebench.evaluate import SCORING_ORACLE_VERSION
from benchmarks.bigclonebench.frozen_profiles import create_frozen_selection
from benchmarks.bigclonebench.generate import BCE_DIR
from benchmarks.bigclonebench.pipeline import build_corpus, evaluate_corpus
from benchmarks.bigclonebench.selection import DEFAULT_SAMPLE_SIZE, create_selection
from benchmarks.bigclonebench.snapshot import materialize_compiled_selection
from benchmarks.contracts import RunMode
from benchmarks.process import write_json_atomic
from benchmarks.progress import ProgressDisplay
from benchmarks.paths import DEFAULT_CACHE_ROOT, DEFAULT_RESULTS_ROOT
from benchmarks.provenance import observe_executable, utc_now
from support.tooling import find_srcdiff, find_srcmove


PAIR_SETS = (
    ("type1", "Type 1"),
    ("type2", "Type 2"),
    ("type3", "Type 3"),
    ("known-false-positive", "Known false positives"),
)
PAIR_SET_LABELS = dict(PAIR_SETS)
OPERATIONAL_FAILURES = (
    "upstream_failure",
    "srcdiff_semantic_ineligible",
    "srcmove_tool_failure",
    "oracle_failure",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    parser.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    parser.add_argument("--bce-dir", type=Path, default=BCE_DIR)
    parser.add_argument("--mode", choices=("sample", "census"), default="sample")
    parser.add_argument(
        "--profile",
        choices=("small", "medium", "full"),
        default="small",
        help=(
            "Frozen standard profile (small/medium), or the slow exhaustive "
            "dynamic research path (full)."
        ),
    )
    parser.add_argument(
        "--role", choices=("tuning", "evaluation"), default="tuning"
    )
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--sample-size", type=int, default=DEFAULT_SAMPLE_SIZE)
    parser.add_argument(
        "--pair-set",
        choices=tuple(PAIR_SET_LABELS),
        help="Run only one pair set (default: run the full suite).",
    )
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


def _operational_failures(counts: Mapping[str, int]) -> int:
    return sum(counts[name] for name in OPERATIONAL_FAILURES)


def _pair_set_operational_pass(
    pair_set: str, counts: Mapping[str, int]
) -> bool:
    if pair_set == "type3":
        return _operational_failures(counts) == 0
    return counts["oracle_pass"] == counts["selected"]


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
    operational_failures = _operational_failures(counts)
    observational = pair_set == "type3"
    type3_strength = summary.get("strata", {}).get("type3_strength", {})
    operational_pass = _pair_set_operational_pass(pair_set, counts)
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
        "assessment": {
            "mode": "observational" if observational else "strict",
            "sample_interpretation": (
                "balanced_strength_sample"
                if observational
                and selection_manifest.get("request", {}).get("mode")
                in {"sample", "preset"}
                else "census"
                if observational
                else None
            ),
            "operational_pass": operational_pass,
            "operational_failures": operational_failures,
        },
        "metrics": {
            "whole_fragment_detected": detected,
            "strictly_classified": counts["oracle_pass"],
            "rejected": counts["oracle_pass"],
            "accepted": counts.get("srcmove_false_positive", 0),
            "incidental": counts.get("negative_incidental_move_passes", 0),
        },
        "selection_counts": dict(selection_manifest["counts"]),
        "type3_strength_strata": dict(type3_strength) if observational else {},
        "timings": {**dict(timings), **resources},
    }


def run_suite(args: argparse.Namespace) -> tuple[Path, dict[str, Any], bool]:
    selected_pair_set = getattr(args, "pair_set", None)
    profile = getattr(args, "profile", "full")
    if args.role == "evaluation" and selected_pair_set in {None, "type3"}:
        raise ValueError(
            "Type-3 evaluation suite is unavailable: a held-out partition has "
            "not been implemented; use ROLE=tuning or exclude Type-3"
        )
    cache_root = args.cache_root.expanduser().resolve()
    results_root = args.results_root.expanduser().resolve()
    srcdiff = find_srcdiff(REPO_ROOT, args.srcdiff)
    srcmove = find_srcmove(REPO_ROOT, args.srcmove)
    if srcdiff is None:
        raise ValueError("srcdiff not found; pass --srcdiff")
    if srcmove is None:
        raise ValueError("srcMove not found; pass --srcmove")

    (compiled_result, compile_seconds) = _timed(
        lambda: ensure_compiled_dataset(
            data_root=cache_root,
            bce_dir=args.bce_dir,
            verify_source=args.verify_source,
        )
    )
    compiled, compiled_reused = compiled_result
    (srcdiff_observation, srcdiff_observation_seconds) = _timed(
        lambda: observe_executable(srcdiff)
    )
    (srcmove_observation, srcmove_observation_seconds) = _timed(
        lambda: observe_executable(srcmove)
    )
    pair_results: list[dict[str, Any]] = []

    pair_sets = (
        ((selected_pair_set, PAIR_SET_LABELS[selected_pair_set]),)
        if selected_pair_set is not None
        else PAIR_SETS
    )
    for pair_set, label in pair_sets:
        selection_mode = "census" if profile == "full" else profile
        with ProgressDisplay("selection", detail=f"{label} {selection_mode}") as progress:
            (selection_result, selection_seconds) = _timed(
                lambda pair_set=pair_set, progress=progress: (
                    create_selection(
                        compiled,
                        data_root=cache_root,
                        pair_set=pair_set,
                        mode="census",
                        role=args.role,
                        sample_size=args.sample_size,
                        seed=args.seed,
                        progress=progress,
                    )
                    if profile == "full"
                    else create_frozen_selection(
                        compiled,
                        data_root=cache_root,
                        pair_set=pair_set,
                        profile=profile,
                        role=args.role,
                    )
                )
            )
            selection_dir, selection_manifest, selection_reused = selection_result
            progress.finish(
                f"{selection_manifest['counts']['selected_frames']:,} tests",
                completion="reused" if selection_reused else "created",
            )

        (snapshot_result, snapshot_seconds) = _timed(
            lambda selection=selection_dir: materialize_compiled_selection(
                data_root=cache_root, selection=selection
            )
        )
        snapshot, snapshot_disposition = snapshot_result

        with ProgressDisplay(
            "srcDiff", total=snapshot.manifest["counts"]["selected"], detail=label
        ) as progress:
            callback, activity = _activity(progress)
            (corpus, corpus_seconds) = _timed(
                lambda: build_corpus(
                    data_root=cache_root,
                    input_snapshot=snapshot,
                    srcdiff=srcdiff,
                    timeout_seconds=args.srcdiff_timeout,
                    retry_failed=False,
                    activity_callback=callback,
                    srcdiff_observation=srcdiff_observation,
                )
            )
            corpus_disposition = "created" if activity["running"] else "reused"
            progress.finish(
                f"{corpus.manifest['counts']['semantic_eligible']:,} eligible",
                completion=corpus_disposition,
            )

        eligible = corpus.manifest["counts"]["semantic_eligible"]
        with ProgressDisplay(
            "srcMove execution", total=eligible, detail=label
        ) as progress:
            callback, _ = _activity(progress)
            (evaluation, evaluation_seconds) = _timed(
                lambda: evaluate_corpus(
                    data_root=cache_root,
                    results_root=results_root,
                    corpus=corpus,
                    srcmove=srcmove,
                    timeout_seconds=args.srcmove_timeout,
                    mode=RunMode.DEVELOPMENT,
                    activity_callback=callback,
                    srcmove_observation=srcmove_observation,
                )
            )
            run_dir, run_manifest, summary = evaluation
            counts = summary["counts"]
            passed = counts["oracle_pass"]
            selected = counts["selected"]
            if pair_set == "known-false-positive":
                outcome_detail = (
                    f"passed {passed:,}/{selected:,} selected; "
                    f"false acceptances {counts['srcmove_false_positive']:,}"
                )
            elif pair_set == "type3":
                strata = summary.get("strata", {}).get("type3_strength", {})
                band_detail = "; ".join(
                    f"{name} {values['strictly_classified']}/{values['selected']} strict, "
                    f"{values['detected']}/{values['selected']} detected"
                    for name, values in strata.items()
                )
                interpretation = (
                    "balanced strength sample"
                    if profile != "full"
                    else "observational census"
                )
                outcome_detail = f"{interpretation}; {band_detail}"
            else:
                outcome_detail = (
                    f"passed {passed:,}/{selected:,} selected; "
                    f"missed {counts['srcmove_miss']:,}"
                )
            progress.finish(
                outcome_detail,
                success=_pair_set_operational_pass(pair_set, counts),
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
    suite_dir = results_root / "bigclonebench" / "suite-runs" / suite_id
    suite = {
        "schema_version": 1,
        "suite_id": suite_id,
        "created_at": utc_now(),
        "request": {
            "profile": profile,
            "mode": "census" if profile == "full" else "preset",
            "role": args.role,
            "seed": args.seed,
            "sample_size": args.sample_size,
            "verify_source": args.verify_source,
            "pair_set": selected_pair_set,
        },
        "compiled_dataset": {
            "dataset_id": compiled.dataset_id,
            "disposition": "reused" if compiled_reused else "created",
            "seconds": compile_seconds,
        },
        "scoring_oracle_version": SCORING_ORACLE_VERSION,
        "tool_observation_seconds": {
            "srcdiff": srcdiff_observation_seconds,
            "srcmove": srcmove_observation_seconds,
        },
        "pair_sets": pair_results,
    }
    write_json_atomic(suite_dir / "summary.json", suite)
    passed = all(result["assessment"]["operational_pass"] for result in pair_results)
    return suite_dir, suite, passed


def _seconds(value: float) -> str:
    return f"{value:.3f}s"


def _print_report(directory: Path, suite: Mapping[str, Any]) -> None:
    dataset = suite["compiled_dataset"]
    pair_sets_passed = sum(
        result["assessment"]["operational_pass"] for result in suite["pair_sets"]
    )
    suite_passed = pair_sets_passed == len(suite["pair_sets"])
    has_observational = any(
        result["assessment"]["mode"] == "observational"
        for result in suite["pair_sets"]
    )
    suite_status = (
        "COMPLETE"
        if suite_passed and has_observational
        else "PASS"
        if suite_passed
        else "FAIL"
    )
    print()
    print(
        f"BigCloneBench suite: {suite_status} "
        f"({pair_sets_passed}/{len(suite['pair_sets'])} pair sets operationally complete)"
    )
    print(
        f"  dataset: {dataset['dataset_id']} "
        f"({dataset['disposition']}; {_seconds(dataset['seconds'])})"
    )
    print()
    for result in suite["pair_sets"]:
        counts = result["counts"]
        metrics = result["metrics"]
        elapsed = result["timings"]["process_seconds"]
        selected = counts["selected"]
        passed = counts["oracle_pass"]
        pass_rate = passed / selected if selected else 0.0
        observational = result["assessment"]["mode"] == "observational"
        status = (
            "OBS"
            if observational and result["assessment"]["operational_pass"]
            else "ERROR"
            if observational
            else "PASS"
            if passed == selected
            else "FAIL"
        )
        if observational:
            interpretation = result["assessment"].get("sample_interpretation")
            label = (
                "balanced strength sample"
                if interpretation == "balanced_strength_sample"
                else "observational census"
            )
            print(
                f"  {result['label']:<22} {status:<4}  {label}; "
                f"{selected:,} selected   srcMove {_seconds(elapsed)}"
            )
        else:
            print(
                f"  {result['label']:<22} {status:<4}  passed "
                f"{passed:,}/{selected:,} ({pass_rate:.1%})   "
                f"srcMove {_seconds(elapsed)}"
            )
        if result["pair_set"] == "known-false-positive":
            errors = sum(
                counts[name]
                for name in (
                    "upstream_failure",
                    "srcdiff_semantic_ineligible",
                    "srcmove_tool_failure",
                    "oracle_failure",
                )
            )
            diagnostic = (
                f"rejected {metrics['rejected']:,}/{selected:,} whole pairs; "
                f"false acceptances {metrics['accepted']:,}; "
                f"incidental moves {metrics['incidental']:,}; errors {errors:,}"
            )
        else:
            expected_kind = {
                "type1": "exact",
                "type2": "type2",
                "type3": "type3",
            }[result["pair_set"]]
            errors = sum(
                counts[name]
                for name in (
                    "upstream_failure",
                    "srcdiff_semantic_ineligible",
                    "srcmove_tool_failure",
                    "oracle_failure",
                )
            )
            diagnostic = (
                f"whole-fragment detections {metrics['whole_fragment_detected']:,}/"
                f"{selected:,}; expected class {expected_kind}; "
                f"wrong class {counts['wrong_classification']:,}; "
                f"misses {counts['srcmove_miss']:,}; errors {errors:,}"
            )
            if observational:
                diagnostic += "; observational results (misses do not fail suite)"
        print(" " * 26 + diagnostic)
        if observational:
            for name in ("very_strong", "strong", "moderate", "weak"):
                stratum = result.get("type3_strength_strata", {}).get(name)
                if not stratum:
                    continue
                stratum_selected = stratum["selected"]
                strict = stratum["strictly_classified"]
                detected = stratum["detected"]
                print(
                    " " * 26
                    + f"{name.replace('_', ' '):<12} strict {strict:,}/"
                    f"{stratum_selected:,} ({strict / stratum_selected:.1%}); "
                    f"detected {detected:,}/{stratum_selected:,} "
                    f"({detected / stratum_selected:.1%})"
                )
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
        f"  selected cases {unique_tests:,}   source rows {source_rows:,}   "
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
