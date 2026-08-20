"""Reproducible paired srcMove performance measurements."""

from __future__ import annotations

import csv
import json
import os
import random
import re
import resource
import statistics
import tempfile
import uuid
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

from benchmarks.contracts import RunMode
from benchmarks.corpus import load_corpus
from benchmarks.process import execute_attempt, validate_srcdiff_xml, write_json_atomic
from benchmarks.provenance import (
    collect_run_observation,
    observe_file,
    sha256_file,
    utc_now,
)


PERFORMANCE_RUN_SCHEMA_VERSION = 1
PERFORMANCE_SUMMARY_SCHEMA_VERSION = 1
PROFILE_LINE_RE = re.compile(
    r"^profile\.([A-Za-z0-9_.]+)_ms=([0-9]+(?:\.[0-9]+)?)$"
)
SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def validate_name(value: str, kind: str) -> str:
    if not SAFE_NAME_RE.fullmatch(value):
        raise ValueError(
            f"{kind} must start with an alphanumeric character and contain only "
            f"letters, digits, '.', '_', or '-': {value!r}"
        )
    return value


def parse_named_path(value: str, kind: str) -> tuple[str, Path]:
    if "=" not in value:
        raise ValueError(f"{kind} must use NAME=PATH: {value!r}")
    name, raw_path = value.split("=", 1)
    validate_name(name, f"{kind} name")
    if not raw_path:
        raise ValueError(f"{kind} path must not be empty: {value!r}")
    return name, Path(raw_path).expanduser().resolve()


def _require_unique(items: Sequence[tuple[str, Path]], kind: str) -> None:
    duplicates = [
        name
        for name, count in Counter(name for name, _ in items).items()
        if count > 1
    ]
    if duplicates:
        raise ValueError(f"duplicate {kind} name(s): {', '.join(sorted(duplicates))}")


def load_inputs(
    *,
    data_root: Path,
    corpus: str | Path | None,
    named_inputs: Sequence[str],
    selected_case_ids: Sequence[str] = (),
) -> tuple[dict[str, Path], dict[str, Any]]:
    """Load direct immutable XML inputs or accepted cases from one corpus."""

    if (corpus is None) == (not named_inputs):
        raise ValueError("select exactly one of --corpus or one or more --input values")

    if corpus is not None:
        corpus_dir, manifest = load_corpus(data_root, corpus)
        accepted = {
            case["case_id"]: corpus_dir / case["input_path"]
            for case in manifest["cases"]
            if case["generation_status"] == "accepted"
        }
        selected = set(selected_case_ids) if selected_case_ids else set(accepted)
        unknown = selected - set(accepted)
        if unknown:
            raise ValueError(
                "unknown accepted corpus case(s): " + ", ".join(sorted(unknown))
            )
        inputs = {
            case["case_id"]: accepted[case["case_id"]]
            for case in manifest["cases"]
            if case["case_id"] in selected
        }
        source = {
            "kind": "corpus",
            "corpus_id": manifest["corpus_id"],
            "corpus_manifest_sha256": sha256_file(corpus_dir / "manifest.json"),
        }
    else:
        parsed = [parse_named_path(value, "input") for value in named_inputs]
        _require_unique(parsed, "input")
        if selected_case_ids:
            raise ValueError("--case is available only with --corpus")
        inputs = dict(parsed)
        source = {"kind": "direct"}

    if not inputs:
        raise ValueError("performance run selected no inputs")
    return inputs, source


def inspect_input(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"performance input not found: {path}")
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as error:
        raise ValueError(f"performance input is malformed XML: {path}: {error}") from error
    child_units = [child for child in root if child.tag.rsplit("}", 1)[-1] == "unit"]
    shape = "archive" if child_units else "single_file"
    validation = validate_srcdiff_xml(path, shape)
    if validation["status"] != "valid":
        raise ValueError(
            f"performance input is not structurally admitted srcDiff XML: "
            f"{path}: {validation.get('error', validation['status'])}"
        )
    elements = list(root.iter())
    return {
        "path": str(path.resolve()),
        "sha256": validation["sha256"],
        "size_bytes": validation["size_bytes"],
        "shape": shape,
        "element_count": len(elements),
        "delete_region_count": sum(
            element.tag.rsplit("}", 1)[-1] == "delete" for element in elements
        ),
        "insert_region_count": sum(
            element.tag.rsplit("}", 1)[-1] == "insert" for element in elements
        ),
    }


