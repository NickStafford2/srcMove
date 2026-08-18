#!/usr/bin/env python3
"""Generate cases, snapshot inputs, build a corpus, and evaluate BigCloneBench."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path
from typing import Callable


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
TESTS_ROOT = REPO_ROOT / "tests"
for import_root in (REPO_ROOT, TESTS_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from benchmarks.bigclonebench.adapter import (
    SEMANTIC_ORACLE_VERSION,
    BigCloneBenchAdapter,
)
from benchmarks.bigclonebench.evaluate import write_evaluation
from benchmarks.bigclonebench.generate import preflight
from benchmarks.contracts import RunMode
from benchmarks.corpus import create_input_snapshot, generate_corpus, run_corpus
from benchmarks.progress import ProgressDisplay
from support.tooling import find_srcdiff, find_srcmove


DEFAULT_DATA_ROOT = REPO_ROOT / "benchmark-data"
DEFAULT_CASES_ROOT = SCRIPT_DIR / "cases"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    stages = parser.add_subparsers(dest="stage", required=True)

    stages.add_parser("preflight")

    cases = stages.add_parser("cases", help="Generate synthetic source cases.")
    cases.add_argument("--clone-type", choices=("type1", "type2"), default="type1")
    cases.add_argument("--limit", type=int, default=1)
    cases.add_argument("--candidate-limit", type=int)
    cases.add_argument("--min-tokens", type=int, default=50)
    cases.add_argument(
        "--dedupe",
        choices=("none", "raw-text-pair", "trimmed-text-pair"),
        default="raw-text-pair",
    )
    cases.add_argument(
        "--text-change", choices=("any", "raw-different"), default="any"
    )
    cases.add_argument(
        "--selection-role",
        choices=("tuning", "evaluation"),
        default="tuning",
    )
    cases.add_argument("--out-dir", type=Path, default=DEFAULT_CASES_ROOT)

    snapshot = stages.add_parser(
        "snapshot",
        help="Freeze and checksum generated old/new source pairs.",
    )
    snapshot.add_argument(
        "--clone-type", choices=("type1", "type2"), default="type1"
    )
    snapshot.add_argument("--cases-dir", type=Path, default=DEFAULT_CASES_ROOT)

    corpus = stages.add_parser("corpus", help="Generate immutable srcDiff XML.")
    corpus.add_argument(
        "input_snapshot", help="Input snapshot ID, directory, or manifest path."
    )
    corpus.add_argument("--srcdiff", type=Path)
    corpus.add_argument("--timeout", type=float, default=60.0)
    corpus.add_argument("--retry-failed", action="store_true")

    evaluate = stages.add_parser("evaluate", help="Run and strictly score srcMove.")
    evaluate.add_argument("corpus")
    evaluate.add_argument("--srcmove", type=Path)
    evaluate.add_argument("--timeout", type=float, default=300.0)
    evaluate.add_argument(
        "--mode",
        choices=[mode.value for mode in RunMode],
        default="development",
    )

    benchmark = stages.add_parser(
        "benchmark",
        help="Snapshot generated cases, build the corpus, and evaluate srcMove.",
    )
    benchmark.add_argument(
        "--clone-type", choices=("type1", "type2"), default="type1"
    )
    benchmark.add_argument("--cases-dir", type=Path, default=DEFAULT_CASES_ROOT)
    benchmark.add_argument("--srcdiff", type=Path)
    benchmark.add_argument("--srcmove", type=Path)
    benchmark.add_argument("--srcdiff-timeout", type=float, default=60.0)
    benchmark.add_argument("--srcmove-timeout", type=float, default=300.0)
    benchmark.add_argument("--retry-failed", action="store_true")
    benchmark.add_argument(
        "--mode",
        choices=[mode.value for mode in RunMode],
        default="development",
    )
    return parser.parse_args()


def _syntactic_type(clone_type: str) -> int:
    return int(clone_type.removeprefix("type"))


def build_corpus(
    *,
    data_root: Path,
    input_snapshot: str | Path,
    srcdiff: Path,
    timeout_seconds: float,
    retry_failed: bool,
    activity_callback: Callable[[str, str], None] | None = None,
) -> tuple[Path, dict]:
    return generate_corpus(
        data_root=data_root,
        input_snapshot=input_snapshot,
        srcdiff=srcdiff,
        timeout_seconds=timeout_seconds,
        use_position=True,
        use_archive=False,
        retry_failed=retry_failed,
        semantic_validator=BigCloneBenchAdapter.validate_semantics,
        semantic_oracle={
            "name": "bigclonebench-payload-exposure",
            "version": SEMANTIC_ORACLE_VERSION,
        },
        activity_callback=activity_callback,
    )


def evaluate_corpus(
    *,
    data_root: Path,
    corpus: str | Path,
    srcmove: Path,
    timeout_seconds: float,
    mode: RunMode,
    activity_callback: Callable[[str, str], None] | None = None,
) -> tuple[Path, dict, dict]:
    run_dir, run_manifest = run_corpus(
        data_root=data_root,
        corpus=corpus,
        srcmove=srcmove,
        timeout_seconds=timeout_seconds,
        mode=mode,
        require_semantic_eligible=True,
        activity_callback=activity_callback,
    )
    corpus_path = Path(corpus)
    if corpus_path.is_file():
        corpus_dir = corpus_path.resolve().parent
    elif corpus_path.is_dir():
        corpus_dir = corpus_path.resolve()
    else:
        corpus_dir = data_root / "corpora" / str(corpus)
    corpus_manifest = json.loads(
        (corpus_dir / "manifest.json").read_text(encoding="utf-8")
    )
    summary = write_evaluation(
        run_dir=run_dir,
        run_manifest=run_manifest,
        corpus_dir=corpus_dir,
        corpus_manifest=corpus_manifest,
    )
    return run_dir, run_manifest, summary


def _case_progress(progress: ProgressDisplay) -> Callable[[str, str], None]:
    completed = 0

    def report(activity: str, case_id: str) -> None:
        nonlocal completed
        if activity == "running":
            progress.update(completed, detail=case_id)
            return
        if activity in {"accepted", "completed", "reused", "failed"}:
            completed += 1
            progress.update(completed, detail=case_id)
        if activity == "failed":
            progress.event(f"{case_id} failed; continuing (details are preserved)")

    return report


def _prepare_snapshot(
    *, data_root: Path, adapter: BigCloneBenchAdapter
) -> tuple[Path, dict]:
    disposition = "prepared"

    def record_disposition(value: str) -> None:
        nonlocal disposition
        disposition = value

    with ProgressDisplay(
        "snapshot", detail="hashing generated inputs"
    ) as progress:
        directory, manifest = create_input_snapshot(
            data_root=data_root,
            adapter=adapter,
            source=adapter.source_manifest(),
            status_callback=record_disposition,
        )
        case_detail = f"{manifest['counts']['selected']} cases"
        if disposition == "reused":
            case_detail += " verified"
        progress.finish(case_detail, completion=disposition)
    return directory, manifest


_OUTCOME_LABELS = {
    "upstream_failure": "srcDiff tool failure",
    "srcdiff_semantic_ineligible": "srcDiff semantic rejection",
    "srcmove_tool_failure": "srcMove tool failure",
    "srcmove_miss": "srcMove miss",
    "wrong_classification": "wrong classification",
    "oracle_failure": "oracle validation failure",
}

_DIAGNOSTIC_LABELS = {
    "no_move_raw_different": "no move; raw text differs",
}

_PLURAL_LABELS = {
    "srcMove miss": "srcMove misses",
}


def _count_label(count: int, singular: str, plural: str | None = None) -> str:
    label = singular if count == 1 else plural or _PLURAL_LABELS.get(
        singular, singular + "s"
    )
    return f"{count:,} {label}"


def _report_benchmark_result(directory: Path, summary: dict) -> bool:
    counts = summary["counts"]
    failure_count = counts["selected"] - counts["oracle_pass"]
    selected = counts["selected"]
    pass_rate = counts["oracle_pass"] / selected if selected else 0.0
    declared_slice = summary.get("declared_slice", {})
    selection = declared_slice.get("selection", {}) or {}
    clone_type = str(declared_slice.get("clone_type", "unknown"))
    clone_type_label = (
        f"Type-{clone_type.removeprefix('type')}"
        if clone_type.startswith("type")
        else clone_type
    )
    distinct_pairs = declared_slice.get("distinct_raw_text_pair_count", 0)
    functionality_groups = declared_slice.get("functionality_group_count", 0)
    candidate_count = declared_slice.get("row_count_before_deduplication", 0)

    print()
    print(f"BigCloneBench result: {'PASS' if failure_count == 0 else 'FAIL'}")
    print()
    print(
        f"  Strict oracle:  {counts['oracle_pass']:,}/{selected:,} passed "
        f"({pass_rate:.1%})"
    )
    print(f"  Failed cases:   {failure_count:,}")
    print()
    print(f"  Clone type:     {clone_type_label}")
    print(f"  Selection role: {selection.get('role', 'unknown')}")
    print(
        f"  Selection:      {selected:,} cases from "
        f"{candidate_count:,} eligible candidates"
    )
    print(
        f"  Diversity:      {distinct_pairs:,} distinct raw-text pairs across "
        f"{functionality_groups:,} functionality groups"
    )
    print(
        f"  Filters:        min {declared_slice.get('min_tokens', 'unknown')} tokens; "
        f"{declared_slice.get('dedupe', 'unknown')} dedupe; "
        f"text change: {declared_slice.get('text_change', 'unknown')}"
    )

    if failure_count:
        categories = [
            _count_label(counts[name], label)
            for name, label in _OUTCOME_LABELS.items()
            if counts[name]
        ]
        print()
        print("Failures:")
        print(f"  Breakdown: {', '.join(categories)}")
        with (directory / "cases.csv").open(
            encoding="utf-8", newline=""
        ) as stream:
            failed_rows = [
                row
                for row in csv.DictReader(stream)
                if row["outcome"] != "oracle_pass"
            ]
        for row in failed_rows[:5]:
            outcome = _OUTCOME_LABELS.get(
                row["outcome"], row["outcome"].replace("_", " ")
            )
            diagnostic = _DIAGNOSTIC_LABELS.get(
                row["diagnostic_class"],
                row["diagnostic_class"].replace("_", " "),
            )
            print(f"  - {row['case_id']}: {outcome} ({diagnostic})")
        if len(failed_rows) > 5:
            print(f"  - … and {len(failed_rows) - 5:,} more")

    print()
    print("Artifacts:")
    print(f"  Run directory: {directory}")
    print("  Files:         summary.json, cases.csv")
    if failure_count:
        print()
        print(
            "Benchmark failed: "
            f"{_count_label(failure_count, 'case')} did not pass the strict oracle."
        )
    sys.stdout.flush()
    return failure_count == 0


def main() -> int:
    args = parse_args()
    data_root = args.data_root.expanduser().resolve()
    exit_code = 0
    try:
        if args.stage == "preflight":
            failures = preflight()
            if failures:
                print(
                    "error: BigCloneBench is an external manual prerequisite; "
                    "nothing was downloaded.",
                    file=sys.stderr,
                )
                for failure in failures:
                    print(f"  - {failure}", file=sys.stderr)
                print(
                    "See benchmarks/bigclonebench/README.md for setup guidance.",
                    file=sys.stderr,
                )
                return 2
            print("BigCloneBench preflight passed")
            return 0

        if args.stage == "cases":
            command = [
                sys.executable,
                str(SCRIPT_DIR / "generate.py"),
                "--syntactic-type",
                str(_syntactic_type(args.clone_type)),
                "--limit",
                str(args.limit),
                "--min-tokens",
                str(args.min_tokens),
                "--dedupe",
                args.dedupe,
                "--text-change",
                args.text_change,
                "--selection-role",
                args.selection_role,
                "--out-dir",
                str(args.out_dir),
                "--overwrite",
            ]
            if args.candidate_limit is not None:
                command.extend(["--candidate-limit", str(args.candidate_limit)])
            return subprocess.run(command, cwd=REPO_ROOT, check=False).returncode

        if args.stage == "snapshot":
            adapter = BigCloneBenchAdapter(
                args.cases_dir, _syntactic_type(args.clone_type)
            )
            directory, manifest = _prepare_snapshot(
                data_root=data_root, adapter=adapter
            )
            print(f"input_snapshot_id={manifest['input_snapshot_id']}")
        elif args.stage == "corpus":
            srcdiff = find_srcdiff(REPO_ROOT, args.srcdiff)
            if srcdiff is None:
                raise ValueError("srcdiff not found; pass --srcdiff")
            with ProgressDisplay("srcDiff", detail="preparing corpus") as progress:
                directory, manifest = build_corpus(
                    data_root=data_root,
                    input_snapshot=args.input_snapshot,
                    srcdiff=srcdiff,
                    timeout_seconds=args.timeout,
                    retry_failed=args.retry_failed,
                    activity_callback=_case_progress(progress),
                )
                progress.set_total(
                    manifest["counts"]["selected"],
                    completed=manifest["counts"]["selected"],
                )
                progress.finish(
                    f"{manifest['counts']['accepted']} accepted, "
                    f"{manifest['counts']['failed']} failed"
                )
            print(f"corpus_id={manifest['corpus_id']}")
            if manifest["counts"]["failed"]:
                print(
                    f"failed_cases={manifest['counts']['failed']}",
                    file=sys.stderr,
                )
                exit_code = 1
        elif args.stage == "evaluate":
            srcmove = find_srcmove(REPO_ROOT, args.srcmove)
            if srcmove is None:
                raise ValueError("srcMove not found; pass --srcmove")
            with ProgressDisplay("srcMove", detail="evaluating corpus") as progress:
                directory, manifest, summary = evaluate_corpus(
                    data_root=data_root,
                    corpus=args.corpus,
                    srcmove=srcmove,
                    timeout_seconds=args.timeout,
                    mode=RunMode(args.mode),
                    activity_callback=_case_progress(progress),
                )
                progress.set_total(
                    manifest["counts"]["semantic_eligible"],
                    completed=manifest["counts"]["executed"],
                )
                progress.finish(
                    f"{manifest['counts']['completed']} executed, "
                    f"{manifest['counts']['failed']} tool failures"
                )
            if not _report_benchmark_result(directory, summary):
                return 1
            return 0
        else:
            srcdiff = find_srcdiff(REPO_ROOT, args.srcdiff)
            srcmove = find_srcmove(REPO_ROOT, args.srcmove)
            if srcdiff is None:
                raise ValueError("srcdiff not found; pass --srcdiff")
            if srcmove is None:
                raise ValueError("srcMove not found; pass --srcmove")
            adapter = BigCloneBenchAdapter(
                args.cases_dir, _syntactic_type(args.clone_type)
            )
            _, snapshot_manifest = _prepare_snapshot(
                data_root=data_root, adapter=adapter
            )
            with ProgressDisplay(
                "srcDiff", total=snapshot_manifest["counts"]["selected"]
            ) as progress:
                corpus_dir, corpus_manifest = build_corpus(
                    data_root=data_root,
                    input_snapshot=snapshot_manifest["input_snapshot_id"],
                    srcdiff=srcdiff,
                    timeout_seconds=args.srcdiff_timeout,
                    retry_failed=args.retry_failed,
                    activity_callback=_case_progress(progress),
                )
                progress.finish(
                    f"{corpus_manifest['counts']['accepted']} accepted, "
                    f"{corpus_manifest['counts']['failed']} failed"
                )
            if corpus_manifest["counts"]["failed"]:
                exit_code = 1
            eligible = corpus_manifest["counts"]["semantic_eligible"]
            with ProgressDisplay("srcMove", total=eligible) as progress:
                directory, manifest, summary = evaluate_corpus(
                    data_root=data_root,
                    corpus=corpus_dir,
                    srcmove=srcmove,
                    timeout_seconds=args.srcmove_timeout,
                    mode=RunMode(args.mode),
                    activity_callback=_case_progress(progress),
                )
                progress.finish(
                    f"{manifest['counts']['completed']} executed, "
                    f"{manifest['counts']['failed']} tool failures"
                )
            if not _report_benchmark_result(directory, summary):
                return 1
            return exit_code
        print(f"directory={directory}")
        return exit_code
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
