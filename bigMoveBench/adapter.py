"""BigMoveBench case metadata and srcDiff semantic eligibility helpers."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from bigMoveBench.contracts import InputPair, SemanticResult, SemanticStatus
from bigMoveBench.selection import type3_stratum


SEMANTIC_ORACLE_VERSION = 1
SRCDIFF_NAMESPACES = {
    "http://www.srcML.org/srcDiff",
    "http://www.srcML.org/srcDiff/diff",
}


def _fragment_relation(fragment_one: str, fragment_two: str) -> dict[str, bool]:
    return {
        "raw_text_identical": fragment_one == fragment_two,
        "trimmed_text_identical": fragment_one.strip() == fragment_two.strip(),
    }


def _type3_frame_strength(rows: Sequence[Mapping[str, Any]]) -> tuple[float, str]:
    similarities: list[float] = []
    for row in rows:
        similarity = row.get("similarity")
        if not isinstance(similarity, Mapping):
            raise ValueError("Type-3 selection row is missing similarity")
        line = similarity.get("line")
        token = similarity.get("token")
        if not isinstance(line, (int, float)) or not isinstance(token, (int, float)):
            raise ValueError("Type-3 selection row has invalid similarity")
        similarities.append(min(float(line), float(token)))
    strength = min(similarities)
    return strength, type3_stratum(strength)


def _local_name(value: str) -> str:
    return value.rsplit("}", 1)[-1].rsplit(":", 1)[-1]


def _attribute(node: ET.Element, name: str) -> str | None:
    for key, value in node.attrib.items():
        if _local_name(key) == name:
            return value
    return None


def _line(value: str, side: str) -> int | None:
    selected = value.split("|")[0 if side == "delete" else -1]
    try:
        return int(selected.split(":", 1)[0])
    except ValueError:
        return None


def _candidate_ranges(root: ET.Element, side: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for region in root.iter():
        namespace = (
            region.tag[1:].split("}", 1)[0]
            if region.tag.startswith("{")
            else ""
        )
        if _local_name(region.tag) != side or namespace not in SRCDIFF_NAMESPACES:
            continue
        lines: list[int] = []
        for node in region.iter():
            for attribute_name in ("start", "end"):
                position = _attribute(node, attribute_name)
                if position is not None:
                    parsed = _line(position, side)
                    if parsed is not None:
                        lines.append(parsed)
        if lines:
            ranges.append((min(lines), max(lines)))
    return ranges


def _covers(candidate: tuple[int, int], expected: tuple[int, int]) -> bool:
    return candidate[0] <= expected[0] and candidate[1] >= expected[1]


def validate_srcdiff_semantics(
    case: InputPair, srcdiff_xml: Path
) -> SemanticResult:
    """Require delete and insert candidates covering both generated payloads."""

    expected = case.metadata.get("expected")
    if not isinstance(expected, Mapping):
        return SemanticResult(
            SemanticStatus.INELIGIBLE,
            {
                "reason": "missing_expected_ranges",
                "oracle_version": SEMANTIC_ORACLE_VERSION,
            },
        )
    try:
        deleted = (int(expected["from_start_line"]), int(expected["from_end_line"]))
        inserted = (int(expected["to_start_line"]), int(expected["to_end_line"]))
    except (KeyError, TypeError, ValueError):
        return SemanticResult(
            SemanticStatus.INELIGIBLE,
            {
                "reason": "invalid_expected_ranges",
                "oracle_version": SEMANTIC_ORACLE_VERSION,
            },
        )

    try:
        root = ET.parse(srcdiff_xml).getroot()
    except (OSError, ET.ParseError) as error:
        return SemanticResult(
            SemanticStatus.INELIGIBLE,
            {
                "reason": "xml_unavailable_after_structural_admission",
                "error": str(error),
                "oracle_version": SEMANTIC_ORACLE_VERSION,
            },
        )

    delete_ranges = _candidate_ranges(root, "delete")
    insert_ranges = _candidate_ranges(root, "insert")
    delete_exposed = any(_covers(candidate, deleted) for candidate in delete_ranges)
    insert_exposed = any(_covers(candidate, inserted) for candidate in insert_ranges)
    status = (
        SemanticStatus.ELIGIBLE
        if delete_exposed and insert_exposed
        else SemanticStatus.INELIGIBLE
    )
    return SemanticResult(
        status,
        {
            "oracle_version": SEMANTIC_ORACLE_VERSION,
            "reason": (
                "payload_exposed"
                if status is SemanticStatus.ELIGIBLE
                else "payload_not_exposed"
            ),
            "expected_delete_range": list(deleted),
            "expected_insert_range": list(inserted),
            "delete_candidate_ranges": [list(value) for value in delete_ranges],
            "insert_candidate_ranges": [list(value) for value in insert_ranges],
            "delete_exposed": delete_exposed,
            "insert_exposed": insert_exposed,
        },
    )
