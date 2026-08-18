#!/usr/bin/env python3
"""Run an explicitly configured repository benchmark suite."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.repositories.run_case import load_case_config, validate_series_name


DEFAULT_CONFIG = SCRIPT_DIR / "suites.json"
DEFAULT_DATA_ROOT = REPO_ROOT / "benchmark-data"
RUNNER = SCRIPT_DIR / "run_case.py"


@dataclass(frozen=True)
class Suite:
    name: str
    description: str
    cases: tuple[str, ...]


@dataclass(frozen=True)
class SuiteConfiguration:
    default_suite: str
    suites: Mapping[str, Suite]


@dataclass(frozen=True)
class CaseOutcome:
    case: str
    returncode: int
    entry: Mapping[str, object] | None


def _require_string(value: object, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} must be a non-empty string")
    return value


def validate_case(case: str, benchmark_root: Path = SCRIPT_DIR) -> None:
    case_dir = benchmark_root / case
    if not case_dir.is_dir():
        raise ValueError(f"unknown repository benchmark case: {case}")
    info_json = case_dir / "info.json"
    if not info_json.is_file():
        raise ValueError(f"repository benchmark case is missing info.json: {case}")
    config = load_case_config(info_json)
    if config["old_rev"] is None or config["new_rev"] is None:
        raise ValueError(
            f"repository benchmark case has no configured revisions: {case}"
        )


def load_suite_configuration(
    path: Path = DEFAULT_CONFIG,
    *,
    benchmark_root: Path = SCRIPT_DIR,
) -> SuiteConfiguration:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError(f"suite configuration not found: {path}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"malformed suite configuration {path}: {error}") from error
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError(f"unsupported or malformed suite configuration: {path}")
    default_suite = _require_string(value.get("default_suite"), "default_suite")
    raw_suites = value.get("suites")
    if not isinstance(raw_suites, dict) or not raw_suites:
        raise ValueError("suites must be a non-empty object")

    suites: dict[str, Suite] = {}
    for raw_name, raw_suite in raw_suites.items():
        name = _require_string(raw_name, "suite name")
        if not isinstance(raw_suite, dict):
            raise ValueError(f"suite {name!r} must be an object")
        description = _require_string(
            raw_suite.get("description"), f"suite {name!r} description"
        )
        raw_cases = raw_suite.get("cases")
        if not isinstance(raw_cases, list) or not raw_cases:
            raise ValueError(f"suite {name!r} cases must be a non-empty list")
        cases = tuple(
            _require_string(case, f"suite {name!r} case") for case in raw_cases
        )
        duplicates = sorted({case for case in cases if cases.count(case) > 1})
        if duplicates:
            raise ValueError(
                f"suite {name!r} contains duplicate cases: {', '.join(duplicates)}"
            )
        for case in cases:
            validate_case(case, benchmark_root)
        suites[name] = Suite(name, description, cases)

    if default_suite not in suites:
        raise ValueError(f"default suite is not defined: {default_suite}")
    return SuiteConfiguration(default_suite, suites)


def select_cases(
    configuration: SuiteConfiguration,
    suite_name: str | None,
    included: Sequence[str],
    excluded: Sequence[str],
    *,
    benchmark_root: Path = SCRIPT_DIR,
) -> tuple[str, tuple[str, ...]]:
    selected_suite = suite_name or configuration.default_suite
    if selected_suite not in configuration.suites:
        raise ValueError(f"unknown repository benchmark suite: {selected_suite}")
    cases = list(configuration.suites[selected_suite].cases)
    for case in included:
        validate_case(case, benchmark_root)
        if case not in cases:
            cases.append(case)
    unknown_exclusions = [case for case in excluded if case not in cases]
    if unknown_exclusions:
        raise ValueError(
            "cannot exclude unselected case(s): " + ", ".join(unknown_exclusions)
        )
    excluded_set = set(excluded)
    cases = [case for case in cases if case not in excluded_set]
    if not cases:
        raise ValueError("repository benchmark selection is empty")
    return selected_suite, tuple(cases)


def default_series(suite_name: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{suite_name}-{stamp}"


def _new_entry(
    series_dir: Path, before: set[Path], case: str
) -> Mapping[str, object] | None:
    candidates = set(series_dir.glob("repository-*.json")) - before
    entries = []
    for path in candidates:
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if entry.get("case") == case:
            entries.append((path.stat().st_mtime_ns, entry))
    return max(entries, default=(0, None), key=lambda item: item[0])[1]


def run_case(
    case: str,
    *,
    series: str,
    data_root: Path,
    position: bool,
    fetch: bool,
    offline: bool,
    executor: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> CaseOutcome:
    series_dir = data_root / "repository-runs" / series
    before = set(series_dir.glob("repository-*.json"))
    command = [
        sys.executable,
        str(RUNNER),
        case,
        "--series",
        series,
        "--data-root",
        str(data_root),
    ]
    if position:
        command.append("--position")
    if fetch:
        command.append("--fetch")
    if offline:
        command.append("--offline")
    result = executor(command, cwd=REPO_ROOT, text=True)
    return CaseOutcome(case, result.returncode, _new_entry(series_dir, before, case))


def _duration(value: object) -> str:
    return "—" if not isinstance(value, (int, float)) else f"{value:.1f}s"


def _moves(entry: Mapping[str, object] | None) -> str:
    if not entry:
        return "—"
    results = entry.get("results", {})
    if not isinstance(results, dict) or not isinstance(results.get("move_count"), int):
        return "—"
    return str(results["move_count"])


def print_summary(
    suite_name: str,
    series: str,
    outcomes: Sequence[CaseOutcome],
    summary_path: Path,
) -> None:
    completed = sum(
        outcome.entry is not None and outcome.entry.get("status") == "completed"
        for outcome in outcomes
    )
    failed = len(outcomes) - completed
    status = "COMPLETED" if failed == 0 else "COMPLETED WITH FAILURES"
    print()
    print(f"Repository benchmark suite: {status}")
    print()
    print(f"  Suite:       {suite_name}")
    print(f"  Series:      {series}")
    print(f"  Cases:       {completed} completed, {failed} failed, {len(outcomes)} selected")
    print()
    print(f"  {'Repository':<24} {'Status':<20} {'srcDiff':>9} {'srcMove':>9} {'Moves':>7}")
    for outcome in outcomes:
        entry = outcome.entry or {}
        status_text = str(entry.get("status") or f"exit {outcome.returncode}")
        srcdiff = entry.get("srcdiff_attempt", {})
        srcmove = entry.get("srcmove_attempt", {})
        srcdiff_time = _duration(
            srcdiff.get("elapsed_seconds") if isinstance(srcdiff, dict) else None
        )
        srcmove_time = _duration(
            srcmove.get("elapsed_seconds") if isinstance(srcmove, dict) else None
        )
        print(
            f"  {outcome.case:<24} {status_text:<20} "
            f"{srcdiff_time:>9} {srcmove_time:>9} {_moves(outcome.entry):>7}"
        )
    print()
    print("Artifacts:")
    print(f"  Series summary: {summary_path.resolve()}")


def suite_exit_code(outcomes: Sequence[CaseOutcome]) -> int:
    return 1 if any(outcome.returncode != 0 for outcome in outcomes) else 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run an explicit, deterministic repository benchmark suite."
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--suite", help="Configured suite name; defaults to standard.")
    parser.add_argument(
        "--case", action="append", default=[], help="Add one configured case. Repeatable."
    )
    parser.add_argument(
        "--exclude-case", action="append", default=[],
        help="Remove one selected case. Repeatable."
    )
    parser.add_argument("--series", help="Shared output series; defaults to a UTC name.")
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--list", action="store_true", help="List suites without running.")
    parser.add_argument("--position", action="store_true")
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--offline", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.fetch and args.offline:
        print("error: --fetch and --offline cannot be used together", file=sys.stderr)
        return 2
    try:
        configuration = load_suite_configuration(args.config)
        if args.list:
            print(f"Default suite: {configuration.default_suite}")
            for suite in configuration.suites.values():
                marker = " (default)" if suite.name == configuration.default_suite else ""
                print(f"\n{suite.name}{marker}: {suite.description}")
                for case in suite.cases:
                    print(f"  {case}")
            return 0
        suite_name, cases = select_cases(
            configuration, args.suite, args.case, args.exclude_case
        )
        series = args.series or default_series(suite_name)
        validate_series_name(series)
    except (RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    data_root = args.data_root.expanduser().resolve()
    print(f"Repository benchmark suite: {suite_name}")
    print(f"Series: {series}")
    print(f"Cases: {', '.join(cases)}")
    outcomes = []
    for position, case in enumerate(cases, start=1):
        print(f"\n=== Repository {position}/{len(cases)}: {case} ===", flush=True)
        outcomes.append(
            run_case(
                case, series=series, data_root=data_root,
                position=args.position, fetch=args.fetch, offline=args.offline,
            )
        )
    summary_path = data_root / "repository-runs" / series / "summary.csv"
    print_summary(suite_name, series, outcomes, summary_path)
    return suite_exit_code(outcomes)


if __name__ == "__main__":
    raise SystemExit(main())
