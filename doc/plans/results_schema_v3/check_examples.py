#!/usr/bin/env python3
"""Validate synthetic results-v3 examples against schema and cross-record rules.

Structural validation uses schema.json. XML resolution, true adjacency,
and detector correctness cannot be established from these documents alone.
"""

import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import re

try:
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import ValidationError
except ImportError as error:
    raise SystemExit(
        "Validation dependencies are unavailable. From the workspace root, install "
        "with: python3 -m pip install --target srcMove/build/schema3-validation -r "
        "srcMove/doc/plans/results_schema_v3/requirements-validation.txt; then set "
        "PYTHONPATH=srcMove/build/schema3-validation when running this checker. "
        "See the contract README for Docker commands."
    ) from error


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


def check_name(evidence, relationship, diagnostic=False):
    require(diagnostic or evidence != "contradicted", "Selected contradicted name evidence")
    if relationship == "type1":
        require(evidence == "not_assessed", "Type-1 name evidence must be not assessed")


def check_location(location, candidate_side=None, selected=False):
    if location["scope"] != "pair":
        return
    if selected:
        require(location["classification"] == "relocated",
                "Selected pair lacks eligible location classification")
        return
    parent = location["parent_pair"]
    require(location["carried_by_parent"] == (parent is not None),
            "Parent carrying and parent reference disagree")
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


