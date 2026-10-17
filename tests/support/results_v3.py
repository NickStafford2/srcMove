"""Isolated schema-3 producer checks and frozen schema-2 differential evidence.

This is a test-only comparison, not a production compatibility reader.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT = REPO_ROOT / "doc/plans/results_schema_v3"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def capture_manifest(directory):
    """Index immutable command snapshots, deduplicated by input bytes/settings."""
    directory = Path(directory).resolve()
    receipt = json.loads((directory.parent / "baseline-identity.json").read_text())
    wanted_hash = receipt["binary_sha256"]
    cases = {}
    for record_path in sorted(directory.rglob("commands/*/command.json")):
        record = json.loads(record_path.read_text())
        if record.get("returncode") != 0 or record.get("executable", {}).get("sha256") != wanted_hash:
            continue
        argv = record["argv"]
        if "--results" not in argv or len(argv) < 3 or argv[2].startswith("--"):
            continue  # Keep annotation-producing commands as replay baselines.
        command_dir = record_path.parent
        result_index = argv.index("--results") + 1
        input_path = command_dir / "before" / ("argument-1-" + Path(argv[1]).name)
        result_path = command_dir / "after" / (f"argument-{result_index}-" + Path(argv[result_index]).name)
        xml_path = command_dir / "after" / ("argument-2-" + Path(argv[2]).name)
        if not all(path.is_file() for path in (input_path, result_path, xml_path)):
            continue
        payload = json.loads(result_path.read_text())
        if payload.get("results_schema_version") != 2:
            raise ValueError("Frozen baseline is not schema 2")
        granularity = argv[argv.index("--min-granularity") + 1] if "--min-granularity" in argv else "statement"
        key = (sha256(input_path), granularity)
        case = {
            "id": key[0][:16] + "-" + granularity,
            "granularity": granularity,
            "input": str(input_path.relative_to(directory)),
            "results": str(result_path.relative_to(directory)),
            "xml": str(xml_path.relative_to(directory)),
            "command": str(record_path.relative_to(directory)),
            "sha256": {"input": key[0], "results": sha256(result_path), "xml": sha256(xml_path)},
            "diagnostics": "diagnostics" in payload,
        }
        if key not in cases or (case["diagnostics"] and not cases[key]["diagnostics"]):
            cases[key] = case
    if not cases:
        raise ValueError("No successful frozen srcMove commands found")
    manifest = {
        "purpose": "Frozen executable differential baseline; no source-to-binary binding is asserted.",
        "binary_sha256": wanted_hash,
        "source_binding": receipt["source_binding"],
        "cases": sorted(cases.values(), key=lambda case: case["id"]),
    }
    (directory / "replay-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def name_evidence(status):
    return "not_assessed" if status in ("exact", "unassessed") else status


def ordinary_projection(payload):
    """Preserve all old result facts that the proposed schema represents."""
    if payload["results_schema_version"] == 2:
        groups = [{
            "id": m["move_id"], "content_relationship": m["content_relationship"],
            "original": list(zip(m["from_xpaths"], m["from_raw_texts"])),
            "modified": list(zip(m["to_xpaths"], m["to_raw_texts"])),
            "name_evidence": name_evidence(m["identity_status"]),
            "correspondence": ("copy_source_set" if m["selection_reason"] == "continuing_source_copy"
                               else "unresolved_partners" if m["selection_reason"] == "unresolved_exact_residual"
                               or len(m["from_xpaths"]) > 1 or len(m["to_xpaths"]) > 1
                               else "selected_pair"),
            "selection": {"matching_weight_milli": m["confidence_milli"],
                          "utility": m["selection_utility"], "matched_units": m["matched_units"],
                          "reason": m["selection_reason"]},
        } for m in payload["moves"]]
        items = [{
            "id": report["move_id"] if report["report_kind"] == "ordered_sequence" else "item:" + report["move_id"],
            "kind": "sequence_move_group" if report["report_kind"] == "ordered_sequence" else "atomic_move_group",
            "members": report["member_move_ids"],
        } for report in payload["reported_moves"]]
        sequences = {s["sequence_id"]: {"policy": s["policy"],
                     "original": {k: v for k, v in s["from"].items() if k != "member_xpaths"},
                     "modified": {k: v for k, v in s["to"].items() if k != "member_xpaths"}}
                     for s in payload["move_sequences"]}
        summary = {"output_item_count": payload["reported_move_count"],
                   "atomic_move_group_count": payload["move_group_count"],
                   "sequence_move_group_count": payload["sequence_cluster_count"],
                   "pair_capacity": payload["move_pair_count"],
                   "endpoint_count": payload["annotated_region_count"],
                   "atomic_content_relationships": payload["content_relationships"],
                   "output_content_relationships": payload["reported_content_relationships"]}
        stats = {"srcdiff_region_count": payload["regions_total"],
                 "grouped_candidate_entry_count": payload["candidates_total"],
                 "processing_group_count": payload["groups_total"],
                 "processing_group_kinds": payload["group_kinds"]}
    else:
        groups = [{
            "id": m["id"], "content_relationship": m["content_relationship"],
            "original": [(e["xpath"], e["raw_text"]) for e in m["original"]],
            "modified": [(e["xpath"], e["raw_text"]) for e in m["modified"]],
            "name_evidence": m["name_evidence"], "correspondence": m["correspondence"]["status"],
            "selection": m["selection"],
        } for m in payload["atomic_move_groups"]]
        items = [{"id": item["id"], "kind": item["kind"], "members": item["member_group_ids"]}
                 for item in payload["output_items"]]
        sequences = {item["id"]: item["sequence"] for item in payload["output_items"]
                     if item["kind"] == "sequence_move_group"}
        summary, stats = payload["summary"], payload["pipeline_statistics"]
    return {"groups": groups, "items": items, "sequences": sequences, "summary": summary, "statistics": stats}


def normalize_context(context):
    return {key: None if isinstance(value, str) and not value else value
            for key, value in context.items()}


def diagnostic_projection(payload):
    """Compare existing diagnostic facts; new IDs/ownership are checked separately."""
    diagnostics = payload["diagnostics"]
    old = payload["results_schema_version"] == 2
    if old:
        candidates = [{
            "id": c["candidate_id"], "revision": "original" if c["side"] == "delete" else "modified",
            "xpath": c["xpath"], "construct": c["construct"] or None, "role": c["role"],
            "raw_text": c["raw_text"], "type3_eligible": c["type3_eligible"],
            "line_units": c["line_units"], "token_units": c["token_units"],
        } for c in diagnostics["candidates"]]
    else:
        selected = {e["candidate_id"]: e for g in payload["atomic_move_groups"]
                    for side in ("original", "modified") for e in g[side]}
        candidates = []
        for c in diagnostics["candidates"]:
            e = selected[c["candidate_id"]] if c["endpoint"] is None else c["endpoint"]
            candidates.append({"id": c["candidate_id"], "revision": c["revision"],
                               "xpath": e["xpath"], "construct": e["construct"], "role": c["role"],
                               "raw_text": e["raw_text"], "type3_eligible": c["type3_eligible"],
                               "line_units": c["line_units"], "token_units": c["token_units"]})
    correspondences = []
    for c in diagnostics["correspondences"]:
        if old:
            location = {"scope": "pair", "classification": c["shadow_change"],
                        "reason": c["classification_reason"],
                        "observations": {name: c[name + "_observation"] for name in
                                         ("file", "semantic_container", "anchor_interval", "relative_order", "ancestor")},
                        "carried_by_parent": c["carried_by_parent"],
                        "parent_pair": ({"original_candidate_id": c["parent_delete_candidate_id"],
                                         "modified_candidate_id": c["parent_insert_candidate_id"]}
                                        if c["carried_by_parent"] else None)}
            a, b, relationship = c["delete_candidate_id"], c["insert_candidate_id"], c["correspondence_kind"]
            selected = c["current_result"] == "move"
            # Old current_result could falsely mark an unresolved singleton as a pair.
            if selected:
                group = next((m for m in payload["moves"] if m["from_xpaths"] == [
                    next(x["xpath"] for x in diagnostics["candidates"] if x["candidate_id"] == a)]
                    and m["to_xpaths"] == [
                    next(x["xpath"] for x in diagnostics["candidates"] if x["candidate_id"] == b)]), None)
                if group and group["selection_reason"] in ("unresolved_exact_residual", "continuing_source_copy"):
                    selected = False
            row = {"a": a, "b": b, "relationship": relationship,
                   "name": name_evidence(c["identity_status"]), "location": location,
                   "original_context": normalize_context(c["before_context"]),
                   "modified_context": normalize_context(c["after_context"]),
                   "partners": ({"original": c["delete_verified_partner_count"],
                                 "modified": c["insert_verified_partner_count"]} if relationship == "type3" else None),
                   "selected": selected}
        else:
            row = {"a": c["original_candidate_id"], "b": c["modified_candidate_id"],
                   "relationship": c["content_relationship"], "name": c["name_evidence"],
                   "location": c["location"], "original_context": c["original_context"],
                   "modified_context": c["modified_context"], "partners": c["verified_partner_counts"],
                   "selected": c["selection"]["status"] == "selected_pair"}
        correspondences.append(row)
    comparisons = []
    for c in diagnostics["type3_pairs" if old else "type3_comparisons"]:
        if old:
            status, reason, selected = {
                "ambiguous_type2c": ("not_evaluated", "ambiguous_type2c", "not_applicable"),
                "below_threshold": ("below_threshold", None, "not_applicable"),
                "selected": ("verified", None, "selected"),
                "selection_rejected": ("verified", None, "not_selected"),
            }[c["outcome"]]
            comparisons.append({"a": c["delete_candidate_id"], "b": c["insert_candidate_id"],
                "verification": {"status": status, "reason": reason,
                    "lines": {"common": None if status == "not_evaluated" else c["common_lines"], "maximum": c["maximum_lines"]},
                    "tokens": {"common": None if status == "not_evaluated" else c["common_tokens"], "maximum": c["maximum_tokens"]}},
                "selection": selected})
        else:
            comparisons.append({"a": c["original_candidate_id"], "b": c["modified_candidate_id"],
                                "verification": c["verification"], "selection": c["selection"]["status"]})
    blind = []
    for g in diagnostics["type2b_groups"]:
        blind.append({"original": g["delete_candidate_ids"] if old else g["original_candidate_ids"],
                      "modified": g["insert_candidate_ids"] if old else g["modified_candidate_ids"],
                      "count": g["blind_only_pair_count"],
                      "location": ({"classification": g["location_change"], "reason": g["location_reason"]}
                                   if g.get("location_change") else None) if old else g["location"]})
    return {"candidates": candidates, "correspondences": correspondences, "comparisons": comparisons, "blind": blind}


def validate_native_xml(input_path, annotated_path, payload, known_ambiguities=None):
    from lxml import etree
    locator = load_module("results_v3_locators", CONTRACT / "check_locators.py")
    tree = etree.parse(str(input_path), etree.XMLParser(resolve_entities=False, no_network=True))
    annotated = etree.parse(str(annotated_path), etree.XMLParser(resolve_entities=False, no_network=True))
    # The native serializer already adds unit metadata and normalizes archive
    # framing whitespace. Complete XML bytes are compared to the frozen writer
    # by the replay test; independent checks here concern locators and endpoints.
    ns = payload["xpath_context"]["namespaces"]
    known = {row["xpath"]: row for row in known_ambiguities or []}

    from tests.support.sequence_xml import validate_sequences
    validate_sequences(input_path, tree, payload, locator.resolve)

    def resolve_checked(document, xpath, label):
        if xpath not in known:
            return locator.resolve(document, xpath, ns)
        expression = ("/src:unit[1]" if locator.archive_mode(document) else "") + xpath
        matches = document.xpath(expression, namespaces=ns)
        expected_count = known[xpath][label + "_matches"]
        if len(matches) != expected_count or expected_count <= 1:
            raise AssertionError("Known baseline locator ambiguity changed: " + xpath)
        if not all(isinstance(node, etree._Element) for node in matches):
            raise AssertionError("Known ambiguous locator no longer resolves to elements")
        return None  # This remains a failed unique-endpoint consumer audit.

    expected = []
    for g in payload["atomic_move_groups"]:
        for side, attribute, other in (("original", "to", "modified"), ("modified", "from", "original")):
            partner_paths = sorted(e["xpath"] for e in g[other])
            for e in g[side]:
                expected.append((g["id"], side))
                before = resolve_checked(tree, e["xpath"], "input")
                after = resolve_checked(annotated, e["xpath"], "annotated")
                if before is None or after is None:
                    continue
                if "revision_file" in e:
                    unit = before
                    while unit is not None and unit.tag != "{" + locator.SRC + "}unit":
                        unit = unit.getparent()
                    filename = unit.get("filename") if unit is not None else None
                    if filename and "|" in filename:
                        pieces = filename.split("|", 1)
                        filename = pieces[0 if side == "original" else 1]
                    if e["revision_file"] != (filename or None):
                        raise AssertionError("Revision-specific endpoint filename differs from input unit")
                if e.get("construct") is not None and e["construct"].split(":")[-1] != etree.QName(before).localname:
                    raise AssertionError("Endpoint construct differs from located input element")
                if after.get("{" + locator.MV + "}id") != g["id"]:
                    raise AssertionError("Endpoint annotation ID disagrees")
                link = after.get("{" + locator.MV + "}" + attribute)
                if link is None or sorted(link.split(" | ")) != partner_paths:
                    raise AssertionError("Endpoint partner links disagree")
                # The retained source is revision-specific, excluding opposite-side descendants.
                from tests.support.annotations import revision_text
                revision = "delete" if side == "original" else "insert"
                text = revision_text(before, revision, revision)
                if text != e["raw_text"]:
                    raise AssertionError(f"Endpoint text differs: {text!r} != {e['raw_text']!r}")
    actual = []
    for node in annotated.iter():
        gid = node.get("{" + locator.MV + "}id")
        if gid is not None:
            side = "original" if node.get("{" + locator.MV + "}to") is not None else "modified"
            actual.append((gid, side))
    if Counter(actual) != Counter(expected):
        raise AssertionError("XML contains missing or extra atomic annotations")
    if "diagnostics" in payload:
        for c in payload["diagnostics"]["candidates"]:
            if c["endpoint"] is not None:
                resolve_checked(tree, c["endpoint"]["xpath"], "input")


def audit_baseline_locators(directory):
    """Record observed old ambiguities with exact paths/counts, never a blanket skip."""
    from lxml import etree
    directory = Path(directory).resolve()
    manifest_path = directory / "replay-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    locator = load_module("baseline_locator_audit", CONTRACT / "check_locators.py")
    ns = {"src": locator.SRC, "diff": locator.DIFF}
    for case in manifest["cases"]:
        before = etree.parse(str(directory / case["input"]), etree.XMLParser(resolve_entities=False, no_network=True))
        after = etree.parse(str(directory / case["xml"]), etree.XMLParser(resolve_entities=False, no_network=True))
        payload = json.loads((directory / case["results"]).read_text())
        paths = {path for move in payload["moves"] for side in ("from", "to") for path in move[side + "_xpaths"]}
        paths.update(c["xpath"] for c in payload.get("diagnostics", {}).get("candidates", []))
        ambiguities = []
        for path in sorted(paths):
            counts = {}
            for label, tree in (("input", before), ("annotated", after)):
                expression = ("/src:unit[1]" if locator.archive_mode(tree) else "") + path
                counts[label + "_matches"] = len(tree.xpath(expression, namespaces=ns))
            if counts == {"input_matches": 1, "annotated_matches": 1}:
                continue
            if counts["input_matches"] <= 1 or counts["input_matches"] != counts["annotated_matches"]:
                raise ValueError(f"Unexpected baseline locator failure: {case['id']} {path} {counts}")
            ambiguities.append({"xpath": path, **counts})
        case["locator_audit"] = {
            "status": "known_ambiguous" if ambiguities else "unique",
            "ambiguous_locators": ambiguities,
        }
    manifest["locator_audit_counts"] = dict(Counter(
        case["locator_audit"]["status"] for case in manifest["cases"]))
    report = directory / "report.json"
    if report.is_file():
        legacy = json.loads(report.read_text())
        manifest["legacy_suite_outcomes"] = legacy["counts"]
        manifest["legacy_oracle_failures"] = [r["id"] for r in legacy["outcomes"] if r["status"] != "pass"]
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path, help="Legacy test artifact directory to index")
    parser.add_argument("--audit-locators", action="store_true", help="Record independently observed native locator ambiguities")
    args = parser.parse_args()
    manifest = capture_manifest(args.baseline)
    if args.audit_locators:
        manifest = audit_baseline_locators(args.baseline)
    print(f"Indexed {len(manifest['cases'])} unique input/settings baselines")


if __name__ == "__main__":
    main()
