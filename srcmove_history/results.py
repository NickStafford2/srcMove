"""Schema-3 admission and projections for compact repository observations.

The SQLite query API retains its historical column names. They always describe
atomic groups; output items are retained separately with explicit member IDs.
"""
from __future__ import annotations
from typing import Any
from srcmove_runtime.results_schema import atomic_moves, validate_results


def scalar_metrics(value: dict[str, Any]) -> dict[str, Any]:
    summary = value["summary"]
    pipeline = value["pipeline_statistics"]
    return {
        "results_schema_version": 3,
        "move_count": summary["atomic_move_group_count"],
        "move_group_count": summary["atomic_move_group_count"],
        "move_pair_count": summary["pair_capacity"],
        "annotated_region_count": summary["endpoint_count"],
        "regions_total": pipeline["srcdiff_region_count"],
        "candidates_total": pipeline["grouped_candidate_entry_count"],
        "groups_total": pipeline["processing_group_count"],
        "output_item_count": summary["output_item_count"],
        "sequence_move_group_count": summary["sequence_move_group_count"],
    }


def normalize_compactable_results(value: dict[str, Any]) -> tuple[list[Any], dict[str, Any]]:
    validate_results(value)
    return atomic_moves(value), {
        "group_kinds": value["pipeline_statistics"]["processing_group_kinds"],
        "content_relationships": value["summary"]["atomic_content_relationships"],
        "summary": value["summary"],
        "configuration": value["configuration"],
        "pipeline_statistics": value["pipeline_statistics"],
        "xpath_context": value["xpath_context"],
        "output_items": value["output_items"],
    }
