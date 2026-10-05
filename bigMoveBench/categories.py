"""Versioned benchmark membership, separate from database and detector labels."""
from __future__ import annotations

from typing import Any, Mapping

CATEGORY_RULES_VERSION = 1
CATEGORIES = ("type1", "type2b", "type2c", "type3")


def category_sql(alias: str = "p") -> str:
    """BigCloneEval membership for positive rows (scores are stored in [0,1])."""
    return (
        f"CASE WHEN {alias}.syntactic_type=1 THEN 'type1' "
        f"WHEN {alias}.syntactic_type=2 THEN 'type2c' "
        f"WHEN {alias}.syntactic_type=3 AND {alias}.similarity_line>=1.0 "
        f"AND {alias}.similarity_token>=1.0 THEN 'type2b' "
        f"WHEN {alias}.syntactic_type=3 THEN 'type3' END"
    )


def benchmark_category(row: Mapping[str, Any]) -> str:
    if row.get("pair_kind", row.get("case_kind")) == "known_false_positive":
        return "known_false_positive"
    kind = row.get("syntactic_type")
    if kind == 1:
        return "type1"
    if kind == 2:
        return "type2c"
    if kind == 3:
        similarity = row.get("similarity", {})
        line = row.get("similarity_line", similarity.get("line"))
        token = row.get("similarity_token", similarity.get("token"))
        if line is None or token is None:
            raise ValueError("type-3 database rows require both similarity fields")
        return "type2b" if line >= 1.0 and token >= 1.0 else "type3"
    raise ValueError(f"unsupported BigCloneBench syntactic type: {kind}")


def normalize_reported_category(kind: str) -> str:
    """Legacy srcMove type2 meant consistent renaming, never aggregate Type-2."""
    return "type2c" if kind == "type2" else kind


def expected_category(metadata: Mapping[str, Any]) -> str:
    version = metadata.get("category_rules_version")
    if version is None:
        # Frozen artifacts retain their original oracle; do not infer membership.
        return {1: "type1", 2: "type2", 3: "type3"}[metadata["syntactic_type"]]
    if version != CATEGORY_RULES_VERSION:
        raise ValueError(f"unsupported category rules version: {version}")
    category = metadata.get("benchmark_category")
    if category not in CATEGORIES:
        raise ValueError("missing or invalid derived benchmark_category")
    if metadata.get("syntactic_type") != {"type1": 1, "type2c": 2, "type2b": 3, "type3": 3}[category]:
        raise ValueError("derived category conflicts with raw syntactic_type")
    return category


def category_metrics(*, selected: int, completed: int, eligible: int,
                     detected: int, agreed: int, reviewed_agreed: int,
                     reported: Mapping[str, int]) -> dict[str, Any]:
    def rate(n: int, d: int) -> float | None:
        return n / d if d else None
    return {
        "denominators": {"selected": selected, "completed": completed,
                         "srcdiff_eligible": eligible, "complete_detections": detected},
        "complete_detections": detected,
        "original_category_agreements": agreed,
        "reviewed_category_agreements": reviewed_agreed,
        "rates": {
            "complete_detection_over_selected": rate(detected, selected),
            "complete_detection_over_eligible": rate(detected, eligible),
            "original_agreement_over_selected": rate(agreed, selected),
            "original_agreement_over_complete_detections": rate(agreed, detected),
            "reviewed_agreement_over_selected": rate(reviewed_agreed, selected),
            "reviewed_agreement_over_complete_detections": rate(reviewed_agreed, detected),
        },
        "reported_categories_among_complete_detections": {
            kind: {"count": count, "rate": rate(count, detected)}
            for kind, count in sorted(reported.items())
        },
    }
