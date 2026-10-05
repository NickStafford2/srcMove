"""python -m bigMoveBench.browser --results-root ROOT --cache-root CACHE COMMAND"""
import argparse
import json
from pathlib import Path
import sqlite3
import sys

from bigMoveBench.browser.reader import list_cases, list_runs, show_case, show_run, show_source


def main():
    parser = argparse.ArgumentParser(description="Read retained BigMoveBench results without executing tests.")
    parser.add_argument("--results-root", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list-runs")
    show = sub.add_parser("show-run")
    show.add_argument("run_id")
    listing = sub.add_parser("list-cases")
    listing.add_argument("run_id")
    for key in ("category", "outcome", "query"):
        listing.add_argument("--" + key, default="")
    listing.add_argument("--basis", default="original")
    listing.add_argument("--offset", type=int, default=0)
    listing.add_argument("--limit", type=int, default=50)
    detail = sub.add_parser("show-case")
    for key in ("run_id", "category", "case_id"):
        detail.add_argument(key)
    source = sub.add_parser("show-source")
    for key in ("run_id", "category", "case_id"):
        source.add_argument(key)
    args = parser.parse_args()
    try:
        if args.command == "list-runs":
            result = list_runs(args.results_root)
        elif args.command == "show-run":
            result = show_run(args.results_root, args.run_id)
        elif args.command == "list-cases":
            result = list_cases(args.results_root, args.cache_root, args.run_id,
                category=args.category, outcome=args.outcome, query=args.query,
                basis=args.basis, offset=args.offset, limit=args.limit)
        elif args.command == "show-source":
            result = show_source(args.results_root, args.cache_root, args.run_id, args.category, args.case_id)
        else:
            result = show_case(args.results_root, args.cache_root, args.run_id, args.category, args.case_id)
    except (OSError, ValueError, KeyError, sqlite3.Error) as error:
        print(json.dumps({"schema_version": 1, "error": str(error),
            "error_kind": "not_found" if isinstance(error, FileNotFoundError) else "invalid"}))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
