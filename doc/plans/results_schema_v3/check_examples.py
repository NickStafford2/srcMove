#!/usr/bin/env python3
"""Check cross-record semantics of synthetic results-v3 examples (stdlib only).

Structural validation belongs to schema.json. XML resolution, true adjacency,
and detector correctness cannot be established from these documents alone.
"""

import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path


RELATIONSHIPS = ("type1", "type2c", "type3")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def index_by(records, field, label):
    result = {}
    for record in records:
        key = record[field]
        require(key not in result, f"Duplicate {label}: {key}")
        result[key] = record
    return result


def histogram(values):
    counts = Counter(values)
    return {relationship: counts[relationship] for relationship in RELATIONSHIPS}


def check_identity(evidence, relationship, diagnostic=False):
    status = evidence["status"]
    reasons = {
        "exact_content": None,
        "corroborated": "continuing_name_corroborated",
        "tentative": "uncorroborated_declaration",
        "unassessed": None,
        "contradicted": "continuing_name_conflict",
    }
    require(status in reasons, "Unknown identity status")
    require(diagnostic or status != "contradicted", "Selected contradicted identity")
    require((relationship == "type1") == (status == "exact_content"),
            "Type-1 and exact-content identity must agree")
    require(evidence["reason"] == reasons[status], "Identity status/reason disagree")


def check_location(location, candidate_side=None, selected=False):
    if location["scope"] != "pair":
        return
    parent = location["parent_pair"]
    require(location["carried_by_parent"] == (parent is not None),
            "Parent carrying and parent reference disagree")
    if selected:
        require(not location["carried_by_parent"], "Selected pair is parent-carried")
        require(location["classification"] == "relocated",
                "Selected pair lacks eligible location classification")
    if parent is not None and candidate_side is not None:
        for side in ("original", "modified"):
            candidate_id = parent[f"{side}_candidate_id"]
            require(candidate_side.get(candidate_id) == side,
                    "Parent reference missing or on incorrect side")
    observations = location["observations"]
    if location["carried_by_parent"]:
        require(observations["anchor_interval"] == "same_within_parent"
                and observations["relative_order"] == "unchanged",
                "Parent-carried observations disagree")


def exact_group(group, original_id, modified_id, relationship):
    return (group["correspondence"]["status"] == "selected_pair"
            and group["content_relationship"] == relationship
            and [endpoint["candidate_id"] for endpoint in group["original"]] == [original_id]
            and [endpoint["candidate_id"] for endpoint in group["modified"]] == [modified_id])


