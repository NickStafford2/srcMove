#!/usr/bin/env python3
"""Explain BigCloneBench content identities excluded for conflicting labels."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from contextlib import closing
from pathlib import Path
from typing import Any, Mapping


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.bigclonebench.compile import DEFAULT_DATA_ROOT
from benchmarks.bigclonebench.compiled import load_compiled_dataset
from benchmarks.bigclonebench.selection import (
    _catalog_connection,
    content_label_conflict_ids,
    content_label_conflicts,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "dataset",
        nargs="?",
        help=(
            "Compiled dataset ID or directory; inferred when the index has one dataset."
        ),
    )
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument(
        "--limit", type=int, default=5, help="Examples to print. Default: 5."
    )
    parser.add_argument(
        "--json", action="store_true", help="Write the report as JSON."
    )
    return parser.parse_args()


def _dataset(args: argparse.Namespace) -> str | Path:
    if args.dataset:
        return args.dataset
    index_path = (
        args.data_root.expanduser().resolve() / "bigclonebench/compiled/index.json"
    )
    value = json.loads(index_path.read_text(encoding="utf-8"))
    entries = value.get("entries") if isinstance(value, Mapping) else None
    identifiers = sorted(set(entries.values())) if isinstance(entries, Mapping) else []
    if len(identifiers) != 1:
        raise ValueError(
            "dataset is required unless the compiled index identifies exactly one dataset"
        )
    return str(identifiers[0])


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    if args.limit < 0:
        raise ValueError("limit must be nonnegative")
    compiled = load_compiled_dataset(
        _dataset(args), data_root=args.data_root, verification="identity"
    )
    with closing(_catalog_connection(compiled)) as connection:
        identifiers = content_label_conflict_ids(connection)
        conflicts = list(content_label_conflicts(connection, identifiers))

    positive_types: Counter[int] = Counter()
    positive_rows = negative_rows = 0
    same_function_pair_conflicts = 0
    for conflict in conflicts:
        positive_pairs: set[tuple[int, int]] = set()
        negative_pairs: set[tuple[int, int]] = set()
        for row in conflict["rows"]:
            pair = tuple(
                sorted(
                    (
                        int(row["function_one"]["function_id"]),
                        int(row["function_two"]["function_id"]),
                    )
                )
            )
            if row["pair_kind"] == "positive":
                positive_rows += 1
                positive_types[int(row["syntactic_type"])] += 1
                positive_pairs.add(pair)
            else:
                negative_rows += 1
                negative_pairs.add(pair)
        same_function_pair_conflicts += int(bool(positive_pairs & negative_pairs))

    return {
        "schema_version": 1,
        "dataset_id": compiled.dataset_id,
        "content_conflict_count": len(conflicts),
        "cause": (
            "Positive and known-false-positive BigCloneBench rows produced the same "
            "unordered pair of extracted fragment contents. The synthetic benchmark "
            "cannot preserve label-relevant source context, so these content identities "
            "are excluded from scored selections."
        ),
        "positive_catalog_rows_by_syntactic_type": {
            str(key): positive_types[key] for key in sorted(positive_types)
        },
        "positive_catalog_rows": positive_rows,
        "known_false_positive_catalog_rows": negative_rows,
        "same_bigclonebench_function_pair_conflicts": same_function_pair_conflicts,
        "examples": conflicts[: args.limit],
    }


def _print_report(report: Mapping[str, Any]) -> None:
    print(f"BigCloneBench content-label conflicts: {report['content_conflict_count']}")
    print(f"  dataset: {report['dataset_id']}")
    print(f"  cause: {report['cause']}")
    print(
        "  contributing catalog rows: "
        f"positive {report['positive_catalog_rows']}, "
        f"known false positive {report['known_false_positive_catalog_rows']}"
    )
    print(
        "  same BigCloneBench function-pair conflicts: "
        f"{report['same_bigclonebench_function_pair_conflicts']}"
    )
    if report["positive_catalog_rows_by_syntactic_type"]:
        strata = ", ".join(
            f"Type {kind}: {count}"
            for kind, count in report["positive_catalog_rows_by_syntactic_type"].items()
        )
        print(f"  positive syntactic types: {strata}")
    for conflict in report["examples"]:
        print(f"  example: {conflict['unordered_pair_id']}")
        for row in conflict["rows"]:
            print(
                "    "
                f"{row['pair_kind']} Type {row['syntactic_type']} "
                f"functions {row['function_one']['function_id']},"
                f"{row['function_two']['function_id']}"
            )


def main() -> int:
    args = parse_args()
    try:
        report = build_report(args)
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            _print_report(report)
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
