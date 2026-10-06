"""Structural checks for srcMove schema-2 results, independent of scoring oracles."""
from __future__ import annotations

from typing import Any


def validate_results_schema(
    results: Any, *, require_xpaths: bool = False
) -> list[str]:
    failures: list[str] = []
    if not isinstance(results, dict):
        return ["results.json root must be an object"]

    if results.get("results_schema_version") != 2:
        failures.append("results_schema_version: expected 2")

    if "match_kinds" in results:
        failures.append("superseded match_kinds field; regenerate results with schema 2")
    moves = results.get("moves")
    move_count = results.get("move_count")
    if not isinstance(moves, list):
        failures.append("moves: expected a list")
        return failures
    if not isinstance(move_count, int) or isinstance(move_count, bool) or move_count < 0:
        failures.append("move_count: expected a nonnegative integer")
    elif move_count != len(moves):
        failures.append("move_count does not match the moves list")

    if "move_group_count" in results:
        group_count = results["move_group_count"]
        if type(group_count) is not int or group_count != len(moves):
            failures.append("move_group_count does not match the moves list")

    observed_counts = {"type1": 0, "type2c": 0, "type3": 0}
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
        if "match_kind" in move:
            failures.append(f"{prefix}: superseded match_kind field; regenerate results")
        content_relationship = move.get("content_relationship")
        if content_relationship not in observed_counts:
            failures.append(f"{prefix}.content_relationship: invalid value {content_relationship!r}")
        else:
            observed_counts[content_relationship] += 1
        for field in ("from_raw_texts", "to_raw_texts"):
            values = move.get(field)
            if not isinstance(values, list) or not all(
                isinstance(value, str) for value in values
            ):
                failures.append(f"{prefix}.{field}: expected a list of strings")
        if require_xpaths:
            for field in ("from_xpaths", "to_xpaths"):
                values = move.get(field)
                if not isinstance(values, list) or not all(
                    isinstance(value, str) and value.startswith("/")
                    for value in values
                ):
                    failures.append(
                        f"{prefix}.{field}: expected a list of absolute XPaths"
                    )

    content_relationships = results.get("content_relationships")
    if not isinstance(content_relationships, dict):
        failures.append("content_relationships: expected an object")
    else:
        if set(content_relationships) - set(observed_counts):
            failures.append("content_relationships: unsupported categories; regenerate results")
        for kind, observed in observed_counts.items():
            count = content_relationships.get(kind, 0)
            if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                failures.append(f"content_relationships.{kind}: expected a nonnegative integer")
            elif count != observed:
                failures.append(
                    f"content_relationships.{kind}: expected {observed} from the moves list, got {count}"
                )
    return failures

