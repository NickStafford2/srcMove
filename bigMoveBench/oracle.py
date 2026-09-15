"""Scoring and diagnostic rules for BigMoveBench cases."""

from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

TextValidation = dict[str, str]
MV_NAMESPACE = "http://www.srcML.org/srcMove"


@dataclass(frozen=True)
class PositiveOracleAssessment:
    detected: bool
    correctly_classified: bool
    operational_failures: list[str]
    detection_failures: list[str]
    classification_failures: list[str]
    text_validation: TextValidation
    detected_move_id: str | None = None
    observed_match_kind: str | None = None


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def trimmed_text(value: str) -> str:
    # Local audit key only. BigCloneBench Type-1 permits whitespace/comment
    # variation, so raw text remains the default dedupe and test-generation key.
    lines = value.strip().splitlines()
    return "\n".join(line.rstrip() for line in lines)


def stable_key(*parts: str) -> str:
    hasher = hashlib.sha256()
    for part in parts:
        encoded = part.encode("utf-8", errors="replace")
        hasher.update(len(encoded).to_bytes(8, byteorder="big"))
        hasher.update(encoded)
    return hasher.hexdigest()


def dedupe_keys(metadata: dict[str, Any]) -> dict[str, str]:
    dedupe = metadata.get("dedupe")
    if isinstance(dedupe, dict):
        raw_pair_key = dedupe.get("raw_text_pair_key")
        trimmed_pair_key = dedupe.get("trimmed_text_pair_key")
        if isinstance(raw_pair_key, str) and isinstance(trimmed_pair_key, str):
            return {
                "raw_text_pair_key": raw_pair_key,
                "trimmed_text_pair_key": trimmed_pair_key,
            }

    fragment_one = metadata.get("fragment_one")
    if not isinstance(fragment_one, dict):
        fragment_one = {}
    fragment_two = metadata.get("fragment_two")
    if not isinstance(fragment_two, dict):
        fragment_two = {}

    fragment1 = fragment_one.get("text")
    fragment2 = fragment_two.get("text")
    if not isinstance(fragment1, str) or not isinstance(fragment2, str):
        return {"raw_text_pair_key": "", "trimmed_text_pair_key": ""}

    return {
        "raw_text_pair_key": stable_key(fragment1, fragment2),
        "trimmed_text_pair_key": stable_key(
            trimmed_text(fragment1), trimmed_text(fragment2)
        ),
    }


def attr_by_local_name(node: ET.Element, local_name: str) -> str | None:
    for key, value in node.attrib.items():
        if key == local_name or key.endswith("}" + local_name) or key.endswith(":" + local_name):
            return value
    return None


def parse_pos_line(value: str, kind: str) -> int | None:
    side = value.split("|")[0 if kind == "delete" else -1]
    line_text = side.split(":", 1)[0]
    try:
        return int(line_text)
    except ValueError:
        return None


def moved_position_ranges(
    srcmove_xml: Path,
) -> dict[str, dict[str, list[tuple[int, int]]]]:
    tree = ET.parse(srcmove_xml)
    ranges: dict[str, dict[str, list[tuple[int, int]]]] = {}

    for node in tree.iter():
        move_id = node.attrib.get(f"{{{MV_NAMESPACE}}}id")
        if move_id is None:
            continue

        to_link = node.attrib.get(f"{{{MV_NAMESPACE}}}to")
        from_link = node.attrib.get(f"{{{MV_NAMESPACE}}}from")
        if to_link is not None and from_link is not None:
            raise ValueError(f"move annotation {move_id!r} has both mv:to and mv:from")
        if to_link:
            kind = "delete"
        elif from_link:
            kind = "insert"
        elif to_link is not None or from_link is not None:
            raise ValueError(f"move annotation {move_id!r} has an empty link attribute")
        else:
            continue

        pos_start = attr_by_local_name(node, "start")
        pos_end = attr_by_local_name(node, "end")
        if pos_start is None or pos_end is None:
            raise ValueError(f"move annotation {move_id!r} is missing a position range")

        start_line = parse_pos_line(pos_start, kind)
        end_line = parse_pos_line(pos_end, kind)
        if start_line is None or end_line is None:
            raise ValueError(f"move annotation {move_id!r} has an invalid position range")

        move_ranges = ranges.setdefault(move_id, {"delete": [], "insert": []})
        move_ranges[kind].append(
            (min(start_line, end_line), max(start_line, end_line))
        )

    return ranges