def build_schedule(
    *,
    case_ids: Sequence[str],
    variant_names: Sequence[str],
    warmups: int,
    repetitions: int,
    seed: int,
) -> list[dict[str, Any]]:
    """Build a deterministic paired/interleaved and position-balanced schedule."""

    if not case_ids or not variant_names:
        raise ValueError("schedule requires at least one case and variant")
    if warmups < 0 or repetitions < 1:
        raise ValueError("warmups must be nonnegative and repetitions must be positive")
    if len(variant_names) > 1 and repetitions < len(variant_names):
        raise ValueError(
            "measured repetitions must be at least the variant count so run order "
            "can be position-balanced"
        )

    randomizer = random.Random(seed)
    base_orders: dict[str, list[str]] = {}
    for case_id in sorted(case_ids):
        order = sorted(variant_names)
        randomizer.shuffle(order)
        base_orders[case_id] = order

    schedule: list[dict[str, Any]] = []
    sequence = 0
    for phase, count in (("warmup", warmups), ("measured", repetitions)):
        for repetition in range(1, count + 1):
            ordered_cases = sorted(case_ids)
            randomizer.shuffle(ordered_cases)
            for case_id in ordered_cases:
                base = base_orders[case_id]
                offset = (repetition - 1) % len(base)
                ordered_variants = base[offset:] + base[:offset]
                for position, variant in enumerate(ordered_variants, start=1):
                    sequence += 1
                    schedule.append(
                        {
                            "sequence": sequence,
                            "phase": phase,
                            "repetition": repetition,
                            "case_id": case_id,
                            "variant": variant,
                            "position_in_pair": position,
                        }
                    )
    return schedule


def parse_profile_output(text: str) -> dict[str, float]:
    metrics: dict[str, float] = {}
    for line in text.splitlines():
        match = PROFILE_LINE_RE.match(line.strip())
        if match is not None:
            metrics[match.group(1)] = float(match.group(2))
    return metrics


def _read_attempt_output(attempt_dir: Path) -> str:
    blocks = []
    for name in ("stdout.bin", "stderr.bin"):
        path = attempt_dir / name
        if path.is_file():
            blocks.append(path.read_bytes().decode("utf-8", errors="replace"))
    return "\n".join(blocks)


def _observe_results(path: Path) -> dict[str, Any]:
    observation = observe_file(path)
    if observation["status"] != "observed":
        return {"status": "missing"}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        return {**observation, "status": "malformed", "error": str(error)}
    if not isinstance(value, dict):
        return {**observation, "status": "malformed", "error": "root must be an object"}
    return {**observation, "status": "valid"}


def _child_cpu_usage() -> tuple[float, float]:
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return usage.ru_utime, usage.ru_stime


def run_measurement(
    *,
    run_dir: Path,
    schedule_entry: Mapping[str, Any],
    executable: Path,
    executable_sha256: str,
    input_path: Path,
    input_observation: Mapping[str, Any],
    timeout_seconds: float,
) -> tuple[dict[str, Any], set[str]]:
    if sha256_file(executable) != executable_sha256:
        raise ValueError(
            f"srcMove variant changed after run observation: "
            f"{schedule_entry['variant']}"
        )
    if sha256_file(input_path) != input_observation["sha256"]:
        raise ValueError(
            f"performance input changed after run observation: "
            f"{schedule_entry['case_id']}"
        )
    before_user, before_system = _child_cpu_usage()

    def command(output: Path) -> Sequence[str]:
        return [
            str(executable),
            str(input_path),
            str(output),
            "--results",
            str(output.parent / "results.json"),
            "--profile",
        ]

    attempt_dir, attempt = execute_attempt(
        attempts_root=run_dir / "attempts",
        stage="srcmove-performance",
        case_id=str(schedule_entry["case_id"]),
        command_factory=command,
        cwd=run_dir,
        timeout_seconds=timeout_seconds,
        xml_validator=lambda path: validate_srcdiff_xml(
            path, str(input_observation["shape"])
        ),
        output_filename="srcmove.xml",
        context={
            "performance_run_id": run_dir.name,
            **dict(schedule_entry),
            "input_sha256": input_observation["sha256"],
        },
    )
    after_user, after_system = _child_cpu_usage()
    metrics = parse_profile_output(_read_attempt_output(attempt_dir))
    results = _observe_results(attempt_dir / "results.json")
    failures = []
    if not attempt["admitted"]:
        failures.append("process_or_output_failure")
    if results["status"] != "valid":
        failures.append(f"results_{results['status']}")
    if not metrics:
        failures.append("profile_metrics_missing")
    status = "success" if not failures else "failed"
    if status == "success":
        (attempt_dir / "srcmove.xml").unlink()
        attempt["output_retention"] = "discarded_after_validation"
        write_json_atomic(attempt_dir / "attempt.json", attempt)
    row: dict[str, Any] = {
        **dict(schedule_entry),
        "attempt_id": attempt["attempt_id"],
        "attempt_path": str(attempt_dir.relative_to(run_dir)),
        "status": status,
        "failure": ";".join(failures),
        "termination_status": attempt["termination"]["status"],
        "exit_code": attempt["termination"].get("exit_code"),
        "signal_name": attempt["termination"].get("signal_name"),
        "wall_seconds": attempt["process_elapsed_seconds"],
        "cpu_user_seconds": max(0.0, after_user - before_user),
        "cpu_system_seconds": max(0.0, after_system - before_system),
        "cpu_total_seconds": max(
            0.0, (after_user - before_user) + (after_system - before_system)
        ),
        "peak_rss_bytes": attempt["resource_usage"]["peak_rss_bytes"],
        "peak_rss_status": attempt["resource_usage"]["peak_rss_status"],
        "input_sha256": input_observation["sha256"],
        "input_size_bytes": input_observation["size_bytes"],
        "input_element_count": input_observation["element_count"],
        "input_delete_region_count": input_observation["delete_region_count"],
        "input_insert_region_count": input_observation["insert_region_count"],
        "output_sha256": attempt["xml"].get("sha256"),
        "output_retention": attempt["output_retention"],
        "results_sha256": results.get("sha256"),
    }
    for name, value in metrics.items():
        row[f"internal_{name}_ms"] = value
    return row, set(metrics)