def validate(document):
    """Raise ValueError for cross-record violations; expect schema-valid input."""
    require(document["results_schema_version"] == 3, "Expected results schema 3")
    groups = index_by(document["atomic_move_groups"], "id", "atomic group ID")
    items = index_by(document["output_items"], "id", "output item ID")
    endpoints = {}
    ownership = {}
    sides = {}
    for group_id, group in groups.items():
        relationship = group["content_relationship"]
        check_identity(group["identity_evidence"], relationship)
        status = group["correspondence"]["status"]
        basis = group["correspondence"]["basis"]
        copy = group["copy_provenance"]["status"] == "continuing_source_copy"
        require(copy == (status == "copy_source_set"), "Copy and correspondence disagree")
        reason = group["selection"]["reason"]
        for special_basis in ("continuing_source_copy", "unresolved_exact_residual",
                              "exact_neighbor_correspondence"):
            require((basis == special_basis) == (reason == special_basis),
                    "Typed correspondence basis and selection reason disagree")
        if basis == "exact_neighbor_correspondence":
            require(relationship == "type1", "Exact-neighbor basis requires Type-1")
        if status == "selected_pair":
            require(basis in ("pair_proposal", "exact_neighbor_correspondence"),
                    "Selected pair has incompatible basis")
            require(len(group["original"]) == len(group["modified"]) == 1,
                    "Selected pair must have one endpoint per side")
            require(group["location_evidence"]["scope"] == "pair",
                    "Selected pair requires pair location")
            require(group["selection"]["reason"] not in
                    ("continuing_source_copy", "unresolved_exact_residual"),
                    "Unresolved or copy policy cannot establish selected pair")
        elif status == "unresolved_partners":
            require(relationship == "type1", "Unresolved group must be Type-1")
            require(basis in ("repeated_exact_group", "unresolved_exact_residual"),
                    "Unresolved group has incompatible basis")
            require(group["location_evidence"]["scope"] == "group",
                    "Unresolved group requires group location gate")
            if basis == "unresolved_exact_residual":
                require(group["selection"]["reason"] == basis,
                        "Residual basis and selection reason disagree")
            else:
                require(len(group["original"]) > 1 or len(group["modified"]) > 1,
                        "Repeated group requires alternatives")
        elif status == "copy_source_set":
            require(relationship == "type1" and basis == "continuing_source_copy",
                    "Copy group requires exact copy basis")
            require(group["selection"]["reason"] == "continuing_source_copy",
                    "Copy selection reason disagrees")
            require(group["location_evidence"]["scope"] == "not_assessed",
                    "Copy group must retain unassessed location")
        else:
            raise ValueError("Unknown correspondence status")
        check_location(group["location_evidence"], selected=status == "selected_pair")
        for side in ("original", "modified"):
            for endpoint in group[side]:
                candidate_id = endpoint["candidate_id"]
                require(candidate_id not in endpoints, "Candidate has multiple selected owners")
                endpoints[candidate_id] = endpoint
                ownership[candidate_id] = group_id
                sides[candidate_id] = side

    members_seen = set()
    output_relationships = []
    sequence_spans = {"original": [], "modified": []}
    for item_id, item in items.items():
        members = item["member_group_ids"]
        require(len(members) == len(set(members)), "Duplicate output member")
        require(all(member in groups for member in members), "Missing output member")
        require(not members_seen.intersection(members), "Output partition repeats group")
        members_seen.update(members)
        if item["kind"] == "atomic_move_group":
            require(len(members) == 1 and item_id == f"item:{members[0]}",
                    "Atomic output identity/member mismatch")
            output_relationships.append(groups[members[0]]["content_relationship"])
            continue
        require(len(members) >= 2 and item_id == f"sequence:{members[0]}",
                "Sequence output identity/member mismatch")
        sequence = item["sequence"]
        require(sequence["policy"] == document["configuration"]["sequence_policy"],
                "Sequence policy differs from configuration")
        for member in members:
            group = groups[member]
            require(group["content_relationship"] == "type1"
                    and group["correspondence"]["status"] == "selected_pair",
                    "Sequence member must be resolved Type-1 pair")
            for side in ("original", "modified"):
                endpoint = group[side][0]
                require(endpoint["role"] == "structural_child", "Sequence member role invalid")
                require(endpoint["revision_file"] == sequence[side]["revision_file"],
                        "Sequence member file differs from span")
        for side in ("original", "modified"):
            span = sequence[side]
            first, last = span["first_child_ordinal"], span["last_child_ordinal"]
            require(last - first + 1 == len(members), "Sequence span/member count mismatch")
            key = (span["revision_file"], span["parent_id"])
            for old_key, old_first, old_last in sequence_spans[side]:
                require(key != old_key or last < old_first or first > old_last,
                        "Sequence spans overlap")
            sequence_spans[side].append((key, first, last))
        output_relationships.append("type1")
    require(members_seen == set(groups), "Output partition omits group")
    summary = document["summary"]
    expected = {
        "atomic_move_group_count": len(groups),
        "output_item_count": len(items),
        "sequence_move_group_count": sum(item["kind"] == "sequence_move_group" for item in items.values()),
        "pair_capacity": sum(min(len(group["original"]), len(group["modified"])) for group in groups.values()),
        "endpoint_count": len(endpoints),
        "atomic_content_relationships": histogram(group["content_relationship"] for group in groups.values()),
        "output_content_relationships": histogram(output_relationships),
    }
    require(summary == expected, "Summary differs from canonical collections")
    statistics = document["pipeline_statistics"]
    require(all(0 <= candidate_id < statistics["registered_candidate_count"]
                for candidate_id in endpoints), "Selected candidate ID outside registry bounds")
    require(sum(statistics["processing_group_kinds"].values()) == statistics["processing_group_count"],
            "Processing group histogram total differs")
    require(statistics["active_candidate_count"] <= statistics["registered_candidate_count"],
            "Active inventory exceeds registered inventory")
    require(len(endpoints) <= statistics["active_candidate_count"],
            "Selected endpoints exceed active inventory")
    if "diagnostics" not in document:
        return
    diagnostics = document["diagnostics"]
    candidates = index_by(diagnostics["candidates"], "candidate_id", "diagnostic candidate ID")
    require(all(0 <= candidate_id < statistics["registered_candidate_count"]
                for candidate_id in candidates), "Diagnostic candidate ID outside registry bounds")
    require(len(candidates) == statistics["active_candidate_count"], "Active candidate inventory incomplete")
    require(set(endpoints) <= set(candidates), "Selected candidate absent from inventory")
    for candidate_id, candidate in candidates.items():
        side = candidate["revision"]
        if candidate_id in ownership:
            require(candidate["selected_group_id"] == ownership[candidate_id]
                    and candidate["endpoint"] is None and side == sides[candidate_id],
                    "Selected candidate ownership/side disagrees")
        else:
            require(candidate["selected_group_id"] is None and candidate["endpoint"] is not None,
                    "Unselected candidate requires inline endpoint")
            require(candidate["endpoint"]["candidate_id"] == candidate_id,
                    "Inline candidate identity disagrees")
        sides[candidate_id] = side

    def check_pair(record):
        for side in ("original", "modified"):
            require(sides.get(record[f"{side}_candidate_id"]) == side,
                    "Diagnostic reference missing or on incorrect side")

    def selected_link(record, relationship, selected_status):
        selection = record["selection"]
        group_id = selection["selected_group_id"]
        if selection["status"] == selected_status:
            require(group_id in groups and exact_group(groups[group_id],
                    record["original_candidate_id"], record["modified_candidate_id"], relationship),
                    "Diagnostic selected link does not match exact selected pair")
        else:
            require(group_id is None, "Unselected diagnostic cannot link a selected pair")
            require(not any(exact_group(group, record["original_candidate_id"],
                    record["modified_candidate_id"], relationship) for group in groups.values()),
                    "Exact selected pair incorrectly marked unselected")

    correspondences = index_by(diagnostics["correspondences"], "id", "correspondence ID")
    for record in correspondences.values():
        check_pair(record)
        check_identity(record["identity_evidence"], record["content_relationship"], diagnostic=True)
        check_location(record["location"], sides)
        require((record["verified_partner_counts"] is not None) == (record["content_relationship"] == "type3"),
                "Verified partner counts apply only to Type-3")
        selected_link(record, record["content_relationship"], "selected_pair")
        if record["selection"]["status"] == "selected_pair":
            group = groups[record["selection"]["selected_group_id"]]
            require(record["identity_evidence"] == group["identity_evidence"]
                    and record["location"] == group["location_evidence"],
                    "Selected diagnostic and ordinary evidence disagree")
        for side in ("original", "modified"):
            candidate_id = record[f"{side}_candidate_id"]
            endpoint = endpoints.get(candidate_id) or candidates[candidate_id]["endpoint"]
            context_file = record[f"{side}_context"]["revision_file"]
            require(context_file is None or endpoint["revision_file"] is None
                    or context_file == endpoint["revision_file"],
                    "Diagnostic context and endpoint files disagree")
    comparison_pairs = set()
    verified_pairs = set()
    for record in index_by(diagnostics["type3_comparisons"], "id", "Type-3 comparison ID").values():
        check_pair(record)
        pair = (record["original_candidate_id"], record["modified_candidate_id"])
        require(pair not in comparison_pairs, "Duplicate Type-3 comparison endpoints")
        comparison_pairs.add(pair)
        verification = record["verification"]
        status = verification["status"]
        selection = record["selection"]
        expected_selection = {"not_evaluated": ("not_applicable",),
                              "below_threshold": ("not_applicable",),
                              "verified": ("selected", "not_selected")}
        require(selection["status"] in expected_selection[status], "Type-3 verification/selection disagree")
        if status == "verified":
            verified_pairs.add(pair)
        require(verification["reason"] == ("ambiguous_type2c" if status == "not_evaluated" else None),
                "Type-3 verification reason disagrees")
        require(selection["reason"] is None, "Unrecorded Type-3 selection reason")
        for unit in ("lines", "tokens"):
            measurement = verification[unit]
            common, maximum = measurement["common"], measurement["maximum"]
            require(maximum >= 0 and (common is None or 0 <= common <= maximum), "Invalid Type-3 LCS bounds")
            require((common is None) == (status == "not_evaluated"), "Type-3 LCS availability disagrees")
        selected_link(record, "type3", "selected")
    type3_correspondences = [record for record in correspondences.values()
                             if record["content_relationship"] == "type3"]
    correspondence_pairs = [(record["original_candidate_id"], record["modified_candidate_id"])
                            for record in type3_correspondences]
    require(len(correspondence_pairs) == len(set(correspondence_pairs))
            and set(correspondence_pairs) == verified_pairs,
            "Verified Type-3 comparisons and classified correspondences differ")
    original_degrees = Counter(original for original, _ in verified_pairs)
    modified_degrees = Counter(modified for _, modified in verified_pairs)
    for record in type3_correspondences:
        require(record["verified_partner_counts"] == {
            "original": original_degrees[record["original_candidate_id"]],
            "modified": modified_degrees[record["modified_candidate_id"]],
        }, "Type-3 verified partner counts differ from verified-edge degrees")
    for record in index_by(diagnostics["type2b_groups"], "id", "Type-2b observation ID").values():
        for side in ("original", "modified"):
            ids = record[f"{side}_candidate_ids"]
            require(len(ids) == len(set(ids)) and all(sides.get(key) == side for key in ids),
                    "Invalid Type-2b endpoint references")
        capacity = len(record["original_candidate_ids"]) * len(record["modified_candidate_ids"])
        require(0 <= record["blind_only_pair_count"] <= capacity, "Type-2b blind count exceeds alternatives")
        if record["location"] is not None:
            require(capacity == record["blind_only_pair_count"] == 1,
                    "Type-2b location requires unique blind-only pair")
    for group in groups.values():
        check_location(group["location_evidence"], sides,
                       selected=group["correspondence"]["status"] == "selected_pair")