def ranges_overlap(left: tuple[int, int], right: tuple[int, int]) -> bool:
    return left[0] <= right[1] and right[0] <= left[1]


def normalize_moved_text(value: str) -> str:
    """Normalize wrapper indentation without hiding line content changes."""
    lines = value.strip().splitlines()
    return "\n".join(line.strip() for line in lines)


def has_encoding_damage(value: str) -> bool:
    return "\ufffd" in value or "ï¿½" in value


def normalize_encoding_damage(value: str) -> str:
    try:
        value = value.encode("latin-1").decode("utf-8")
    except UnicodeError:
        pass
    return value.replace("ï¿½", "\ufffd")


def text_matches_with_status(observed: str, expected: str) -> str | None:
    normalized_observed = normalize_moved_text(observed)
    normalized_expected = normalize_moved_text(expected)
    if normalized_observed == normalized_expected:
        return "strict"

    if has_encoding_damage(normalized_observed) or has_encoding_damage(
        normalized_expected
    ):
        tolerant_observed = normalize_encoding_damage(normalized_observed)
        tolerant_expected = normalize_encoding_damage(normalized_expected)
        if tolerant_observed == tolerant_expected:
            return "encoding_tolerant"

    return None


def expected_generated_text(expected: dict[str, Any], side: str) -> str | None:
    generated_key = f"{side}_generated_text"
    generated_text = expected.get(generated_key)
    if isinstance(generated_text, str):
        return generated_text

    # Backward-compatible fallback for metadata generated before the exact
    # wrapped fragment text was recorded.
    raw_key = f"{side}_raw_text"
    raw_text = expected.get(raw_key)
    return raw_text if isinstance(raw_text, str) else None


def validate_reported_text(
    failures: list[str],
    text_validation: TextValidation,
    observed: str,
    expected: dict[str, Any],
    side: str,
) -> None:
    expected_text = expected_generated_text(expected, side)
    if expected_text is None:
        failures.append(f"metadata expected.{side}_generated_text is missing or invalid")
        text_validation[side] = "failed"
        return

    status = text_matches_with_status(observed, expected_text)
    if status is None:
        failures.append(
            f"{side}_raw_texts[0] does not match the expected generated fragment text"
        )
        text_validation[side] = "failed"
        return

    text_validation[side] = status


def _validate_results_schema(results: Any) -> list[str]:
    failures: list[str] = []
    if not isinstance(results, dict):
        return ["results.json root must be an object"]

    moves = results.get("moves")
    move_count = results.get("move_count")
    if not isinstance(moves, list):
        failures.append("moves: expected a list")
        return failures
    if not isinstance(move_count, int) or isinstance(move_count, bool) or move_count < 0:
        failures.append("move_count: expected a nonnegative integer")
    elif move_count != len(moves):
        failures.append("move_count does not match the moves list")

    observed_counts = {"exact": 0, "type2": 0, "type3": 0}
    move_ids: set[str] = set()
    for index, move in enumerate(moves):
        prefix = f"moves[{index}]"
        if not isinstance(move, dict):
            failures.append(f"{prefix}: expected an object")
            continue
        move_id = move.get("move_id")
        if not isinstance(move_id, str) or not move_id:
            failures.append(f"{prefix}.move_id: expected a nonempty string")
        elif move_id in move_ids:
            failures.append(f"{prefix}.move_id: duplicate move id {move_id!r}")
        else:
            move_ids.add(move_id)
        match_kind = move.get("match_kind")
        if match_kind not in observed_counts:
            failures.append(f"{prefix}.match_kind: invalid value {match_kind!r}")
        else:
            observed_counts[match_kind] += 1
        for field in ("from_raw_texts", "to_raw_texts"):
            values = move.get(field)
            if not isinstance(values, list) or not all(
                isinstance(value, str) for value in values
            ):
                failures.append(f"{prefix}.{field}: expected a list of strings")

    match_kinds = results.get("match_kinds")
    if not isinstance(match_kinds, dict):
        failures.append("match_kinds: expected an object")
    else:
        for kind, observed in observed_counts.items():
            count = match_kinds.get(kind, 0)
            if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                failures.append(f"match_kinds.{kind}: expected a nonnegative integer")
            elif count != observed:
                failures.append(
                    f"match_kinds.{kind}: expected {observed} from the moves list, got {count}"
                )
    return failures


