"""Strict schema-3 admission and internal atomic projections.

JSON-only validation establishes shape and cross-record consistency. It does
not prove XML resolution, structural adjacency, or detector correctness.
"""
from collections import Counter
from functools import lru_cache
import json
from pathlib import Path
import re

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


def _validate_records(document):
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
        # Use broad lexical tokens here so unsupported Unicode prefixes cannot
        # evade the ASCII-only published namespace-map contract. XPath axes
        # contain two colons and are excluded; quoted URI/text literals above
        # cannot introduce apparent QNames.
        prefixes = set(re.findall(r"(?<![\w.-])([^/\s\[\]():=,@|<>+*]+):(?=[^:\s/])", path))
        require(all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*", prefix)
                    for prefix in prefixes), "XPath uses an unsupported namespace prefix")
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



@lru_cache(maxsize=1)
def contract_schema():
    return json.loads(Path(__file__).with_name('results_schema_v3.json').read_text())


def _shape(value, schema, path='$', root=None):
    """Evaluate only the vocabulary of the pinned contract, failing closed.

    This is not a general JSON Schema engine; development tests compare it
    with Draft202012Validator using the same contract and counterexamples.
    """
    root = contract_schema() if root is None else root
    supported = {'$schema', '$defs', '$ref', 'title', 'description', 'type',
                 'const', 'enum', 'properties', 'required', 'additionalProperties',
                 'minProperties', 'propertyNames', 'items', 'minItems', 'maxItems',
                 'uniqueItems', 'minLength', 'pattern', 'minimum', 'maximum',
                 'anyOf', 'oneOf', 'allOf', 'if', 'then', 'else'}
    require(not set(schema) - supported, 'Unsupported contract vocabulary')
    if '$ref' in schema:
        ref = schema['$ref']
        require(ref.startswith('#/$defs/'), 'Unsupported contract reference')
        _shape(value, root['$defs'][ref.split('/')[-1]], path, root)
    types = {'object': dict, 'array': list, 'string': str, 'integer': int,
             'boolean': bool, 'null': type(None)}
    if 'type' in schema:
        require(type(value) is types[schema['type']], f'{path}: expected {schema["type"]}')
    if 'const' in schema:
        require(type(value) is type(schema['const']) and value == schema['const'],
                f'{path}: expected {schema["const"]!r}')
    if 'enum' in schema:
        require(any(type(value) is type(item) and value == item for item in schema['enum']),
                f'{path}: unsupported value {value!r}')
    if isinstance(value, dict):
        require(set(schema.get('required', ())) <= value.keys(), f'{path}: missing required fields')
        require(len(value) >= schema.get('minProperties', 0), f'{path}: too few properties')
        properties = schema.get('properties', {})
        additional = schema.get('additionalProperties', True)
        for key, item in value.items():
            require(isinstance(key, str), f'{path}: property names must be strings')
            if 'propertyNames' in schema:
                _shape(key, schema['propertyNames'], path, root)
            if key in properties:
                _shape(item, properties[key], f'{path}.{key}', root)
            elif additional is False:
                raise ValueError(f'{path}: unknown property {key!r}')
            elif isinstance(additional, dict):
                _shape(item, additional, f'{path}.{key}', root)
    if isinstance(value, list):
        require(len(value) >= schema.get('minItems', 0), f'{path}: too few items')
        require('maxItems' not in schema or len(value) <= schema['maxItems'], f'{path}: too many items')
        if schema.get('uniqueItems'):
            require(len({json.dumps(item, sort_keys=True) for item in value}) == len(value), f'{path}: duplicate items')
        if 'items' in schema:
            for index, item in enumerate(value):
                _shape(item, schema['items'], f'{path}[{index}]', root)
    if isinstance(value, str):
        require(len(value) >= schema.get('minLength', 0), f'{path}: string too short')
        require('pattern' not in schema or re.search(schema['pattern'], value) is not None,
                f'{path}: invalid string')
    if type(value) is int:
        require('minimum' not in schema or value >= schema['minimum'], f'{path}: below minimum')
        require('maximum' not in schema or value <= schema['maximum'], f'{path}: above maximum')
    def matches(branch):
        try:
            _shape(value, branch, path, root)
            return True
        except ValueError:
            return False
    for keyword in ('anyOf', 'oneOf'):
        if keyword in schema:
            count = sum(matches(branch) for branch in schema[keyword])
            require(count == 1 if keyword == 'oneOf' else count > 0, f'{path}: invalid {keyword} alternative')
    for branch in schema.get('allOf', ()):
        _shape(value, branch, path, root)
    if 'if' in schema:
        branch = schema.get('then' if matches(schema['if']) else 'else')
        if branch is not None:
            _shape(value, branch, path, root)


def validate_results(document):
    """Reject old versions, malformed objects and inconsistent evidence."""
    _shape(document, contract_schema())
    _validate_records(document)


# These fields belong to retained BigMoveBench execution receipts, never to the
# producer wire format. An explicit allowlist keeps future/unknown fields visible
# to strict validation instead of treating every _oracle_* name as trusted.
BENCHMARK_RECEIPT_FIELDS = frozenset({
    '_oracle_label_correction', '_oracle_reviewed_outcome',
    '_oracle_reviewed_failures', '_oracle_expected_category',
    '_oracle_category_rules_version', '_oracle_complete_detection',
    '_oracle_detected_move_id', '_oracle_observed_content_relationship',
    '_oracle_diagnostic_stage',
})


def benchmark_result_evidence(receipt):
    """Extract validated schema-3 evidence without changing a saved receipt."""
    require(isinstance(receipt, dict), 'Benchmark results receipt must be an object')
    evidence = {key: value for key, value in receipt.items() if key not in BENCHMARK_RECEIPT_FIELDS}
    validate_results(evidence)
    return evidence


def atomic_moves(document):
    """Project admitted atomic groups for internal scoring/storage consumers.

    Output items never enter this projection. Call validate_results at admission.
    """
    moves = []
    for group in document['atomic_move_groups']:
        move = {'move_id': group['id'], 'content_relationship': group['content_relationship'],
                'correspondence': group['correspondence'], 'name_evidence': group['name_evidence'],
                'location_evidence': group['location_evidence'], 'selection': group['selection']}
        for side, prefix in (('original', 'from'), ('modified', 'to')):
            for suffix, field in (('xpaths', 'xpath'), ('raw_texts', 'raw_text')):
                move[f'{prefix}_{suffix}'] = [endpoint[field] for endpoint in group[side]]
        moves.append(move)
    return moves


def resolve_locator(tree, locator, namespaces):
    """Resolve a srcReader locator exactly once against native input XML."""
    from lxml import etree
    root = tree.getroot() if hasattr(tree, 'getroot') else tree
    attributes = {etree.QName(name).localname for name in root.attrib}
    archive = etree.QName(root).localname == 'unit' and 'url' in attributes and 'filename' not in attributes
    require(namespaces.get('src') == 'http://www.srcML.org/srcML/src'
            and namespaces.get('diff') == 'http://www.srcML.org/srcDiff', 'Invalid locator namespaces')
    try:
        matches = root.getroottree().xpath(('/src:unit[1]' if archive else '') + locator, namespaces=namespaces)
    except etree.XPathError as error:
        raise ValueError(f'Invalid locator: {locator}') from error
    require(isinstance(matches, list) and len(matches) == 1 and isinstance(matches[0], etree._Element),
            f'Locator must resolve exactly once: {locator}')
    return matches[0]
