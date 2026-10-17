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


# Production consumers and format examples share one semantic admission policy.
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from srcmove_runtime.results_schema import (
    RELATIONSHIPS, require, _validate_records as validate,
)


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
