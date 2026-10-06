"""Shared admission rules for srcMove results retained by repository analysis."""

from __future__ import annotations

from typing import Any
from collections import Counter


def normalize_compactable_results(
    value: dict[str, Any],
) -> tuple[list[Any], dict[str, Any]]:
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
    nested: dict[str, Any] = {}
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
    _validate_reporting(value, moves)
    _validate_sequences(value, moves)
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


def _validate_reporting(value: dict[str, Any], moves: list[Any]) -> None:
    """Compound reports partition atomic groups; endpoints stay ordered."""
    fields = {"reported_moves", "reported_move_count", "reported_content_relationships"}
    if not fields.intersection(value):
        return
    if not fields.issubset(value):
        raise ValueError("incomplete reported move fields")
    reports = value["reported_moves"]
    count = value["reported_move_count"]
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise ValueError("reported_move_count must be non-negative")
    if not isinstance(reports, list) or len(reports) != count:
        raise ValueError("reported_moves disagree with reported_move_count")
    atomic = _indexed_atomic_moves(moves)
    seen: set[str] = set()
    report_ids: set[str] = set()
    for ordinal, report in enumerate(reports):
        _validate_move(report, ordinal)
        members = report.get("member_move_ids")
        report_id = report.get("move_id")
        kind = report.get("report_kind")
        if not isinstance(report_id, str) or not report_id or report_id in report_ids:
            raise ValueError("reported move IDs must be unique")
        report_ids.add(report_id)
        if not isinstance(members, list) or not members or any(
            not isinstance(member, str) or member not in atomic or member in seen
            for member in members
        ) or len(set(members)) != len(members):
            raise ValueError("reported move members must partition atomic moves")
        if kind == "atomic":
            if members != [report_id]:
                raise ValueError("atomic report must retain its atomic move ID")
        elif kind == "ordered_sequence":
            if len(members) < 2 or report["content_relationship"] != "type1":
                raise ValueError("ordered sequence report requires multiple Type-1 members")
            if any(len(atomic[member][side]) != 1 for member in members for side in ("from_xpaths", "to_xpaths")):
                raise ValueError("ordered sequence members require one-to-one endpoints")
        else:
            raise ValueError("invalid report_kind")
        if any(atomic[member]["content_relationship"] != report["content_relationship"] for member in members):
            raise ValueError("reported content relationship disagrees with members")
        for name in ("from_xpaths", "to_xpaths", "from_raw_texts", "to_raw_texts"):
            expected = [item for member in members for item in atomic[member][name]]
            if report[name] != expected:
                raise ValueError("reported move endpoints disagree with ordered members")
        seen.update(members)
    if seen != set(atomic):
        raise ValueError("reported moves must cover every atomic move")
    counts = value["reported_content_relationships"]
    if not isinstance(counts, dict) or set(counts) - {"type1", "type2c", "type3"}:
        raise ValueError("invalid reported_content_relationships")
    observed = Counter(report["content_relationship"] for report in reports)
    if any(isinstance(count, bool) or not isinstance(count, int) or count < 0 for count in counts.values()) or any(
        counts.get(kind, 0) != observed[kind] for kind in ("type1", "type2c", "type3")
    ):
        raise ValueError("reported_content_relationships disagree with reports")


def _validate_sequences(value: dict[str, Any], moves: list[Any]) -> None:
    fields = {"move_sequences", "sequence_cluster_count", "sequence_reporting_unit_count"}
    if not fields.intersection(value):
        return
    if not fields.issubset(value):
        raise ValueError("incomplete move sequence fields")
    sequences = value["move_sequences"]
    if not isinstance(sequences, list):
        raise ValueError("move_sequences must be an array")
    for field in ("sequence_cluster_count", "sequence_reporting_unit_count"):
        count = value[field]
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError(f"{field} must be non-negative")
    if value["sequence_cluster_count"] != len(sequences):
        raise ValueError("sequence_cluster_count disagrees with sequences")
    atomic = _indexed_atomic_moves(moves)
    seen: set[str] = set()
    ids: set[str] = set()
    for sequence in sequences:
        if not isinstance(sequence, dict):
            raise ValueError("move sequence must be an object")
        sequence_id = sequence.get("sequence_id")
        members = sequence.get("member_move_ids")
        if not isinstance(sequence_id, str) or not sequence_id or sequence_id in ids:
            raise ValueError("sequence IDs must be unique")
        ids.add(sequence_id)
        if sequence.get("content_relationship") != "type1" or sequence.get("policy") != "ordered_adjacent_v1":
            raise ValueError("invalid move sequence policy or relationship")
        if not isinstance(members, list) or len(members) < 2 or any(
            not isinstance(member, str) or member not in atomic or member in seen for member in members
        ) or len(set(members)) != len(members):
            raise ValueError("sequence members must be disjoint atomic moves")
        if any(atomic[member]["content_relationship"] != "type1" for member in members):
            raise ValueError("sequence members must be Type-1 moves")
        for side in ("from", "to"):
            endpoint = sequence.get(side)
            if not isinstance(endpoint, dict):
                raise ValueError("sequence endpoint must be an object")
            for name in ("revision_file", "parent_id"):
                if not isinstance(endpoint.get(name), str) or not endpoint[name]:
                    raise ValueError("sequence endpoint requires a file and parent")
            for name in ("first_child_ordinal", "last_child_ordinal"):
                ordinal = endpoint.get(name)
                if isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal < 0:
                    raise ValueError("invalid sequence child ordinal")
            if endpoint["last_child_ordinal"] - endpoint["first_child_ordinal"] + 1 != len(members):
                raise ValueError("sequence ordinals disagree with members")
            if any(len(atomic[member][side + "_xpaths"]) != 1 for member in members) or endpoint.get("member_xpaths") != [atomic[member][side + "_xpaths"][0] for member in members]:
                raise ValueError("sequence endpoints disagree with ordered members")
        seen.update(members)
    reporting_count = len(moves) - len(seen) + len(sequences)
    if value["sequence_reporting_unit_count"] != reporting_count:
        raise ValueError("sequence_reporting_unit_count disagrees with sequences")
    if "reported_moves" in value:
        projected = {report["move_id"]: report["member_move_ids"] for report in value["reported_moves"] if report["report_kind"] == "ordered_sequence"}
        if projected != {sequence["sequence_id"]: sequence["member_move_ids"] for sequence in sequences} or value["reported_move_count"] != reporting_count:
            raise ValueError("move sequences disagree with reported moves")


def _indexed_atomic_moves(moves: list[Any]) -> dict[str, Any]:
    ids = [move.get("move_id") for move in moves]
    if any(not isinstance(move_id, str) or not move_id for move_id in ids) or len(set(ids)) != len(ids):
        raise ValueError("compound reporting requires unique atomic move IDs")
    return dict(zip(ids, moves))
