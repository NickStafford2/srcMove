"""Test-only projections for frozen, independently reviewed behavioral oracles.

Live documents must pass the schema-3 validator first. Legacy field names here
are oracle vocabulary, never an accepted wire format. Reports resolve atomic
members; they do not claim duplicated evidence in the serialized output.
"""
from __future__ import annotations

from copy import deepcopy
from benchmarking.results import validate_results_schema


def oracle_view(payload):
    errors = validate_results_schema(payload, require_xpaths=True)
    if errors:
        raise ValueError("invalid schema-3 results: " + "; ".join(errors))
    result = deepcopy(payload)
    groups = payload["atomic_move_groups"]
    moves = []
    for group in groups:
        selection = group["selection"]
        move = {"move_id": group["id"], "content_relationship": group["content_relationship"],
                "confidence_milli": selection["matching_weight_milli"],
                "selection_utility": selection["utility"], "matched_units": selection["matched_units"],
                "selection_reason": selection["reason"], "name_evidence": group["name_evidence"],
                "correspondence": group["correspondence"]}
        for side, revision in (("from", "original"), ("to", "modified")):
            for field in ("xpath", "raw_text"):
                move[side + "_" + field + "s"] = [endpoint[field] for endpoint in group[revision]]
        moves.append(move)
    summary, stats = payload["summary"], payload["pipeline_statistics"]
    result.update(moves=moves, move_count=len(groups),
                  move_pair_count=summary["pair_capacity"], move_group_count=len(groups),
                  annotated_regions=summary["endpoint_count"], annotated_region_count=summary["endpoint_count"],
                  regions_total=stats["srcdiff_region_count"], candidates_total=stats["grouped_candidate_entry_count"],
                  groups_total=stats["processing_group_count"], group_kinds=stats["processing_group_kinds"],
                  content_relationships=summary["atomic_content_relationships"])
    by_id = {move["move_id"]: move for move in moves}
    reports, sequences = [], []
    for item in payload["output_items"]:
        members = [by_id[mid] for mid in item["member_group_ids"]]
        sequence = item["kind"] == "sequence_move_group"
        report = {"move_id": item["id"] if sequence else members[0]["move_id"],
                  "report_kind": "ordered_sequence" if sequence else "atomic",
                  "member_move_ids": item["member_group_ids"],
                  "content_relationship": "type1" if sequence else members[0]["content_relationship"]}
        for field in ("from_xpaths", "to_xpaths", "from_raw_texts", "to_raw_texts"):
            report[field] = [value for member in members for value in member[field]]
        if not sequence:
            report["name_evidence"] = members[0]["name_evidence"]
        reports.append(report)
        if sequence:
            seq = {"move_id": item["id"], "member_move_ids": item["member_group_ids"],
                   "content_relationship": "type1", "policy": item["sequence"]["policy"]}
            for side, revision in (("from", "original"), ("to", "modified")):
                seq[side] = dict(item["sequence"][revision], member_xpaths=report[side + "_xpaths"])
            sequences.append(seq)
    result.update(reported_moves=reports, reported_move_count=len(reports), move_sequences=sequences,
                  sequence_cluster_count=len(sequences), sequence_reporting_unit_count=len(reports),
                  reported_content_relationships=summary["output_content_relationships"])
    if "diagnostics" in payload:
        diagnostic = deepcopy(payload["diagnostics"])
        endpoints = {endpoint["candidate_id"]: endpoint for group in groups
                     for side in ("original", "modified") for endpoint in group[side]}
        for candidate in diagnostic["candidates"]:
            candidate.update(endpoints[candidate["candidate_id"]] if candidate["selected_group_id"] is not None
                             else candidate["endpoint"])
            candidate["side"] = "delete" if candidate["revision"] == "original" else "insert"
        for pair in diagnostic["correspondences"]:
            location = pair["location"]
            pair.update(delete_candidate_id=pair["original_candidate_id"], insert_candidate_id=pair["modified_candidate_id"],
                        correspondence_kind=pair["content_relationship"], shadow_change=location["classification"],
                        classification_reason=location["reason"], carried_by_parent=location["carried_by_parent"],
                        current_result="move" if pair["selection"]["status"] == "selected_pair" else "not_move",
                        before_context=pair["original_context"], after_context=pair["modified_context"])
            parent = location["parent_pair"]
            for old, new in (("delete", "original"), ("insert", "modified")):
                pair["parent_" + old + "_candidate_id"] = parent[new + "_candidate_id"] if parent else None
                pair[old + "_verified_partner_count"] = (pair["verified_partner_counts"][new]
                                                          if pair["verified_partner_counts"] else None)
            pair.update({key + "_observation": value for key, value in location["observations"].items()})
            counts = pair["verified_partner_counts"]
            pair["cardinality"] = "competing_edges" if counts and max(counts.values()) > 1 else "one_to_one"
        comparisons = []
        for pair in diagnostic["type3_comparisons"]:
            verification, selection = pair["verification"], pair["selection"]
            outcome = {"selected": "selected", "not_selected": "selection_rejected"}.get(selection["status"],
                       verification["reason"] or verification["status"])
            comparisons.append(dict(pair, delete_candidate_id=pair["original_candidate_id"],
                                    insert_candidate_id=pair["modified_candidate_id"], outcome=outcome))
        diagnostic["type3_pairs"] = comparisons
        for group in diagnostic["type2b_groups"]:
            group.update(correspondence_kind=group["content_relationship"],
                         delete_candidate_ids=group["original_candidate_ids"], insert_candidate_ids=group["modified_candidate_ids"],
                         cardinality="one_to_one" if len(group["original_candidate_ids"]) == len(group["modified_candidate_ids"]) == 1 else "ambiguous")
            if group["location"] is not None:
                group.update(location_change=group["location"]["classification"], location_reason=group["location"]["reason"])
        result["diagnostics"] = diagnostic
    return result
