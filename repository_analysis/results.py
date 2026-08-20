"""Shared admission rules for srcMove results retained by repository analysis."""

from __future__ import annotations

from typing import Any


def normalize_compactable_results(
    value: dict[str, Any],
) -> tuple[list[Any], dict[str, dict[str, int]]]:
    """Validate and normalize every result field needed by compact storage."""

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
    for ordinal, move in enumerate(moves):
        _validate_move(move, ordinal)
    nested: dict[str, dict[str, int]] = {}
    for name in ("group_kinds", "match_kinds"):
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
    return moves, nested


def _validate_move(value: Any, ordinal: int) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"srcMove move {ordinal} must be an object")
    match_kind = value.get("match_kind")
    if not isinstance(match_kind, str) or not match_kind:
        raise ValueError(f"srcMove move {ordinal} has no match kind")
    for name in ("from_xpaths", "to_xpaths", "from_raw_texts", "to_raw_texts"):
        field = value.get(name)
        if not isinstance(field, list) or not all(
            isinstance(item, str) for item in field
        ):
            raise ValueError(
                f"srcMove move {ordinal} field {name!r} must be a string array"
            )