def assess_positive_case(
    *,
    metadata: dict[str, Any],
    results: Any,
    srcmove_xml: Path,
    syntactic_type: int,
) -> PositiveOracleAssessment:
    operational_failures = _validate_results_schema(results)
    detection_failures: list[str] = []
    classification_failures: list[str] = []
    text_validation: TextValidation = {"from": "not_checked", "to": "not_checked"}
    expected_match_kinds = {1: "exact", 2: "type2", 3: "type3"}
    if syntactic_type not in expected_match_kinds:
        raise ValueError(f"unsupported BigCloneBench syntactic type: {syntactic_type}")
    expected_match_kind = expected_match_kinds[syntactic_type]

    if metadata.get("syntactic_type") != syntactic_type:
        operational_failures.append(
            f"metadata syntactic_type: expected {syntactic_type}, "
            f"got {metadata.get('syntactic_type')!r}"
        )
    expected = metadata.get("expected")
    if not isinstance(expected, dict):
        operational_failures.append("metadata expected field is missing or invalid")
        expected = {}
    expected_from = expected_generated_text(expected, "from")
    expected_to = expected_generated_text(expected, "to")
    if expected_from is None:
        operational_failures.append(
            "metadata expected.from_generated_text is missing or invalid"
        )
    if expected_to is None:
        operational_failures.append(
            "metadata expected.to_generated_text is missing or invalid"
        )
    try:
        expected_from_range = (
            int(expected["from_start_line"]),
            int(expected["from_end_line"]),
        )
        expected_to_range = (
            int(expected["to_start_line"]),
            int(expected["to_end_line"]),
        )
    except (KeyError, TypeError, ValueError):
        operational_failures.append(
            "metadata expected synthetic line ranges are missing or invalid"
        )
        expected_from_range = expected_to_range = (0, -1)

    ranges_by_move: dict[str, dict[str, list[tuple[int, int]]]] = {}
    # The corpus runner intentionally discards a validated XML artifact when
    # srcMove reports zero moves. A present artifact must still be well formed.
    if results.get("move_count") != 0 or srcmove_xml.exists():
        try:
            ranges_by_move = moved_position_ranges(srcmove_xml)
        except (OSError, ET.ParseError, ValueError) as error:
            operational_failures.append(f"srcmove.xml parse error: {error}")

    if operational_failures:
        return PositiveOracleAssessment(
            False,
            False,
            operational_failures,
            detection_failures,
            classification_failures,
            text_validation,
        )

    detected: list[tuple[dict[str, Any], str, str]] = []
    text_link_found = False
    from_position_found = False
    to_position_found = False
    for move in results["moves"]:
        from_status = next(
            (
                status
                for value in move["from_raw_texts"]
                if (status := text_matches_with_status(value, expected_from)) is not None
            ),
            None,
        )
        to_status = next(
            (
                status
                for value in move["to_raw_texts"]
                if (status := text_matches_with_status(value, expected_to)) is not None
            ),
            None,
        )
        if from_status is None or to_status is None:
            continue
        text_link_found = True
        move_ranges = ranges_by_move.get(move["move_id"], {})
        from_overlaps = any(
            ranges_overlap(found, expected_from_range)
            for found in move_ranges.get("delete", [])
        )
        to_overlaps = any(
            ranges_overlap(found, expected_to_range)
            for found in move_ranges.get("insert", [])
        )
        from_position_found |= from_overlaps
        to_position_found |= to_overlaps
        if from_overlaps and to_overlaps:
            detected.append((move, from_status, to_status))

    if not detected:
        if not text_link_found:
            detection_failures.append(
                "no single reported move links both complete expected generated fragment texts"
            )
            text_validation = {"from": "failed", "to": "failed"}
        else:
            if not from_position_found:
                detection_failures.append(
                    "the text-linked move's delete annotation does not overlap the expected source range"
                )
            if not to_position_found:
                detection_failures.append(
                    "the text-linked move's insert annotation does not overlap the expected target range"
                )
        return PositiveOracleAssessment(
            False,
            False,
            [],
            detection_failures,
            [],
            text_validation,
        )

    correctly_classified = next(
        (candidate for candidate in detected if candidate[0]["match_kind"] == expected_match_kind),
        None,
    )
    selected = correctly_classified or detected[0]
    move, from_status, to_status = selected
    text_validation = {"from": from_status, "to": to_status}
    if correctly_classified is None:
        classification_failures.append(
            f"match_kind: expected {expected_match_kind!r}, got {move['match_kind']!r}"
        )
    return PositiveOracleAssessment(
        True,
        correctly_classified is not None,
        [],
        [],
        classification_failures,
        text_validation,
        move["move_id"],
        move["match_kind"],
    )


