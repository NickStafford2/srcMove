#!/usr/bin/env python3
"""Compare snapshot and normalized execution on the same selections."""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
import uuid
from pathlib import Path
from typing import Any, Mapping


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarking.provenance import utc_now
from benchmarking.storage import write_json_atomic
from benchmarking.tooling import find_srcdiff, find_srcmove
from bigMoveBench.benchmark_cases import publish_benchmark_cases
from bigMoveBench.evaluate import OUTCOMES
from bigMoveBench.normalized_execution import SerialBenchmarkExecutionRunner
from bigMoveBench.paths import DEFAULT_CACHE_ROOT


COMPARISON_FIELDS = (
    "outcome",
    "case_kind",
    "syntactic_type",
    "expected_match_kind",
    "observed_match_kind",
    "move_count",
    "semantic_reason",
    "type3_strength_stratum",
    "from_text_validation",
    "to_text_validation",
)
COUNT_FIELDS = ("selected", "eligible", "executed", *OUTCOMES)


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _csv_rows(path: Path) -> dict[str, dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None or "case_id" not in reader.fieldnames:
            raise ValueError(f"cases CSV has no case_id column: {path}")
        rows: dict[str, dict[str, str]] = {}
        for row in reader:
            case_id = row.get("case_id", "")
            if not case_id:
                raise ValueError(f"cases CSV contains an empty case_id: {path}")
            if case_id in rows:
                raise ValueError(f"cases CSV contains duplicate case_id {case_id}: {path}")
            rows[case_id] = dict(row)
    return rows


def compare_case_csv(reference: Path, normalized: Path) -> dict[str, Any]:
    """Compare the scientific result fields in two case-level CSV artifacts."""

    reference_rows = _csv_rows(reference)
    normalized_rows = _csv_rows(normalized)
    reference_ids = set(reference_rows)
    normalized_ids = set(normalized_rows)
    missing = sorted(reference_ids - normalized_ids)
    unexpected = sorted(normalized_ids - reference_ids)
    differences: list[dict[str, str]] = []
    for case_id in sorted(reference_ids & normalized_ids):
        left = reference_rows[case_id]
        right = normalized_rows[case_id]
        for field in COMPARISON_FIELDS:
            reference_value = left.get(field, "")
            normalized_value = right.get(field, "")
            if reference_value != normalized_value:
                differences.append(
                    {
                        "case_id": case_id,
                        "field": field,
                        "snapshot": reference_value,
                        "normalized": normalized_value,
                    }
                )
    return {
        "equivalent": not missing and not unexpected and not differences,
        "reference_cases": len(reference_rows),
        "normalized_cases": len(normalized_rows),
        "missing_case_ids": missing,
        "unexpected_case_ids": unexpected,
        "differences": differences,
    }


def _compare_counts(
    reference: Mapping[str, Any], normalized: Mapping[str, Any]
) -> list[dict[str, Any]]:
    differences = []
    for field in COUNT_FIELDS:
        left = reference.get(field, 0)
        right = normalized.get(field, 0)
        if left != right:
            differences.append(
                {"field": field, "snapshot": left, "normalized": right}
            )
    return differences


def run_equivalence(
    *,
    reference_summary: Path,
    cache_root: Path,
    results_root: Path,
    srcdiff: Path,
    srcmove: Path,
    srcdiff_timeout: float,
    srcmove_timeout: float,
) -> tuple[Path, dict[str, Any], bool]:
    reference_summary = reference_summary.expanduser().resolve()
    suite = _read_object(reference_summary)
    pair_sets = suite.get("pair_sets")
    if not isinstance(pair_sets, list) or not pair_sets:
        raise ValueError("reference suite contains no pair-set results")

    comparison_id = (
        "equivalence-"
        f"{utc_now().replace(':', '').replace('+', '-')}-{uuid.uuid4()}"
    )
    output_directory = (
        results_root.expanduser().resolve()
        / "bigMoveBench"
        / "equivalence"
        / comparison_id
    )
    comparisons: list[dict[str, Any]] = []
    for reference in pair_sets:
        if not isinstance(reference, Mapping):
            raise ValueError("reference pair-set result is invalid")
        pair_set = reference.get("pair_set")
        selection_id = reference.get("selection_id")
        run_directory = reference.get("run_directory")
        identity = (pair_set, selection_id, run_directory)
        if not all(isinstance(value, str) and value for value in identity):
            raise ValueError("reference pair-set result lacks execution identity")

        benchmark_cases, disposition = publish_benchmark_cases(
            data_root=cache_root, selection=selection_id
        )
        normalized_directory = output_directory / "normalized-runs" / pair_set
        _, normalized_summary = SerialBenchmarkExecutionRunner(
            benchmark_cases,
            run_dir=normalized_directory,
            srcdiff=srcdiff,
            srcmove=srcmove,
            srcdiff_timeout_seconds=srcdiff_timeout,
            srcmove_timeout_seconds=srcmove_timeout,
        ).run()
        case_comparison = compare_case_csv(
            Path(run_directory) / "cases.csv",
            normalized_directory / "cases.csv",
        )
        count_differences = _compare_counts(
            reference.get("counts", {}), normalized_summary.get("counts", {})
        )
        comparisons.append(
            {
                "pair_set": pair_set,
                "selection_id": selection_id,
                "benchmark_cases_id": benchmark_cases.benchmark_cases_id,
                "benchmark_cases_disposition": disposition,
                "snapshot_run_directory": run_directory,
                "normalized_run_directory": str(normalized_directory),
                "equivalent": case_comparison["equivalent"] and not count_differences,
                "case_comparison": case_comparison,
                "count_differences": count_differences,
            }
        )

    equivalent = all(item["equivalent"] for item in comparisons)
    result = {
        "schema_version": 1,
        "comparison_id": comparison_id,
        "created_at": utc_now(),
        "reference_suite_id": suite.get("suite_id"),
        "reference_summary": str(reference_summary),
        "equivalent": equivalent,
        "pair_sets": comparisons,
    }
    write_json_atomic(output_directory / "summary.json", result)
    return output_directory, result, equivalent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference_summary", type=Path)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    parser.add_argument("--results-root", type=Path, default=Path("benchmark-results"))
    parser.add_argument("--srcdiff", type=Path)
    parser.add_argument("--srcmove", type=Path)
    parser.add_argument("--srcdiff-timeout", type=float, default=60.0)
    parser.add_argument("--srcmove-timeout", type=float, default=300.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        srcdiff = find_srcdiff(REPO_ROOT, args.srcdiff)
        srcmove = find_srcmove(REPO_ROOT, args.srcmove)
        if srcdiff is None:
            raise ValueError("srcdiff not found; pass --srcdiff")
        if srcmove is None:
            raise ValueError("srcMove not found; pass --srcmove")
        directory, result, equivalent = run_equivalence(
            reference_summary=args.reference_summary,
            cache_root=args.cache_root,
            results_root=args.results_root,
            srcdiff=srcdiff,
            srcmove=srcmove,
            srcdiff_timeout=args.srcdiff_timeout,
            srcmove_timeout=args.srcmove_timeout,
        )
        for pair_set in result["pair_sets"]:
            comparison = pair_set["case_comparison"]
            print(
                f"{pair_set['pair_set']}: "
                f"{'EQUIVALENT' if pair_set['equivalent'] else 'DIFFERENT'} "
                f"({comparison['reference_cases']} cases, "
                f"{len(comparison['differences'])} field differences)"
            )
        print(f"summary={directory / 'summary.json'}")
        return 0 if equivalent else 1
    except (OSError, ValueError, sqlite3.Error, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
