"""Apply the BigMoveBench scoring oracle to one completed case."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Mapping

from benchmarking.results import validate_results_schema
from benchmarking.contracts import XmlStatus
from benchmarking.provenance import observe_file
from bigMoveBench.label_corrections import LabelCorrections
from bigMoveBench.oracle import (
    assess_positive_case,
    expected_generated_text,
    text_matches_with_status,
)


SCORING_ORACLE_VERSION = 9
OPERATIONAL_FAILURES = (
    "upstream_failure",
    "srcdiff_semantic_ineligible",
    "srcmove_tool_failure",
    "oracle_failure",
)
OUTCOMES = (
    "upstream_failure",
    "srcdiff_semantic_ineligible",
    "srcmove_tool_failure",
    "srcmove_miss",
    "srcmove_false_positive",
    "wrong_classification",
    "oracle_failure",
    "oracle_pass",
)


def pair_set_passes(pair_set: str, counts: Mapping[str, int]) -> bool:
    """Apply required expectations without making Type-3 recall a gate."""
    if pair_set == "type3":
        return all(counts[name] == 0 for name in OPERATIONAL_FAILURES)
    return counts["oracle_pass"] == counts["selected"]


def diagnostic_stage(outcome: str, results: dict[str, Any]) -> str:
    """Classify the observable stage of an outcome without guessing internals."""

    if outcome == "oracle_pass":
        return "selected"
    if outcome == "wrong_classification":
        return "classification"
    if outcome == "srcmove_false_positive":
        return "false_acceptance"
    if outcome != "srcmove_miss":
        return outcome

    candidates = results.get("candidates_total")
    if type(candidates) is int and candidates < 2:
        return "candidate_generation"
    moves = results.get("moves")
    if isinstance(moves, list) and moves:
        return "selection_or_granularity"
    return "retrieval_or_verification"


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def validate_results_output(path: Path) -> dict[str, Any]:
    """Validate the results-only artifact before admitting a srcMove attempt."""

    artifact = observe_file(path)
    if artifact["status"] != "observed":
        return {"status": XmlStatus.MISSING.value}
    base = {
        "size_bytes": artifact["size_bytes"],
        "sha256": artifact["sha256"],
    }
    if artifact["size_bytes"] == 0:
        return {"status": XmlStatus.EMPTY.value, **base}
    try:
        results = _read_json(path)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        return {
            "status": XmlStatus.MALFORMED.value,
            "error": str(error),
            **base,
        }
    failures = validate_results_schema(results, require_xpaths=True)
    if failures:
        return {
            "status": XmlStatus.INVALID_STRUCTURE.value,
            "errors": failures,
            **base,
        }
    return {"status": XmlStatus.VALID.value, **base}


def _score_completed_case(
    *,
    metadata: dict[str, Any],
    results_path: Path,
    srcmove_xml: Path | None = None,
    srcdiff_xml: Path | None = None,
    label_corrections: LabelCorrections | None = None,
) -> tuple[str, list[str], dict[str, str], dict[str, Any]]:
    try:
        results = _read_json(results_path)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        return (
            "oracle_failure",
            [f"results.json parse error: {error}"],
            {"from": "not_checked", "to": "not_checked"},
            {},
        )
    if metadata.get("case_kind") == "known_false_positive":
        text_validation = {"from": "not_checked", "to": "not_checked"}
        failures = validate_results_schema(results)
        moves = results.get("moves")
        if srcmove_xml is not None and (
            results.get("move_count") != 0 or srcmove_xml.exists()
        ):
            try:
                ET.parse(srcmove_xml)
            except (OSError, ET.ParseError) as error:
                failures.append(f"srcmove.xml parse error: {error}")
        expected = metadata.get("expected")
        if not isinstance(expected, dict):
            failures.append("metadata expected field is missing or invalid")
        expected_from = (
            expected_generated_text(expected, "from")
            if isinstance(expected, dict)
            else None
        )
        expected_to = (
            expected_generated_text(expected, "to")
            if isinstance(expected, dict)
            else None
        )
        if expected_from is None or expected_to is None:
            failures.append("metadata expected generated texts are missing or invalid")

        if failures:
            return "oracle_failure", failures, text_validation, results

        whole_fragment_match = False
        if (
            isinstance(moves, list)
            and expected_from is not None
            and expected_to is not None
        ):
            for move in moves:
                from_texts = move.get("from_raw_texts")
                to_texts = move.get("to_raw_texts")
                from_status = next(
                    (
                        status
                        for value in from_texts
                        if isinstance(value, str)
                        if (status := text_matches_with_status(value, expected_from))
                        is not None
                    ),
                    None,
                )
                to_status = next(
                    (
                        status
                        for value in to_texts
                        if isinstance(value, str)
                        if (status := text_matches_with_status(value, expected_to))
                        is not None
                    ),
                    None,
                )
                if from_status is not None and to_status is not None:
                    whole_fragment_match = True
                    text_validation = {"from": from_status, "to": to_status}
                    break
        if whole_fragment_match:
            failures.append(
                "srcMove linked the complete BigCloneBench known-false-positive pair"
            )
            return "srcmove_false_positive", failures, text_validation, results
        return "oracle_pass", [], text_validation, results

    try:
        syntactic_type = int(metadata["syntactic_type"])
    except (KeyError, TypeError, ValueError) as error:
        return (
            "oracle_failure",
            [f"metadata syntactic_type is missing or invalid: {error}"],
            {"from": "not_checked", "to": "not_checked"},
            results,
        )
    try:
        assessment = assess_positive_case(
            metadata=metadata,
            results=results,
            syntactic_type=syntactic_type,
            srcmove_xml=srcmove_xml,
            srcdiff_xml=srcdiff_xml,
        )
    except ValueError as error:
        return "oracle_failure", [str(error)], {"from": "not_checked", "to": "not_checked"}, results
    try:
        correction = (label_corrections or LabelCorrections()).match(metadata)
    except ValueError as error:
        return "oracle_failure", [str(error)], assessment.text_validation, results
    if correction is not None:
        reviewed = assess_positive_case(
            metadata=metadata, results=results, syntactic_type=syntactic_type,
            srcmove_xml=srcmove_xml, srcdiff_xml=srcdiff_xml,
            expected_content_relationship_override=correction["reviewed_content_relationship"],
        )
        results["_oracle_label_correction"] = correction
        results["_oracle_reviewed_outcome"] = (
            "oracle_failure" if reviewed.operational_failures else
            "srcmove_miss" if not reviewed.detected else
            "wrong_classification" if not reviewed.correctly_classified else "oracle_pass"
        )
        results["_oracle_reviewed_failures"] = (
            reviewed.operational_failures + reviewed.detection_failures + reviewed.classification_failures
        )
    results["_oracle_expected_category"] = metadata.get("benchmark_category", f"type{syntactic_type}")
    results["_oracle_category_rules_version"] = metadata.get("category_rules_version")
    results["_oracle_complete_detection"] = assessment.detected
    if assessment.detected_move_id is not None:
        results["_oracle_detected_move_id"] = assessment.detected_move_id
        results["_oracle_observed_content_relationship"] = assessment.observed_content_relationship
    if assessment.operational_failures:
        return (
            "oracle_failure",
            assessment.operational_failures,
            assessment.text_validation,
            results,
        )
    if not assessment.detected:
        return (
            "srcmove_miss",
            assessment.detection_failures,
            assessment.text_validation,
            results,
        )
    if not assessment.correctly_classified:
        return (
            "wrong_classification",
            assessment.classification_failures,
            assessment.text_validation,
            results,
        )
    return "oracle_pass", [], assessment.text_validation, results
