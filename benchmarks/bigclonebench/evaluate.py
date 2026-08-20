"""Strict BigCloneBench scoring over a shared srcDiff corpus run."""

from __future__ import annotations

import csv
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

from benchmarks.bigclonebench.run import classify_result, validate_case
from benchmarks.process import write_json_atomic
from benchmarks.provenance import sha256_file, utc_now


SCORING_ORACLE_VERSION = 1
OUTCOMES = (
    "upstream_failure",
    "srcdiff_semantic_ineligible",
    "srcmove_tool_failure",
    "srcmove_miss",
    "wrong_classification",
    "oracle_failure",
    "oracle_pass",
)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _score_completed_case(
    *,
    metadata: dict[str, Any],
    results_path: Path,
    srcmove_xml: Path,
) -> tuple[str, list[str], dict[str, str], dict[str, Any]]:
    results = _read_json(results_path)
    syntactic_type = int(metadata["syntactic_type"])
    failures, text_validation = validate_case(
        Path("."), results_path, srcmove_xml, syntactic_type, metadata=metadata
    )
    if not failures:
        return "oracle_pass", [], text_validation, results
    if results.get("move_count") == 0:
        return "srcmove_miss", failures, text_validation, results

    classification_failures = [
        failure
        for failure in failures
        if failure.startswith("match_kind:") or failure.startswith("match_kinds.")
    ]
    if classification_failures and len(classification_failures) == len(failures):
        return "wrong_classification", failures, text_validation, results
    return "oracle_failure", failures, text_validation, results


def _write_csv_atomic(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "case_id",
        "outcome",
        "diagnostic_class",
        "semantic_reason",
        "clone_type",
        "syntactic_type",
        "functionality_id",
        "function_id_one",
        "function_id_two",
        "file1",
        "file2",
        "min_tokens",
        "raw_text_identical",
        "expected_match_kind",
        "observed_match_kind",
        "move_count",
        "from_text_validation",
        "to_text_validation",
        "input_sha256",
        "attempt_id",
        "failures",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames)
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


