"""Apply the BigMoveBench scoring oracle to one completed case."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from bigMoveBench.oracle import (
    _validate_results_schema,
    assess_positive_case,
    expected_generated_text,
    text_matches_with_status,
)


SCORING_ORACLE_VERSION = 4
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
        failures = _validate_results_schema(results)
        moves = results.get("moves")
        if results.get("move_count") != 0 or srcmove_xml.exists():
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
    assessment = assess_positive_case(
        metadata=metadata,
        results=results,
        srcmove_xml=srcmove_xml,
        syntactic_type=syntactic_type,
    )
    if assessment.detected_move_id is not None:
        results["_oracle_detected_move_id"] = assessment.detected_move_id
        results["_oracle_observed_match_kind"] = assessment.observed_match_kind
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
