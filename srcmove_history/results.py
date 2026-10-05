"""Shared admission rules for srcMove results retained by repository analysis."""

from __future__ import annotations

from typing import Any
from collections import Counter


def normalize_compactable_results(
    value: dict[str, Any],
) -> tuple[list[Any], dict[str, dict[str, int]]]:
    """Validate and normalize every result field needed by compact storage."""

    if value.get("results_schema_version") != 2:
        raise ValueError("srcMove results field 'results_schema_version' must be 2")

    if "match_kinds" in value:
        raise ValueError("superseded match_kinds field; regenerate results with schema 2")

    required_counts = (
        "move_count",
        "move_group_count",
        "move_pair_count",
        "annotated_region_count",
    )
    for name in required_counts:
        count = value.get(name)
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError(f"srcMove results field {name!r} must be non-negative")
    move_count = value["move_count"]
    moves = value.get("moves")
    if moves is None and move_count == 0:
        moves = []
    if not isinstance(moves, list) or len(moves) != move_count:
        raise ValueError("srcMove results moves do not match move_count")
    if value["move_group_count"] != len(moves):
        raise ValueError("srcMove move_group_count does not match moves")
    for ordinal, move in enumerate(moves):
        _validate_move(move, ordinal)
    nested: dict[str, dict[str, int]] = {}
    for name in ("group_kinds", "content_relationships"):
        counts = value.get(name)
        if counts is None and move_count == 0:
            counts = {}
        if not isinstance(counts, dict):
            raise ValueError(f"srcMove results field {name!r} must be an object")
        normalized: dict[str, int] = {}
        for key, count in counts.items():
            if (
                not isinstance(key, str)
                or not key
                or isinstance(count, bool)
                or not isinstance(count, int)
                or count < 0
            ):
                raise ValueError(f"srcMove results field {name!r} is malformed")
            normalized[key] = count
        nested[name] = dict(sorted(normalized.items()))
    observed = Counter(move["content_relationship"] for move in moves)
    counts = nested["content_relationships"]
    if set(counts) - {"type1", "type2c", "type3"}:
        raise ValueError("invalid content_relationships category; regenerate results")
    if any(counts.get(kind, 0) != observed[kind] for kind in {"type1", "type2c", "type3"}):
        raise ValueError("content_relationships counts disagree with moves")
    return moves, nested


def _validate_move(value: Any, ordinal: int) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"srcMove move {ordinal} must be an object")
    if "match_kind" in value:
        raise ValueError("superseded match_kind field; regenerate results with schema 2")
    content_relationship = value.get("content_relationship")
    if content_relationship not in {"type1", "type2c", "type3"}:
        raise ValueError(f"srcMove move {ordinal} has an invalid content relationship")
    for name in ("from_xpaths", "to_xpaths", "from_raw_texts", "to_raw_texts"):
        field = value.get(name)
        if not isinstance(field, list) or not all(
            isinstance(item, str) for item in field
        ):
            raise ValueError(
                f"srcMove move {ordinal} field {name!r} must be a string array"
            )