def write_evaluation(
    *,
    run_dir: Path,
    run_manifest: Mapping[str, Any],
    corpus_dir: Path,
    corpus_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Score all selected cases and write append-only artifacts under the run id."""

    if run_manifest.get("corpus_id") != corpus_manifest.get("corpus_id"):
        raise ValueError("run and corpus manifests do not match")
    persisted_run = _read_json(run_dir / "run.json")
    if persisted_run != dict(run_manifest):
        raise ValueError("run manifest does not match the persisted run artifact")
    corpus_manifest_path = corpus_dir / "manifest.json"
    persisted_corpus = _read_json(corpus_manifest_path)
    if persisted_corpus != dict(corpus_manifest):
        raise ValueError("corpus manifest does not match the persisted corpus artifact")
    corpus_manifest_checksum = sha256_file(corpus_manifest_path)
    if run_manifest.get("corpus_manifest_sha256") != corpus_manifest_checksum:
        raise ValueError("corpus manifest checksum does not match the run observation")
    if run_manifest.get("status") != "completed":
        raise ValueError("BigCloneBench evaluation requires a completed run")
    summary_path = run_dir / "summary.json"
    cases_path = run_dir / "cases.csv"
    if summary_path.exists() or cases_path.exists():
        raise FileExistsError(
            f"evaluation artifacts already exist for {run_manifest['run_id']}"
        )

    runs = {case["case_id"]: case for case in run_manifest["cases"]}
    rows: list[dict[str, Any]] = []
    counts = {outcome: 0 for outcome in OUTCOMES}
    strict_passes = 0
    tolerant_passes = 0

    for case in corpus_manifest["cases"]:
        case_id = case["case_id"]
        metadata = case.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        syntactic_type = metadata.get("syntactic_type", "")
        expected_kind = (
            "exact"
            if syntactic_type == 1
            else "type2"
            if syntactic_type == 2
            else ""
        )
        failures: list[str] = []
        text_validation = {"from": "not_checked", "to": "not_checked"}
        results: dict[str, Any] = {}
        run_case = runs.get(case_id)

        if case["generation_status"] != "accepted":
            outcome = "upstream_failure"
            diagnostic_class = "srcdiff_tool_failure"
        elif case.get("semantic_status") != "eligible":
            outcome = "srcdiff_semantic_ineligible"
            diagnostic_class = "srcdiff_semantic_ineligible"
        elif run_case is None or run_case.get("status") != "completed":
            outcome = "srcmove_tool_failure"
            diagnostic_class = "srcmove_tool_failure"
        else:
            attempt_dir = run_dir / "attempts" / run_case["attempt_id"]
            outcome, failures, text_validation, results = _score_completed_case(
                metadata=metadata,
                results_path=attempt_dir / "results.json",
                srcmove_xml=attempt_dir / "srcmove.xml",
            )
            diagnostic_class = classify_result(
                metadata,
                results,
                outcome == "oracle_pass",
                failures,
                text_validation,
            )
        counts[outcome] += 1
        if outcome == "oracle_pass":
            if "encoding_tolerant" in text_validation.values():
                tolerant_passes += 1
            else:
                strict_passes += 1
        moves = results.get("moves", [])
        observed_kind = ""
        if isinstance(moves, list) and len(moves) == 1 and isinstance(moves[0], dict):
            observed_kind = moves[0].get("match_kind", "")
        rows.append(
            {
                "case_id": case_id,
                "outcome": outcome,
                "diagnostic_class": diagnostic_class,
                "semantic_reason": case.get("semantic_details", {}).get(
                    "reason", ""
                ),
                "clone_type": f"type{syntactic_type}" if syntactic_type != "" else "",
                "syntactic_type": syntactic_type,
                "functionality_id": metadata.get("functionality_id", ""),
                "function_id_one": metadata.get("function_id_one", ""),
                "function_id_two": metadata.get("function_id_two", ""),
                "file1": (
                    metadata.get("fragment_one", {}).get("file", "")
                    if isinstance(metadata.get("fragment_one"), dict)
                    else ""
                ),
                "file2": (
                    metadata.get("fragment_two", {}).get("file", "")
                    if isinstance(metadata.get("fragment_two"), dict)
                    else ""
                ),
                "min_tokens": metadata.get("min_tokens", ""),
                "raw_text_identical": (
                    metadata.get("fragment_relation", {}).get("raw_text_identical", "")
                    if isinstance(metadata.get("fragment_relation"), dict)
                    else ""
                ),
                "expected_match_kind": expected_kind,
                "observed_match_kind": observed_kind,
                "move_count": results.get("move_count", ""),
                "from_text_validation": text_validation["from"],
                "to_text_validation": text_validation["to"],
                "input_sha256": case.get("xml", {}).get("sha256", ""),
                "attempt_id": run_case.get("attempt_id", "") if run_case else "",
                "failures": " | ".join(failures),
            }
        )

    selected = len(corpus_manifest["cases"])
    eligible = counts["srcmove_tool_failure"] + counts["srcmove_miss"] + counts[
        "wrong_classification"
    ] + counts["oracle_failure"] + counts["oracle_pass"]
    executed = len(run_manifest["cases"])
    if sum(counts.values()) != selected or executed != eligible:
        raise ValueError("BigCloneBench aggregate counts do not reconcile")

    _write_csv_atomic(cases_path, rows)
    clone_type_strata: dict[str, dict[str, int | float | None]] = {}
    raw_text_strata: dict[str, dict[str, int | float | None]] = {}
    token_size_strata: dict[str, dict[str, int | float | None]] = {}

    def add_stratum(
        groups: dict[str, dict[str, int | float | None]],
        key: str,
        passed: bool,
    ) -> None:
        group = groups.setdefault(key, {"selected": 0, "oracle_pass": 0, "rate": None})
        group["selected"] = int(group["selected"] or 0) + 1
        group["oracle_pass"] = int(group["oracle_pass"] or 0) + int(passed)

    for row in rows:
        clone_type = str(row["clone_type"] or "unknown")
        passed = row["outcome"] == "oracle_pass"
        add_stratum(clone_type_strata, clone_type, passed)
        raw_relation = (
            "identical"
            if row["raw_text_identical"] is True
            else "different"
            if row["raw_text_identical"] is False
            else "unknown"
        )
        add_stratum(raw_text_strata, raw_relation, passed)
        try:
            tokens = int(row["min_tokens"])
        except (TypeError, ValueError):
            bucket = "unknown"
        else:
            bucket = (
                "under_50"
                if tokens < 50
                else "50_99"
                if tokens < 100
                else "100_199"
                if tokens < 200
                else "200_plus"
            )
        add_stratum(token_size_strata, bucket, passed)
    for groups in (clone_type_strata, raw_text_strata, token_size_strata):
        for group in groups.values():
            group["rate"] = int(group["oracle_pass"] or 0) / int(
                group["selected"] or 1
            )

    source = corpus_manifest.get("source", {})
    generated_manifest = (
        source.get("selection", {}) if isinstance(source, Mapping) else {}
    )
    summary = {
        "schema_version": 1,
        "created_at": utc_now(),
        "run_id": run_manifest["run_id"],
        "corpus_id": corpus_manifest["corpus_id"],
        "corpus_manifest_sha256": corpus_manifest_checksum,
        "scoring_oracle": {
            "name": "bigclonebench-strict",
            "version": SCORING_ORACLE_VERSION,
        },
        "declared_slice": {
            key: generated_manifest.get(key)
            for key in (
                "clone_type",
                "dedupe",
                "text_change",
                "min_tokens",
                "row_count_before_deduplication",
                "distinct_raw_text_pair_count",
                "functionality_group_count",
                "selection",
            )
        },
        "counts": {
            "selected": selected,
            "eligible": eligible,
            "executed": executed,
            **counts,
            "strict_passes": strict_passes,
            "encoding_tolerant_passes": tolerant_passes,
        },
        "rates": {
            "end_to_end_detection_and_classification": (
                counts["oracle_pass"] / selected if selected else None
            ),
            "conditional_srcmove_detection_and_classification": (
                counts["oracle_pass"] / eligible if eligible else None
            ),
            "end_to_end_strict_text_detection_and_classification": (
                strict_passes / selected if selected else None
            ),
            "conditional_srcmove_strict_text_detection_and_classification": (
                strict_passes / eligible if eligible else None
            ),
        },
        "strata": {
            "clone_type": clone_type_strata,
            "raw_text_relationship": raw_text_strata,
            "min_tokens": token_size_strata,
        },
        "cases_csv": {"path": cases_path.name, "sha256": sha256_file(cases_path)},
    }
    write_json_atomic(summary_path, summary)
    return summary