def self_test(documents):
    """Exercise semantic failures using structurally plausible example mutations."""
    failures = 0
    for document in documents:
        mutations = [lambda value: value["summary"].update(endpoint_count=value["summary"]["endpoint_count"] + 1)]
        if document["output_items"]:
            mutations.append(lambda value: value["output_items"][0]["member_group_ids"].append("missing-group"))
        if document["atomic_move_groups"]:
            mutations.append(lambda value: value["atomic_move_groups"][0]["identity_evidence"].update(status="contradicted", reason="continuing_name_conflict"))
            def duplicate_owner(value):
                group = value["atomic_move_groups"][0]
                group["modified"][0]["candidate_id"] = group["original"][0]["candidate_id"]
            mutations.append(duplicate_owner)
            def candidate_outside_registry(value):
                value["atomic_move_groups"][0]["original"][0]["candidate_id"] = (
                    value["pipeline_statistics"]["registered_candidate_count"] + 1)
            mutations.append(candidate_outside_registry)
        for index, group in enumerate(document["atomic_move_groups"]):
            if (group["correspondence"]["status"] == "unresolved_partners"
                    and len(group["original"]) == len(group["modified"]) == 1):
                def falsely_resolve(value, index=index):
                    value["atomic_move_groups"][index]["correspondence"] = {
                        "status": "selected_pair", "basis": "pair_proposal"}
                mutations.append(falsely_resolve)
                break
        if document.get("diagnostics", {}).get("correspondences"):
            def wrong_selected_link(value):
                selection = value["diagnostics"]["correspondences"][0]["selection"]
                selection.update(status="selected_pair", selected_group_id="missing-group")
            mutations.append(wrong_selected_link)
            for index, record in enumerate(document["diagnostics"]["correspondences"]):
                if record["content_relationship"] == "type3":
                    def wrong_partner_count(value, index=index):
                        value["diagnostics"]["correspondences"][index]["verified_partner_counts"]["original"] = 999
                    def missing_verified_correspondence(value, index=index):
                        del value["diagnostics"]["correspondences"][index]
                    mutations.extend((wrong_partner_count, missing_verified_correspondence))
                    break
        for index, item in enumerate(document["output_items"]):
            if item["kind"] == "sequence_move_group":
                def wrong_sequence_order(value, index=index):
                    value["output_items"][index]["member_group_ids"].reverse()
                def wrong_sequence_span(value, index=index):
                    value["output_items"][index]["sequence"]["original"]["last_child_ordinal"] += 1
                mutations.extend((wrong_sequence_order, wrong_sequence_span))
                break
        for index, candidate in enumerate(document.get("diagnostics", {}).get("candidates", [])):
            if candidate["selected_group_id"] is not None:
                def wrong_owner(value, index=index):
                    value["diagnostics"]["candidates"][index]["selected_group_id"] = "missing-group"
                mutations.append(wrong_owner)
                break
        for mutate in mutations:
            broken = deepcopy(document)
            mutate(broken)
            try:
                validate(broken)
            except ValueError:
                failures += 1
            else:
                raise ValueError("Self-test accepted a malformed counterexample")
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    paths = args.paths or sorted((Path(__file__).parent / "examples").glob("*.json"))
    require(bool(paths), "No example JSON documents found")
    documents = []
    for path in paths:
        try:
            document = json.loads(path.read_text())
            validate(document)
        except (ValueError, KeyError, TypeError) as error:
            raise SystemExit(f"{path}: {error}") from error
        documents.append(document)
        print(f"PASS {path.name}")
    if args.self_test:
        print(f"PASS {self_test(documents)} malformed counterexamples rejected")


if __name__ == "__main__":
    main()