def validate(document):
    """Raise ValueError for cross-record violations; expect schema-valid input."""
    require(document["results_schema_version"] == 3, "Expected results schema 3")
    groups = index_by(document["atomic_move_groups"], "id", "atomic group ID")
    items = index_by(document["output_items"], "id", "output item ID")
    endpoints = {}
    ownership = {}
    sides = {}
    selected_pairs = {}
    namespaces = document["xpath_context"]["namespaces"]
    require(document["xpath_context"]["convention"] == "srcreader_file_units_v1",
            "Unsupported XPath convention")
    require(namespaces.get("src") == "http://www.srcML.org/srcML/src"
            and namespaces.get("diff") == "http://www.srcML.org/srcDiff",
            "Canonical src/diff namespace bindings required")

    def check_xpath(endpoint):
        # Ignore quoted filename/name literals when looking for XPath prefixes.
        path = re.sub(r"'[^']*'|\"[^\"]*\"", "", endpoint["xpath"])
        prefixes = set(re.findall(r"(?<![\w.-])([A-Za-z_][\w.-]*):(?=[A-Za-z_*])", path))
        require(prefixes <= namespaces.keys(), "XPath uses an unbound namespace prefix")

    for group_id, group in groups.items():
        relationship = group["content_relationship"]
        check_name(group["name_evidence"], relationship)
        status = group["correspondence"]["status"]
        reason = group["selection"]["reason"]
        require((status == "copy_source_set") == (reason == "continuing_source_copy"),
                "Copy correspondence and selection reason disagree")
        if reason == "exact_neighbor_correspondence":
            require(relationship == "type1" and status == "selected_pair",
                    "Exact-neighbor selection requires Type-1 selected pair")
        if status == "selected_pair":
            require(len(group["original"]) == len(group["modified"]) == 1,
                    "Selected pair must have one endpoint per side")
            location = group["location_evidence"]
            require(location["scope"] == "pair" or (
                    relationship == "type1" and location == {
                        "scope": "not_assessed", "reason": "no_classified_pair"}),
                    "Selected pair requires classified location or unassessed exact pair")
            require(group["selection"]["reason"] not in
                    ("continuing_source_copy", "unresolved_exact_residual"),
                    "Unresolved or copy policy cannot establish selected pair")
        elif status == "unresolved_partners":
            require(relationship == "type1", "Unresolved group must be Type-1")
            require(group["location_evidence"]["scope"] == "group",
                    "Unresolved group requires group location gate")
            if reason != "unresolved_exact_residual":
                require(len(group["original"]) > 1 or len(group["modified"]) > 1,
                        "Repeated group requires alternatives")
        elif status == "copy_source_set":
            require(relationship == "type1", "Copy group requires Type-1")
            require(group["selection"]["reason"] == "continuing_source_copy",
                    "Copy selection reason disagrees")
            require(group["location_evidence"]["scope"] == "not_assessed",
                    "Copy group must retain unassessed location")
        else:
            raise ValueError("Unknown correspondence status")
        check_location(group["location_evidence"], selected=status == "selected_pair")
        for side in ("original", "modified"):
            for endpoint in group[side]:
                check_xpath(endpoint)
                candidate_id = endpoint["candidate_id"]
                require(candidate_id not in endpoints, "Candidate has multiple selected owners")
                endpoints[candidate_id] = endpoint
                ownership[candidate_id] = group_id
                sides[candidate_id] = side
        if status == "selected_pair":
            pair_key = (group["original"][0]["candidate_id"],
                        group["modified"][0]["candidate_id"], relationship)
            require(pair_key not in selected_pairs, "Duplicate selected pair")
            selected_pairs[pair_key] = group_id

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
    require(sum(statistics["processing_group_kinds"].values()) == statistics["processing_group_count"],
            "Processing group histogram total differs")
    if "diagnostics" not in document:
        return
    diagnostics = document["diagnostics"]
    counts = diagnostics["candidate_counts"]
    require(counts["active"] <= counts["registered"], "Active inventory exceeds registered inventory")
    candidates = index_by(diagnostics["candidates"], "candidate_id", "diagnostic candidate ID")
    require(all(0 <= candidate_id < counts["registered"]
                for candidate_id in candidates), "Diagnostic candidate ID outside registry bounds")
    require(len(candidates) == counts["active"], "Active candidate inventory incomplete")
    require(set(endpoints) <= set(candidates), "Selected candidate absent from inventory")
    for candidate_id, candidate in candidates.items():
        side = candidate["revision"]
        if candidate["type3_eligible"]:
            require(candidate["role"] == "structural_child"
                    and candidate["line_units"] > 0 and candidate["token_units"] > 0,
                    "Type-3 eligible candidate requires structural role and positive units")
        if candidate_id in ownership:
            require(candidate["selected_group_id"] == ownership[candidate_id]
                    and candidate["endpoint"] is None and side == sides[candidate_id],
                    "Selected candidate ownership/side disagrees")
        else:
            require(candidate["selected_group_id"] is None and candidate["endpoint"] is not None,
                    "Unselected candidate requires inline endpoint")
            require(candidate["endpoint"]["candidate_id"] == candidate_id,
                    "Inline candidate identity disagrees")
            check_xpath(candidate["endpoint"])
        sides[candidate_id] = side
    for item in items.values():
        if item["kind"] == "sequence_move_group":
            for group_id in item["member_group_ids"]:
                for side in ("original", "modified"):
                    candidate_id = groups[group_id][side][0]["candidate_id"]
                    require(candidates[candidate_id]["role"] == "structural_child",
                            "Sequence diagnostic member role invalid")

    def check_pair(record):
        for side in ("original", "modified"):
            require(sides.get(record[f"{side}_candidate_id"]) == side,
                    "Diagnostic reference missing or on incorrect side")

    def selected_link(record, relationship, selected_status):
        selection = record["selection"]
        group_id = selection["selected_group_id"]
        expected_group = selected_pairs.get((record["original_candidate_id"],
                                             record["modified_candidate_id"], relationship))
        if selection["status"] == selected_status:
            require(group_id is not None and group_id == expected_group,
                    "Diagnostic selected link does not match exact selected pair")
        else:
            require(group_id is None, "Unselected diagnostic cannot link a selected pair")
            require(expected_group is None,
                    "Exact selected pair incorrectly marked unselected")

    correspondences = index_by(diagnostics["correspondences"], "id", "correspondence ID")
    for record in correspondences.values():
        check_pair(record)
        check_name(record["name_evidence"], record["content_relationship"], diagnostic=True)
        check_location(record["location"], sides)
        require((record["verified_partner_counts"] is not None) == (record["content_relationship"] == "type3"),
                "Verified partner counts apply only to Type-3")
        selected_link(record, record["content_relationship"], "selected_pair")
        if record["selection"]["status"] == "selected_pair":
            group = groups[record["selection"]["selected_group_id"]]
            location = record["location"]
            require(record["name_evidence"] == group["name_evidence"]
                    and {key: location[key] for key in ("scope", "classification", "reason")}
                    == group["location_evidence"] and not location["carried_by_parent"],
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
        pair_candidates = [candidates[candidate_id] for candidate_id in pair]
        pair_endpoints = [endpoints.get(candidate_id) or candidates[candidate_id]["endpoint"]
                          for candidate_id in pair]
        require(all(candidate["type3_eligible"] for candidate in pair_candidates),
                "Type-3 comparison requires eligible candidates")
        require(pair_endpoints[0]["construct"] is not None
                and pair_endpoints[0]["construct"] == pair_endpoints[1]["construct"],
                "Type-3 comparison requires equal known constructs")
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
        threshold_passed = False
        for unit in ("lines", "tokens"):
            measurement = verification[unit]
            common, maximum = measurement["common"], measurement["maximum"]
            require(maximum >= 0 and (common is None or 0 <= common <= maximum), "Invalid Type-3 LCS bounds")
            lengths = [candidate["line_units" if unit == "lines" else "token_units"]
                       for candidate in pair_candidates]
            require(maximum == max(lengths), "Type-3 maximum differs from candidate lengths")
            require(common is None or common <= min(lengths), "Type-3 LCS exceeds shorter candidate")
            require((common is None) == (status == "not_evaluated"), "Type-3 LCS availability disagrees")
            threshold_passed |= common is not None and maximum > 0 and 10 * common >= 9 * maximum
        if status != "not_evaluated":
            require((status == "verified") == threshold_passed,
                    "Type-3 verification status disagrees with line-or-token threshold")
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


def validate_document(document, validator):
    """Run JSON Schema first so semantic checks can rely on the declared shape."""
    validator.validate(document)
    validate(document)


def self_test(documents, validator):
    """Reject malformed shape and cross-record examples through the public checks."""
    failures = 0
    test_documents = list(documents)
    for document in documents:
        if ("diagnostics" not in document and len(document["atomic_move_groups"]) == 1
                and document["atomic_move_groups"][0]["content_relationship"] == "type1"
                and document["atomic_move_groups"][0]["correspondence"]["status"] == "selected_pair"):
            unclassified = deepcopy(document)
            unclassified["atomic_move_groups"][0]["location_evidence"] = {
                "scope": "not_assessed", "reason": "no_classified_pair"}
            validate_document(unclassified, validator)
            test_documents.append(unclassified)
            print("PASS unclassified selected exact-pair positive variant")
            break
    for document in test_documents:
        mutations = [
            lambda value: value["summary"].update(endpoint_count=value["summary"]["endpoint_count"] + 1),
            lambda value: value.update(unexpected_property=True),
            lambda value: value.pop("configuration"),
            lambda value: value["xpath_context"]["namespaces"].update(src="urn:wrong"),
        ]
        if document["output_items"]:
            mutations.append(lambda value: value["output_items"][0]["member_group_ids"].append("missing-group"))
        if document["atomic_move_groups"]:
            mutations.append(lambda value: value["atomic_move_groups"][0].update(name_evidence="contradicted"))
            def unbound_prefix(value):
                value["atomic_move_groups"][0]["original"][0]["xpath"] = "/unbound:unit[1]"
            mutations.append(unbound_prefix)
            def duplicate_owner(value):
                group = value["atomic_move_groups"][0]
                group["modified"][0]["candidate_id"] = group["original"][0]["candidate_id"]
            mutations.append(duplicate_owner)
        for index, group in enumerate(document["atomic_move_groups"]):
            if group["correspondence"]["status"] == "selected_pair":
                def false_copy_location(value, index=index):
                    value["atomic_move_groups"][index]["location_evidence"] = {
                        "scope": "not_assessed", "reason": "continuing_source_copy"}
                def false_stationary_location(value, index=index):
                    value["atomic_move_groups"][index]["location_evidence"] = {
                        "scope": "pair", "classification": "stationary",
                        "reason": "same_anchor_interval"}
                mutations.extend((false_copy_location, false_stationary_location))
                if group["content_relationship"] != "type1":
                    def false_unclassified_nonexact(value, index=index):
                        value["atomic_move_groups"][index]["location_evidence"] = {
                            "scope": "not_assessed", "reason": "no_classified_pair"}
                    mutations.append(false_unclassified_nonexact)
                elif group["location_evidence"]["scope"] == "not_assessed":
                    def false_unclassified_copy_status(value, index=index):
                        value["atomic_move_groups"][index]["correspondence"]["status"] = "copy_source_set"
                        value["atomic_move_groups"][index]["selection"]["reason"] = "continuing_source_copy"
                    mutations.append(false_unclassified_copy_status)
                break
        for index, group in enumerate(document["atomic_move_groups"]):
            if (group["correspondence"]["status"] == "unresolved_partners"
                    and len(group["original"]) == len(group["modified"]) == 1):
                def falsely_resolve(value, index=index):
                    value["atomic_move_groups"][index]["correspondence"] = {
                        "status": "selected_pair"}
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
        if document.get("diagnostics", {}).get("candidates"):
            def candidate_outside_registry(value):
                diagnostics = value["diagnostics"]
                diagnostics["candidates"][0]["candidate_id"] = diagnostics["candidate_counts"]["registered"] + 1
            mutations.append(candidate_outside_registry)
        if document.get("diagnostics", {}).get("type3_comparisons"):
            def wrong_maximum(value):
                value["diagnostics"]["type3_comparisons"][0]["verification"]["tokens"]["maximum"] += 1
            def ineligible_type3(value):
                diagnostics = value["diagnostics"]
                candidate_id = diagnostics["type3_comparisons"][0]["original_candidate_id"]
                next(candidate for candidate in diagnostics["candidates"]
                     if candidate["candidate_id"] == candidate_id)["type3_eligible"] = False
            def wrong_eligible_role(value):
                diagnostics = value["diagnostics"]
                candidate_id = diagnostics["type3_comparisons"][0]["original_candidate_id"]
                next(candidate for candidate in diagnostics["candidates"]
                     if candidate["candidate_id"] == candidate_id)["role"] = "diff_wrapper"
            def unequal_type3_constructs(value):
                diagnostics = value["diagnostics"]
                candidate_id = diagnostics["type3_comparisons"][0]["modified_candidate_id"]
                candidate = next(candidate for candidate in diagnostics["candidates"]
                                 if candidate["candidate_id"] == candidate_id)
                if candidate["selected_group_id"] is None:
                    endpoint = candidate["endpoint"]
                else:
                    group = next(group for group in value["atomic_move_groups"]
                                 if group["id"] == candidate["selected_group_id"])
                    endpoint = next(endpoint for endpoint in group["modified"]
                                    if endpoint["candidate_id"] == candidate_id)
                endpoint["construct"] = "synthetic:unequal_construct"
            mutations.extend((wrong_maximum, ineligible_type3, wrong_eligible_role,
                              unequal_type3_constructs))
            for index, record in enumerate(document["diagnostics"]["type3_comparisons"]):
                status = record["verification"]["status"]
                if status == "verified":
                    def false_verified(value, index=index):
                        verification = value["diagnostics"]["type3_comparisons"][index]["verification"]
                        verification["lines"]["common"] = 0
                        verification["tokens"]["common"] = 0
                    mutations.append(false_verified)
                    break
            for index, record in enumerate(document["diagnostics"]["type3_comparisons"]):
                if record["verification"]["status"] == "below_threshold":
                    for unit, field in (("tokens", "token_units"), ("lines", "line_units")):
                        lengths = [candidate[field] for candidate in document["diagnostics"]["candidates"]
                                   if candidate["candidate_id"] in (record["original_candidate_id"],
                                                                   record["modified_candidate_id"])]
                        required = (9 * max(lengths) + 9) // 10
                        if required > 0 and required <= min(lengths):
                            def false_below_threshold(value, index=index, unit=unit, required=required):
                                # Only one metric passes; requiring both would be incorrect.
                                value["diagnostics"]["type3_comparisons"][index]["verification"][unit]["common"] = required
                            mutations.append(false_below_threshold)
                            break
                    break
        for mutate in mutations:
            broken = deepcopy(document)
            mutate(broken)
            try:
                validate_document(broken, validator)
            except (ValueError, ValidationError):
                failures += 1
            else:
                raise ValueError("Self-test accepted a malformed counterexample")
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    schema = json.loads((Path(__file__).parent / "schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    paths = args.paths or sorted((Path(__file__).parent / "examples").glob("*.json"))
    require(bool(paths), "No example JSON documents found")
    documents = []
    for path in paths:
        try:
            document = json.loads(path.read_text())
            validate_document(document, validator)
        except (ValueError, ValidationError, KeyError, TypeError) as error:
            raise SystemExit(f"{path}: {error}") from error
        documents.append(document)
        print(f"PASS {path.name}")
    if args.self_test:
        print(f"PASS {self_test(documents, validator)} malformed counterexamples rejected")


if __name__ == "__main__":
    main()
