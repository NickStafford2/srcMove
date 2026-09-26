"""Run semantic move-selection cases against one or more srcMove builds.

Hypothesis misses are measurements. Contract misses can optionally fail the
process. Invalid fixtures, malformed results, and failed tool executions are
always hard failures.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarking.execution import execute_attempt
from benchmarking.provenance import observe_file, utc_now
from benchmarking.srcdiff_validation import validate_srcdiff_xml
from benchmarking.storage import write_json_atomic
from benchmarking.tooling import find_srcmove
from performance.benchmark import parse_named_path, parse_profile_output, validate_name


CATALOG_SCHEMA_VERSION = 2
RUN_SCHEMA_VERSION = 1
SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9_]*$")
ALLOWED_MATCH_KINDS = {"type1", "type2", "type3"}
ALLOWED_INPUT_SHAPES = {"single_file", "archive"}
ALLOWED_CASE_STATUSES = {"contract", "hypothesis"}


class CatalogError(ValueError):
    """The benchmark catalog cannot be interpreted safely."""


def normalize_text(value: str) -> str:
    """Compare raw source text while ignoring formatting-only whitespace."""

    return " ".join(value.split())


def _validate_expectation(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CatalogError(f"{context}: expectation must be an object")
    result = dict(value)
    for field in ("from", "to"):
        text = result.get(field)
        if not isinstance(text, str) or not normalize_text(text):
            raise CatalogError(f"{context}: {field} must be non-empty text")
    kinds = result.get("match_kinds")
    if kinds is not None:
        if (
            not isinstance(kinds, list)
            or not kinds
            or not all(isinstance(kind, str) and kind in ALLOWED_MATCH_KINDS for kind in kinds)
        ):
            raise CatalogError(
                f"{context}: match_kinds must contain type1, type2, or type3"
            )
    return result


def load_catalog(path: Path) -> list[dict[str, Any]]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CatalogError(f"cannot read catalog {path}: {error}") from error
    if not isinstance(document, dict) or document.get("schema_version") != CATALOG_SCHEMA_VERSION:
        raise CatalogError("catalog schema_version must be 2")
    raw_cases = document.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise CatalogError("catalog cases must be a non-empty array")

    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ordinal, value in enumerate(raw_cases, start=1):
        context = f"case {ordinal}"
        if not isinstance(value, dict):
            raise CatalogError(f"{context}: case must be an object")
        case_id = value.get("id")
        if not isinstance(case_id, str) or SAFE_ID.fullmatch(case_id) is None:
            raise CatalogError(f"{context}: id must use lowercase letters, digits, and underscores")
        if case_id in seen:
            raise CatalogError(f"duplicate case id: {case_id}")
        seen.add(case_id)
        status = value.get("status")
        if status not in ALLOWED_CASE_STATUSES:
            raise CatalogError(
                f"{case_id}: status must be contract or hypothesis"
            )
        raw_input = value.get("input")
        if not isinstance(raw_input, str) or not raw_input:
            raise CatalogError(f"{case_id}: input must be a relative path")
        relative_input = Path(raw_input)
        if relative_input.is_absolute() or ".." in relative_input.parts:
            raise CatalogError(f"{case_id}: input path is unsafe: {raw_input!r}")
        input_path = (path.parent / relative_input).resolve()
        try:
            input_path.relative_to(path.parent.resolve())
        except ValueError as error:
            raise CatalogError(f"{case_id}: resolved input escapes the catalog directory") from error
        if not input_path.is_file():
            raise CatalogError(f"{case_id}: input does not exist: {input_path}")
        required = value.get("required", [])
        forbidden = value.get("forbidden", [])
        if not isinstance(required, list) or not isinstance(forbidden, list):
            raise CatalogError(f"{case_id}: required and forbidden must be arrays")
        input_shape = value.get("input_shape", "single_file")
        if input_shape not in ALLOWED_INPUT_SHAPES:
            raise CatalogError(
                f"{case_id}: input_shape must be single_file or archive"
            )
        verify_results_only = value.get("verify_results_only_equivalence", False)
        if not isinstance(verify_results_only, bool):
            raise CatalogError(
                f"{case_id}: verify_results_only_equivalence must be boolean"
            )
        cases.append(
            {
                **value,
                "status": status,
                "input_path": input_path,
                "input_shape": input_shape,
                "verify_results_only_equivalence": verify_results_only,
                "required": [
                    _validate_expectation(item, f"{case_id}.required[{index}]")
                    for index, item in enumerate(required)
                ],
                "forbidden": [
                    _validate_expectation(item, f"{case_id}.forbidden[{index}]")
                    for index, item in enumerate(forbidden)
                ],
            }
        )
    return cases


def _result_moves(results: Mapping[str, Any]) -> list[dict[str, Any]]:
    moves = results.get("moves")
    if not isinstance(moves, list):
        raise ValueError("results.moves must be an array")
    parsed = []
    for ordinal, move in enumerate(moves, start=1):
        if not isinstance(move, dict):
            raise ValueError(f"results move {ordinal} must be an object")
        from_texts = move.get("from_raw_texts")
        to_texts = move.get("to_raw_texts")
        kind = move.get("match_kind")
        if (
            not isinstance(from_texts, list)
            or not all(isinstance(text, str) for text in from_texts)
            or not isinstance(to_texts, list)
            or not all(isinstance(text, str) for text in to_texts)
            or kind not in ALLOWED_MATCH_KINDS
        ):
            raise ValueError(f"results move {ordinal} has an invalid shape")
        parsed.append(move)
    return parsed


def expectation_matches(expectation: Mapping[str, Any], move: Mapping[str, Any]) -> bool:
    allowed = expectation.get("match_kinds")
    if allowed is not None and move.get("match_kind") not in allowed:
        return False
    wanted_from = normalize_text(str(expectation["from"]))
    wanted_to = normalize_text(str(expectation["to"]))
    actual_from = {normalize_text(text) for text in move["from_raw_texts"]}
    actual_to = {normalize_text(text) for text in move["to_raw_texts"]}
    return wanted_from in actual_from and wanted_to in actual_to


def evaluate_results(case: Mapping[str, Any], results: Mapping[str, Any]) -> dict[str, Any]:
    moves = _result_moves(results)
    required = list(case.get("required", []))
    forbidden = list(case.get("forbidden", []))
    required_hits = [any(expectation_matches(item, move) for move in moves) for item in required]
    forbidden_hits = [any(expectation_matches(item, move) for move in moves) for item in forbidden]
    missing = [index for index, hit in enumerate(required_hits) if not hit]
    violations = [index for index, hit in enumerate(forbidden_hits) if hit]
    status = "pass" if not missing and not violations else "semantic_miss"
    return {
        "status": status,
        "required_total": len(required),
        "required_found": sum(required_hits),
        "forbidden_total": len(forbidden),
        "forbidden_found": sum(forbidden_hits),
        "missing_required_indexes": missing,
        "forbidden_violation_indexes": violations,
        "move_count": results.get("move_count"),
        "candidate_count": results.get("candidates_total"),
        "group_count": results.get("groups_total"),
    }


def transition_label(baseline: str, candidate: str) -> str:
    return f"{baseline}_to_{candidate}"


def summarize(outcomes: Sequence[Mapping[str, Any]], baseline: str) -> dict[str, Any]:
    by_variant: dict[str, Counter[str]] = {}
    indexed: dict[tuple[str, str], str] = {}
    for outcome in outcomes:
        variant = str(outcome["variant"])
        status = str(outcome["semantic_status"])
        by_variant.setdefault(variant, Counter())[status] += 1
        indexed[(variant, str(outcome["case_id"]))] = status

    transitions: dict[str, dict[str, int]] = {}
    case_ids = sorted({str(outcome["case_id"]) for outcome in outcomes})
    for variant in sorted(by_variant):
        if variant == baseline:
            continue
        counts: Counter[str] = Counter()
        for case_id in case_ids:
            baseline_status = indexed.get((baseline, case_id), "not_run")
            candidate_status = indexed.get((variant, case_id), "not_run")
            counts[transition_label(baseline_status, candidate_status)] += 1
        transitions[variant] = dict(sorted(counts.items()))
    return {
        "schema_version": RUN_SCHEMA_VERSION,
        "baseline": baseline,
        "variants": {
            variant: {"cases": sum(counts.values()), **dict(sorted(counts.items()))}
            for variant, counts in sorted(by_variant.items())
        },
        "transitions_from_baseline": transitions,
    }


def _load_result_file(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("results root must be an object")
    if value.get("results_schema_version") != 1:
        raise ValueError("results.results_schema_version must be 1")
    _result_moves(value)
    return value


def _validate_results_file(path: Path) -> dict[str, Any]:
    """Adapt results JSON validation to the benchmark attempt contract."""

    try:
        _load_result_file(path)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        return {"status": "invalid_structure", "error": str(error)}
    return {"status": "valid", "size_bytes": path.stat().st_size}


def _matching_decisions(results: Mapping[str, Any]) -> list[tuple[Any, ...]]:
    """Return an order-independent projection of selected move endpoints."""

    decisions = []
    for move in _result_moves(results):
        decisions.append(
            (
                move["match_kind"],
                tuple(
                    sorted(normalize_text(text) for text in move["from_raw_texts"])
                ),
                tuple(sorted(normalize_text(text) for text in move["to_raw_texts"])),
                tuple(sorted(str(path) for path in move.get("from_xpaths", []))),
                tuple(sorted(str(path) for path in move.get("to_xpaths", []))),
            )
        )
    return sorted(decisions)


def _profile_text(attempt_dir: Path) -> str:
    parts = []
    for filename in ("stdout.bin", "stderr.bin"):
        path = attempt_dir / filename
        if path.is_file():
            parts.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parts)


def run_benchmark(
    *,
    catalog_path: Path,
    variants: Mapping[str, Path],
    output_root: Path,
    baseline: str,
    timeout_seconds: float,
    run_id: str,
    case_statuses: set[str] | None = None,
) -> tuple[Path, dict[str, Any]]:
    cases = load_catalog(catalog_path)
    if case_statuses is not None:
        cases = [case for case in cases if case["status"] in case_statuses]
        if not cases:
            raise ValueError("catalog selection contains no cases")
    validate_name(run_id, "run id")
    if baseline not in variants:
        raise ValueError(f"baseline variant is not defined: {baseline}")
    run_dir = output_root.resolve() / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "attempts").mkdir()
    manifest = {
        "schema_version": RUN_SCHEMA_VERSION,
        "run_id": run_id,
        "started_at": utc_now(),
        "status": "running",
        "baseline": baseline,
        "catalog": observe_file(catalog_path),
        "variants": {name: observe_file(path) for name, path in variants.items()},
        "cases": {
            case["id"]: {
                "category": case.get("category"),
                "status": case["status"],
                "rationale": case.get("rationale"),
                "input": observe_file(case["input_path"]),
            }
            for case in cases
        },
        "interpretation": {
            "semantic_miss_is_process_failure": False,
            "purpose": "characterization_and_variant_comparison",
        },
    }
    write_json_atomic(run_dir / "manifest.json", manifest)

    outcomes: list[dict[str, Any]] = []
    hard_failures = 0
    for case in cases:
        for variant, executable in variants.items():
            def command(output: Path, executable: Path = executable, case: Mapping[str, Any] = case) -> list[str]:
                return [
                    str(executable),
                    str(case["input_path"]),
                    str(output),
                    "--results",
                    str(output.parent / "results.json"),
                    "--profile",
                ]

            attempt_dir, attempt = execute_attempt(
                attempts_root=run_dir / "attempts",
                stage="move-selection-characterization",
                case_id=str(case["id"]),
                command_factory=command,
                cwd=run_dir,
                timeout_seconds=timeout_seconds,
                output_validator=lambda output, shape=case["input_shape"]: (
                    validate_srcdiff_xml(output, shape)
                ),
                output_filename="srcmove.xml",
                context={"variant": variant, "category": case.get("category")},
            )
            outcome: dict[str, Any] = {
                "case_id": case["id"],
                "category": case.get("category"),
                "case_status": case["status"],
                "variant": variant,
                "attempt_id": attempt["attempt_id"],
                "admitted": attempt["admitted"],
                "profile": parse_profile_output(_profile_text(attempt_dir)),
            }
            try:
                if not attempt["admitted"]:
                    raise ValueError("srcMove execution was not admitted")
                results = _load_result_file(attempt_dir / "results.json")
                evaluation = evaluate_results(case, results)
                if case["verify_results_only_equivalence"]:
                    def results_only_command(
                        output: Path,
                        executable: Path = executable,
                        case: Mapping[str, Any] = case,
                    ) -> list[str]:
                        return [
                            str(executable),
                            str(case["input_path"]),
                            "--results",
                            str(output),
                            "--results-only",
                            "--profile",
                        ]

                    results_only_dir, results_only_attempt = execute_attempt(
                        attempts_root=run_dir / "attempts",
                        stage="move-selection-results-only-equivalence",
                        case_id=str(case["id"]),
                        command_factory=results_only_command,
                        cwd=run_dir,
                        timeout_seconds=timeout_seconds,
                        output_validator=_validate_results_file,
                        output_filename="results.json",
                        output_validation_key="results",
                        context={
                            "variant": variant,
                            "category": case.get("category"),
                        },
                    )
                    if not results_only_attempt["admitted"]:
                        raise ValueError("srcMove --results-only execution was not admitted")
                    results_only = _load_result_file(results_only_dir / "results.json")
                    equivalent = _matching_decisions(results) == _matching_decisions(
                        results_only
                    )
                    evaluation["results_only_equivalent"] = equivalent
                    evaluation["results_only_attempt_id"] = results_only_attempt[
                        "attempt_id"
                    ]
                    if not equivalent:
                        evaluation["status"] = "semantic_miss"
                outcome.update(evaluation)
                outcome["semantic_status"] = evaluation["status"]
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
                hard_failures += 1
                outcome.update(
                    {
                        "status": "invalid_run",
                        "semantic_status": "invalid_run",
                        "error": f"{type(error).__name__}: {error}",
                    }
                )
            outcomes.append(outcome)

    summary = summarize(outcomes, baseline)
    summary["hard_failures"] = hard_failures
    summary["contract_semantic_misses"] = sum(
        outcome["case_status"] == "contract"
        and outcome["semantic_status"] == "semantic_miss"
        for outcome in outcomes
    )
    summary["semantic_misses_are_observations"] = True
    write_json_atomic(run_dir / "outcomes.json", {"outcomes": outcomes})
    write_json_atomic(run_dir / "summary.json", summary)
    manifest.update(
        {
            "completed_at": utc_now(),
            "status": "completed" if hard_failures == 0 else "completed_with_failures",
            "hard_failures": hard_failures,
            "artifacts": {
                "outcomes": observe_file(run_dir / "outcomes.json"),
                "summary": observe_file(run_dir / "summary.json"),
            },
        }
    )
    write_json_atomic(run_dir / "manifest.json", manifest)
    return run_dir, summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare move-selection semantics across srcMove builds."
    )
    parser.add_argument(
        "--variant",
        action="append",
        default=[],
        metavar="NAME=PATH",
        help="Named srcMove executable; repeat to compare builds.",
    )
    parser.add_argument("--baseline", help="Variant used for transition counts.")
    parser.add_argument(
        "--catalog",
        type=Path,
        default=Path(__file__).with_name("catalog.json"),
    )
    parser.add_argument("--output-root", type=Path, default=REPO_ROOT / "benchmark-results" / "move-selection")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument(
        "--contracts-only",
        action="store_true",
        help="Run only accepted contract cases.",
    )
    parser.add_argument(
        "--enforce-contracts",
        action="store_true",
        help="Exit nonzero when an accepted contract has a semantic miss.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        parsed = [parse_named_path(value, "variant") for value in args.variant]
        if not parsed:
            discovered = find_srcmove(REPO_ROOT)
            if discovered is None:
                raise ValueError("srcMove executable not found; pass --variant NAME=PATH")
            parsed = [("current", discovered)]
        variants = dict(parsed)
        if len(variants) != len(parsed):
            raise ValueError("variant names must be unique")
        for name, executable in variants.items():
            if not executable.is_file():
                raise ValueError(f"variant executable not found: {name}={executable}")
        baseline = args.baseline or parsed[0][0]
        run_id = args.run_id or utc_now().replace(":", "-").replace("+", "_")
        run_dir, summary = run_benchmark(
            catalog_path=args.catalog.resolve(),
            variants=variants,
            output_root=args.output_root,
            baseline=baseline,
            timeout_seconds=args.timeout,
            run_id=run_id,
            case_statuses={"contract"} if args.contracts_only else None,
        )
    except (CatalogError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(f"move-selection results: {run_dir}")
    for variant, counts in summary["variants"].items():
        print(
            f"{variant}: pass={counts.get('pass', 0)} "
            f"semantic_miss={counts.get('semantic_miss', 0)} "
            f"invalid_run={counts.get('invalid_run', 0)}"
        )
    return 1 if (
        summary["hard_failures"]
        or (args.enforce_contracts and summary["contract_semantic_misses"])
    ) else 0


if __name__ == "__main__":
    raise SystemExit(main())
