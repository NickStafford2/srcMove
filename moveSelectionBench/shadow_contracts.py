"""Reviewed oracle for the observation-only correspondence classifier."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterator


SRC_NAMESPACE = "http://www.srcML.org/srcML/src"
DIFF_NAMESPACES = {
    "http://www.srcML.org/srcDiff",
    "http://www.srcML.org/srcDiff/diff",
}
MEMBERSHIP_BY_DIFF_NAME = {
    "delete": "original_only",
    "insert": "modified_only",
    "common": "both",
}
REQUIRED_CONTEXT_DIMENSIONS = {
    "file",
    "semantic_container",
    "anchor_interval",
    "ancestor_change",
    "relative_order",
}
CONTEXT_VALUES = {
    "file": {"same", "different"},
    "semantic_container": {"same_mapped", "different_mapped", "unknown"},
    "anchor_interval": {"same", "different", "crossed", "same_within_parent", "unknown"},
    "ancestor_change": {"none", "wrapped", "unwrapped", "incompatible", "unknown"},
    "relative_order": {"unchanged", "crossed_stable_sibling", "symmetric", "unknown"},
}
SEMANTIC_CONTAINERS = {
    "function",
    "function_decl",
    "constructor",
    "destructor",
    "class",
    "struct",
    "interface",
    "namespace",
}
REASON_CHANGE_KIND = {
    "same_anchor_interval": "stationary",
    "different_file": "relocated",
    "different_semantic_container": "relocated",
    "crossed_stable_sibling": "relocated",
    "ancestor_wrapped": "restructured",
    "ancestor_unwrapped": "restructured",
    "stable_relative_to_relocated_parent": "stationary",
    "non_unique_correspondence": "ambiguous",
    "incompatible_context": "ambiguous",
    "insufficient_context": "ambiguous",
}


class ShadowContractError(ValueError):
    """A shadow contract or its srcDiff precondition is invalid."""


def normalize_text(value: str) -> str:
    return " ".join(value.split())


def _safe_file(root: Path, value: Any, context: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ShadowContractError(f"{context}: path must be a non-empty string")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ShadowContractError(f"{context}: unsafe path {value!r}")
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as error:
        raise ShadowContractError(f"{context}: path escapes catalog directory") from error
    if not resolved.is_file():
        raise ShadowContractError(f"{context}: file does not exist: {resolved}")
    return resolved


def load_shadow_contracts(path: Path) -> list[dict[str, Any]]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ShadowContractError(f"cannot read {path}: {error}") from error
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise ShadowContractError("shadow contract schema_version must be 1")
    raw_cases = document.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ShadowContractError("shadow contract cases must be a non-empty array")

    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ordinal, raw_case in enumerate(raw_cases, start=1):
        context = f"case {ordinal}"
        if not isinstance(raw_case, dict):
            raise ShadowContractError(f"{context}: must be an object")
        case_id = raw_case.get("id")
        if not isinstance(case_id, str) or not case_id:
            raise ShadowContractError(f"{context}: id must be a non-empty string")
        if case_id in seen:
            raise ShadowContractError(f"duplicate shadow contract id: {case_id}")
        seen.add(case_id)

        fixture = raw_case.get("fixture")
        if not isinstance(fixture, dict) or len(fixture) != 1:
            raise ShadowContractError(f"{case_id}: fixture must select one input form")
        resolved_fixture: dict[str, Any]
        if "srcdiff" in fixture:
            resolved_fixture = {
                "srcdiff": _safe_file(path.parent, fixture["srcdiff"], f"{case_id}.fixture")
            }
        elif "source_pair" in fixture and isinstance(fixture["source_pair"], dict):
            pair = fixture["source_pair"]
            resolved_fixture = {
                "source_pair": {
                    side: _safe_file(path.parent, pair.get(side), f"{case_id}.{side}")
                    for side in ("original", "modified")
                }
            }
        else:
            raise ShadowContractError(f"{case_id}: unknown fixture form")

        precondition = raw_case.get("srcdiff_precondition")
        if not isinstance(precondition, dict):
            raise ShadowContractError(f"{case_id}: srcdiff_precondition must be an object")
        for field in ("element", "before_text", "after_text"):
            if not isinstance(precondition.get(field), str) or not precondition[field]:
                raise ShadowContractError(f"{case_id}: {field} must be non-empty text")
        for field in ("before_count", "after_count"):
            if not isinstance(precondition.get(field), int) or precondition[field] < 1:
                raise ShadowContractError(f"{case_id}: {field} must be a positive integer")
        if precondition.get("correspondence_kind") != "type1":
            raise ShadowContractError(f"{case_id}: Phase 0 contracts must use Type-1 evidence")
        cardinality = precondition.get("cardinality")
        if cardinality not in {"one_to_one", "many_to_many"}:
            raise ShadowContractError(f"{case_id}: unsupported cardinality")
        counts = (precondition["before_count"], precondition["after_count"])
        if cardinality == "one_to_one" and counts != (1, 1):
            raise ShadowContractError(f"{case_id}: one_to_one requires one endpoint per side")
        if cardinality == "many_to_many" and min(counts) < 2:
            raise ShadowContractError(f"{case_id}: many_to_many requires repeated endpoints")

        observations = raw_case.get("observed_context")
        if not isinstance(observations, dict) or set(observations) != REQUIRED_CONTEXT_DIMENSIONS:
            raise ShadowContractError(
                f"{case_id}: observed_context must declare every context dimension"
            )
        if not all(isinstance(value, str) and value for value in observations.values()):
            raise ShadowContractError(f"{case_id}: context observations must be non-empty strings")
        for dimension, value in observations.items():
            if value not in CONTEXT_VALUES[dimension]:
                raise ShadowContractError(
                    f"{case_id}: unsupported {dimension} observation {value!r}"
                )

        structural = raw_case.get("structural_precondition")
        if not isinstance(structural, dict):
            raise ShadowContractError(f"{case_id}: structural_precondition must be an object")
        allowed_structural = {
            "anchors",
            "container_bounds",
            "crossed_common",
            "exclusive_ancestors",
            "corresponding_parent",
        }
        if not set(structural).issubset(allowed_structural):
            raise ShadowContractError(f"{case_id}: unknown structural precondition")
        if observations["anchor_interval"] == "same" and not (
            "anchors" in structural or structural.get("container_bounds") is True
        ):
            raise ShadowContractError(f"{case_id}: same interval requires reliable boundaries")
        if observations["anchor_interval"] == "crossed" and "crossed_common" not in structural:
            raise ShadowContractError(f"{case_id}: crossed interval requires a common sibling")
        if observations["anchor_interval"] == "same_within_parent" and "corresponding_parent" not in structural:
            raise ShadowContractError(f"{case_id}: carried child requires a corresponding parent")

        expected = raw_case.get("expected_shadow")
        if not isinstance(expected, dict):
            raise ShadowContractError(f"{case_id}: expected_shadow must be an object")
        change_kind = expected.get("change_kind")
        if change_kind not in set(REASON_CHANGE_KIND.values()):
            raise ShadowContractError(f"{case_id}: unknown change_kind")
        reason = expected.get("classification_reason")
        if reason not in REASON_CHANGE_KIND:
            raise ShadowContractError(f"{case_id}: unknown classification_reason")
        if REASON_CHANGE_KIND[reason] != change_kind:
            raise ShadowContractError(f"{case_id}: reason does not support change_kind")
        carried = expected.get("carried_by_parent", False)
        if not isinstance(carried, bool):
            raise ShadowContractError(f"{case_id}: carried_by_parent must be boolean")

        rationale = raw_case.get("rationale")
        if not isinstance(rationale, str) or not rationale:
            raise ShadowContractError(f"{case_id}: rationale must be non-empty")
        cases.append({**raw_case, "fixture": resolved_fixture})
    return cases


def _expanded_name(tag: str) -> tuple[str | None, str]:
    if tag.startswith("{"):
        namespace, local = tag[1:].split("}", 1)
        return namespace, local
    return None, tag


def _elements_with_membership(
    element: ET.Element, membership: str = "both"
) -> Iterator[tuple[ET.Element, str]]:
    namespace, local = _expanded_name(element.tag)
    effective = MEMBERSHIP_BY_DIFF_NAME.get(local, membership) if namespace in DIFF_NAMESPACES else membership
    yield element, effective
    for child in element:
        yield from _elements_with_membership(child, effective)


def validate_srcdiff_precondition(case: dict[str, Any], srcdiff_path: Path) -> dict[str, int]:
    try:
        root = ET.parse(srcdiff_path).getroot()
    except (OSError, ET.ParseError) as error:
        raise ShadowContractError(f"{case['id']}: invalid srcDiff fixture: {error}") from error
    precondition = case["srcdiff_precondition"]
    wanted_element = precondition["element"]
    wanted = {
        "original_only": normalize_text(precondition["before_text"]),
        "modified_only": normalize_text(precondition["after_text"]),
    }
    counts = {"original_only": 0, "modified_only": 0}
    walked = list(_elements_with_membership(root))
    memberships = {id(element): membership for element, membership in walked}
    parents = {id(child): parent for parent in root.iter() for child in parent}
    positions = {id(element): index for index, (element, _) in enumerate(walked)}
    endpoints: dict[str, list[ET.Element]] = {"original_only": [], "modified_only": []}
    for element, membership in walked:
        namespace, local = _expanded_name(element.tag)
        if namespace != SRC_NAMESPACE or local != wanted_element or membership not in counts:
            continue
        if normalize_text("".join(element.itertext())) == wanted[membership]:
            counts[membership] += 1
            endpoints[membership].append(element)
    expected_counts = {
        "original_only": precondition["before_count"],
        "modified_only": precondition["after_count"],
    }
    if counts != expected_counts:
        raise ShadowContractError(
            f"{case['id']}: srcDiff precondition counts {counts}, expected {expected_counts}"
        )
    before = endpoints["original_only"][0]
    after = endpoints["modified_only"][0]

    def ancestors(element: ET.Element) -> Iterator[ET.Element]:
        current = parents.get(id(element))
        while current is not None:
            yield current
            current = parents.get(id(current))

    def revision_file(element: ET.Element, side: str) -> str:
        unit = next(
            (
                item
                for item in ancestors(element)
                if _expanded_name(item.tag) == (SRC_NAMESPACE, "unit") and item.get("filename")
            ),
            root if root.get("filename") else None,
        )
        if unit is None:
            return ""
        filename = unit.get("filename", "")
        if "|" not in filename:
            return filename
        original, modified = filename.split("|", 1)
        return original if side == "original_only" else modified

    actual_file_relation = (
        "same"
        if revision_file(before, "original_only") == revision_file(after, "modified_only")
        else "different"
    )
    expected_file_relation = case["observed_context"]["file"]
    if actual_file_relation != expected_file_relation:
        raise ShadowContractError(
            f"{case['id']}: file relation {actual_file_relation}, expected {expected_file_relation}"
        )

    def mapped_container(element: ET.Element) -> ET.Element | None:
        for item in ancestors(element):
            namespace, local = _expanded_name(item.tag)
            if (
                namespace == SRC_NAMESPACE
                and local in SEMANTIC_CONTAINERS
                and memberships[id(item)] == "both"
            ):
                return item
        return None

    before_container = mapped_container(before)
    after_container = mapped_container(after)
    if before_container is None or after_container is None:
        container_relation = "unknown"
    elif before_container is after_container:
        container_relation = "same_mapped"
    else:
        container_relation = "different_mapped"
    expected_container_relation = case["observed_context"]["semantic_container"]
    if container_relation != expected_container_relation:
        raise ShadowContractError(
            f"{case['id']}: container relation {container_relation}, "
            f"expected {expected_container_relation}"
        )

    structural = case["structural_precondition"]
    if structural.get("container_bounds") is True and not (
        before_container is not None and before_container is after_container
    ):
        raise ShadowContractError(
            f"{case['id']}: container bounds require one shared mapped container"
        )

    def common_exact(text: str) -> ET.Element:
        matches = [
            element
            for element, membership in walked
            if membership == "both" and normalize_text("".join(element.itertext())) == text
        ]
        if len(matches) != 1:
            raise ShadowContractError(
                f"{case['id']}: common construct {text!r} resolved {len(matches)} times"
            )
        return matches[0]

    anchors = structural.get("anchors")
    if anchors is not None:
        if not isinstance(anchors, dict) or set(anchors) != {"before", "after"}:
            raise ShadowContractError(f"{case['id']}: anchors must declare before and after")
        lower = common_exact(normalize_text(anchors["before"]))
        upper = common_exact(normalize_text(anchors["after"]))
        endpoint_positions = [positions[id(item)] for values in endpoints.values() for item in values]
        if not (positions[id(lower)] < min(endpoint_positions) <= max(endpoint_positions) < positions[id(upper)]):
            raise ShadowContractError(f"{case['id']}: endpoints are outside the declared anchor interval")

    crossed = structural.get("crossed_common")
    if crossed is not None:
        anchor = common_exact(normalize_text(crossed))
        if not (positions[id(before)] < positions[id(anchor)] < positions[id(after)]):
            raise ShadowContractError(f"{case['id']}: target does not cross the common sibling")

    expected_ancestors = structural.get("exclusive_ancestors")
    if expected_ancestors is not None:
        if not isinstance(expected_ancestors, dict) or set(expected_ancestors) != {
            "before",
            "after",
        }:
            raise ShadowContractError(f"{case['id']}: invalid exclusive_ancestors")
        relevant_names = {"if_stmt", "else", "for", "while", "do", "switch", "try", "catch", "macro"}
        for side_name, endpoint, membership in (
            ("before", before, "original_only"),
            ("after", after, "modified_only"),
        ):
            expected_names = expected_ancestors[side_name]
            if not isinstance(expected_names, list) or not all(
                isinstance(value, str) and value in relevant_names for value in expected_names
            ):
                raise ShadowContractError(f"{case['id']}: invalid {side_name} ancestors")
            actual_names = {
                local
                for item in ancestors(endpoint)
                for namespace, local in [_expanded_name(item.tag)]
                if namespace == SRC_NAMESPACE
                and local in relevant_names
                and memberships[id(item)] == membership
            }
            if actual_names != set(expected_names):
                raise ShadowContractError(
                    f"{case['id']}: exclusive {side_name} ancestors {sorted(actual_names)}, "
                    f"expected {sorted(expected_names)}"
                )

    parent_contract = structural.get("corresponding_parent")
    if parent_contract is not None:
        if not isinstance(parent_contract, dict) or set(parent_contract) != {"element", "text"}:
            raise ShadowContractError(f"{case['id']}: invalid corresponding_parent")
        parent_text = normalize_text(parent_contract["text"])
        parent_element = parent_contract["element"]
        resolved = []
        for endpoint, membership in ((before, "original_only"), (after, "modified_only")):
            matches = [
                item
                for item in ancestors(endpoint)
                if _expanded_name(item.tag) == (SRC_NAMESPACE, parent_element)
                and memberships[id(item)] == membership
                and normalize_text("".join(item.itertext())) == parent_text
            ]
            if len(matches) != 1:
                raise ShadowContractError(
                    f"{case['id']}: corresponding parent resolved {len(matches)} times"
                )
            resolved.append(matches[0])

    return {"before_count": counts["original_only"], "after_count": counts["modified_only"]}