RAW_BASE_FIELDS = [
    "sequence",
    "phase",
    "repetition",
    "case_id",
    "variant",
    "position_in_pair",
    "attempt_id",
    "attempt_path",
    "status",
    "failure",
    "termination_status",
    "exit_code",
    "signal_name",
    "wall_seconds",
    "cpu_user_seconds",
    "cpu_system_seconds",
    "cpu_total_seconds",
    "peak_rss_bytes",
    "peak_rss_status",
    "input_sha256",
    "input_size_bytes",
    "input_element_count",
    "input_delete_region_count",
    "input_insert_region_count",
    "output_sha256",
    "output_retention",
    "results_sha256",
]


def write_raw_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    internal_fields = sorted(
        {key for row in rows for key in row if key.startswith("internal_")}
    )
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=RAW_BASE_FIELDS + internal_fields)
            writer.writeheader()
            writer.writerows(rows)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def describe(values: Sequence[float]) -> dict[str, int | float | None]:
    if not values:
        return {"n": 0, "median": None, "mad": None, "min": None, "max": None}
    median = statistics.median(values)
    return {
        "n": len(values),
        "median": median,
        "mad": statistics.median(abs(value - median) for value in values),
        "min": min(values),
        "max": max(values),
    }


def build_summary(
    *,
    run_id: str,
    rows: Sequence[Mapping[str, Any]],
    variant_names: Sequence[str],
    internal_metric_names: Sequence[str],
) -> dict[str, Any]:
    measured = [row for row in rows if row["phase"] == "measured"]
    metric_fields = [
        "wall_seconds",
        "cpu_user_seconds",
        "cpu_system_seconds",
        "cpu_total_seconds",
        "peak_rss_bytes",
        *[f"internal_{name}_ms" for name in sorted(internal_metric_names)],
    ]

    def summarize_rows(selected: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        successful = [row for row in selected if row["status"] == "success"]
        return {
            "attempted": len(selected),
            "successful": len(successful),
            "failed": len(selected) - len(successful),
            "metrics": {
                field: describe(
                    [
                        float(row[field])
                        for row in successful
                        if row.get(field) is not None
                    ]
                )
                for field in metric_fields
            },
        }

    variants: dict[str, Any] = {}
    for variant in variant_names:
        variant_rows = [row for row in measured if row["variant"] == variant]
        variants[variant] = summarize_rows(variant_rows)
        variants[variant]["cases"] = {
            case_id: summarize_rows(
                [row for row in variant_rows if row["case_id"] == case_id]
            )
            for case_id in sorted({str(row["case_id"]) for row in variant_rows})
        }

    baseline = variant_names[0]
    comparisons: dict[str, Any] = {}
    for candidate in variant_names[1:]:
        comparison_metrics: dict[str, Any] = {}
        for field in metric_fields:
            paired: dict[tuple[str, int], dict[str, float]] = {}
            for row in measured:
                if row["status"] != "success" or row.get(field) is None:
                    continue
                if row["variant"] not in {baseline, candidate}:
                    continue
                key = (str(row["case_id"]), int(row["repetition"]))
                paired.setdefault(key, {})[str(row["variant"])] = float(row[field])
            complete = [
                values
                for values in paired.values()
                if baseline in values and candidate in values
            ]
            deltas = [values[candidate] - values[baseline] for values in complete]
            ratios = [
                values[candidate] / values[baseline]
                for values in complete
                if values[baseline] != 0
            ]
            comparison_metrics[field] = {
                "paired": len(complete),
                "candidate_minus_baseline": describe(deltas),
                "candidate_over_baseline": describe(ratios),
            }
        comparisons[candidate] = {
            "baseline": baseline,
            "candidate": candidate,
            "metrics": comparison_metrics,
        }

    failure_classes = Counter(
        str(row["failure"] or "unknown")
        for row in measured
        if row["status"] != "success"
    )
    return {
        "schema_version": PERFORMANCE_SUMMARY_SCHEMA_VERSION,
        "run_id": run_id,
        "counts": {
            "warmup_attempts": sum(row["phase"] == "warmup" for row in rows),
            "measured_attempts": len(measured),
            "measured_successful": sum(row["status"] == "success" for row in measured),
            "measured_failed": sum(row["status"] != "success" for row in measured),
        },
        "failure_classes": dict(sorted(failure_classes.items())),
        "variants": variants,
        "comparisons": comparisons,
    }


def run_performance(
    *,
    output_root: Path,
    variants: Mapping[str, Path],
    inputs: Mapping[str, Path],
    input_source: Mapping[str, Any],
    warmups: int,
    repetitions: int,
    seed: int,
    timeout_seconds: float,
    cache_policy: str,
    mode: RunMode,
    run_id: str | None = None,
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    if not variants:
        raise ValueError("performance run requires at least one srcMove variant")
    for name, executable in variants.items():
        validate_name(name, "variant name")
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise ValueError(
                f"srcMove variant is not an executable file: {name}={executable}"
            )
    run_id = run_id or f"performance-{utc_now().replace(':', '').replace('+', '-')}-{uuid.uuid4()}"
    validate_name(run_id, "run id")
    run_dir = output_root.expanduser().resolve() / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "attempts").mkdir()
    created_at = utc_now()
    input_observations = {name: inspect_input(path) for name, path in inputs.items()}
    schedule = build_schedule(
        case_ids=list(inputs),
        variant_names=list(variants),
        warmups=warmups,
        repetitions=repetitions,
        seed=seed,
    )
    observation = collect_run_observation(
        mode=mode,
        repositories={},
        executables=variants,
        inputs=inputs,
    )
    running_manifest = {
        "schema_version": PERFORMANCE_RUN_SCHEMA_VERSION,
        "run_id": run_id,
        "status": "running",
        "created_at": created_at,
        "mode": mode.value,
        "input_source": dict(input_source),
        "inputs": input_observations,
        "variant_order": list(variants),
        "policy": {
            "warmups": warmups,
            "repetitions": repetitions,
            "seed": seed,
            "ordering": "paired_interleaved_position_balanced",
            "timeout_seconds": timeout_seconds,
            "cache_policy": cache_policy,
            "cpu_measurement": "getrusage_children_delta",
            "memory_measurement": "shared_attempt_resource_monitor",
        },
        "schedule": schedule,
        "observation": observation,
        "implementation": {
            "performance_runner_sha256": sha256_file(Path(__file__)),
            "process_runner_sha256": sha256_file(
                Path(execute_attempt.__code__.co_filename)
            ),
        },
        "completed_sequences": 0,
    }
    write_json_atomic(run_dir / "run.json", running_manifest)
    rows: list[dict[str, Any]] = []
    internal_metric_names: set[str] = set()
    try:
        for entry in schedule:
            row, names = run_measurement(
                run_dir=run_dir,
                schedule_entry=entry,
                executable=variants[str(entry["variant"])],
                executable_sha256=observation["executables"][
                    str(entry["variant"])
                ]["artifact"]["sha256"],
                input_path=inputs[str(entry["case_id"])],
                input_observation=input_observations[str(entry["case_id"])],
                timeout_seconds=timeout_seconds,
            )
            rows.append(row)
            internal_metric_names.update(names)
            running_manifest["completed_sequences"] = len(rows)
            write_json_atomic(run_dir / "run.json", running_manifest)

        raw_path = run_dir / "raw.csv"
        write_raw_csv(raw_path, rows)
        summary = build_summary(
            run_id=run_id,
            rows=rows,
            variant_names=list(variants),
            internal_metric_names=sorted(internal_metric_names),
        )
        write_json_atomic(run_dir / "summary.json", summary)
        manifest = {
            **running_manifest,
            "status": "completed",
            "completed_at": utc_now(),
            "completed_sequences": len(rows),
            "artifacts": {
                "raw_csv": {
                    "path": raw_path.name,
                    "sha256": sha256_file(raw_path),
                },
                "summary": {
                    "path": "summary.json",
                    "sha256": sha256_file(run_dir / "summary.json"),
                },
            },
        }
        write_json_atomic(run_dir / "run.json", manifest)
        return run_dir, manifest, summary
    except BaseException:
        running_manifest.update(
            {
                "status": "orchestration_interrupted",
                "completed_at": utc_now(),
                "completed_sequences": len(rows),
            }
        )
        write_json_atomic(run_dir / "run.json", running_manifest)
        raise