def validate_case(
    case_dir: Path,
    results_json: Path,
    srcmove_xml: Path,
    syntactic_type: int,
    metadata: dict[str, Any] | None = None,
) -> tuple[list[str], TextValidation]:
    if metadata is None:
        metadata = load_json(case_dir / "metadata.json")
    results = load_json(results_json)
    assessment = assess_positive_case(
        metadata=metadata,
        results=results,
        srcmove_xml=srcmove_xml,
        syntactic_type=syntactic_type,
    )
    failures = (
        assessment.operational_failures
        + assessment.detection_failures
        + assessment.classification_failures
    )
    return failures, assessment.text_validation


def move_points_to_anchor(move: dict[str, Any]) -> bool:
    values: list[str] = []
    for field in ("from_xpaths", "to_xpaths", "from_raw_texts", "to_raw_texts"):
        field_value = move.get(field)
        if isinstance(field_value, list):
            values.extend(value for value in field_value if isinstance(value, str))

    haystack = "\n".join(values)
    return any(
        anchor in haystack
        for anchor in ("beforeAnchor", "middleAnchor", "targetAnchor", "afterAnchor")
    )


def move_points_inside_expected_payload(move: dict[str, Any]) -> bool:
    values: list[str] = []
    for field in ("from_xpaths", "to_xpaths"):
        field_value = move.get(field)
        if isinstance(field_value, list):
            values.extend(value for value in field_value if isinstance(value, str))

    haystack = "\n".join(values)
    return (
        "diff:delete[1]/diff:delete[1]" in haystack
        or "diff:insert[1]/diff:insert[1]" in haystack
    )


def classify_result(
    metadata: dict[str, Any],
    results: dict[str, Any] | None,
    passed: bool,
    failures: list[str],
    text_validation: TextValidation,
) -> str:
    if passed:
        if "encoding_tolerant" in text_validation.values():
            return "pass_encoding_tolerant"
        return "pass_strict"

    if results is None:
        return "tool_failure"

    moves = results.get("moves")
    move_count = results.get("move_count")
    fragment_relation = metadata.get("fragment_relation")
    raw_identical = (
        isinstance(fragment_relation, dict)
        and fragment_relation.get("raw_text_identical") is True
    )

    if not isinstance(moves, list):
        return "invalid_results"

    if move_count == 0:
        return "no_move_raw_identical" if raw_identical else "no_move_raw_different"

    if any(status == "failed" for status in text_validation.values()):
        return "text_mismatch"

    operational_prefixes = (
        "results.json",
        "moves:",
        "moves[",
        "move_count:",
        "match_kinds",
        "metadata ",
        "srcmove.xml parse error:",
    )
    if any(failure.startswith(operational_prefixes) for failure in failures):
        return "oracle_failure"

    if all(isinstance(move, dict) and move_points_to_anchor(move) for move in moves):
        return "anchor_only_false_positive"

    if all(
        isinstance(move, dict) and move_points_inside_expected_payload(move)
        for move in moves
    ):
        return "too_many_expected_child_moves"

    if any(isinstance(move, dict) and move_points_to_anchor(move) for move in moves):
        return "mixed_anchor_and_payload_moves"

    if failures:
        return "validation_failure"

    return "unknown_failure"
