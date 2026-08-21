"""BigCloneBench adapter for the shared input snapshot and corpus pipeline."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Mapping, Sequence

from benchmarks.contracts import InputPair, SemanticResult, SemanticStatus


SEMANTIC_ORACLE_VERSION = 1
SRCDIFF_NAMESPACES = {
    "http://www.srcML.org/srcDiff",
    "http://www.srcML.org/srcDiff/diff",
}


def _local_name(value: str) -> str:
    return value.rsplit("}", 1)[-1].rsplit(":", 1)[-1]


def _attribute(node: ET.Element, name: str) -> str | None:
    for key, value in node.attrib.items():
        if _local_name(key) == name:
            return value
    return None


def _line(value: str, side: str) -> int | None:
    selected = value.split("|")[0 if side == "delete" else -1]
    try:
        return int(selected.split(":", 1)[0])
    except ValueError:
        return None


def _candidate_ranges(root: ET.Element, side: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for region in root.iter():
        namespace = (
            region.tag[1:].split("}", 1)[0]
            if region.tag.startswith("{")
            else ""
        )
        if _local_name(region.tag) != side or namespace not in SRCDIFF_NAMESPACES:
            continue
        lines: list[int] = []
        for node in region.iter():
            for attribute_name in ("start", "end"):
                position = _attribute(node, attribute_name)
                if position is not None:
                    parsed = _line(position, side)
                    if parsed is not None:
                        lines.append(parsed)
        if lines:
            ranges.append((min(lines), max(lines)))
    return ranges


def _covers(candidate: tuple[int, int], expected: tuple[int, int]) -> bool:
    return candidate[0] <= expected[0] and candidate[1] >= expected[1]


def validate_srcdiff_semantics(
    case: InputPair, srcdiff_xml: Path
) -> SemanticResult:
    """Require delete and insert candidates covering both generated payloads."""

    expected = case.metadata.get("expected")
    if not isinstance(expected, Mapping):
        return SemanticResult(
            SemanticStatus.INELIGIBLE,
            {
                "reason": "missing_expected_ranges",
                "oracle_version": SEMANTIC_ORACLE_VERSION,
            },
        )
    try:
        deleted = (int(expected["from_start_line"]), int(expected["from_end_line"]))
        inserted = (int(expected["to_start_line"]), int(expected["to_end_line"]))
    except (KeyError, TypeError, ValueError):
        return SemanticResult(
            SemanticStatus.INELIGIBLE,
            {
                "reason": "invalid_expected_ranges",
                "oracle_version": SEMANTIC_ORACLE_VERSION,
            },
        )

    try:
        root = ET.parse(srcdiff_xml).getroot()
    except (OSError, ET.ParseError) as error:
        return SemanticResult(
            SemanticStatus.INELIGIBLE,
            {
                "reason": "xml_unavailable_after_structural_admission",
                "error": str(error),
                "oracle_version": SEMANTIC_ORACLE_VERSION,
            },
        )

    delete_ranges = _candidate_ranges(root, "delete")
    insert_ranges = _candidate_ranges(root, "insert")
    delete_exposed = any(_covers(candidate, deleted) for candidate in delete_ranges)
    insert_exposed = any(_covers(candidate, inserted) for candidate in insert_ranges)
    status = (
        SemanticStatus.ELIGIBLE
        if delete_exposed and insert_exposed
        else SemanticStatus.INELIGIBLE
    )
    return SemanticResult(
        status,
        {
            "oracle_version": SEMANTIC_ORACLE_VERSION,
            "reason": (
                "payload_exposed"
                if status is SemanticStatus.ELIGIBLE
                else "payload_not_exposed"
            ),
            "expected_delete_range": list(deleted),
            "expected_insert_range": list(inserted),
            "delete_candidate_ranges": [list(value) for value in delete_ranges],
            "insert_candidate_ranges": [list(value) for value in insert_ranges],
            "delete_exposed": delete_exposed,
            "insert_exposed": insert_exposed,
        },
    )


class BigCloneBenchAdapter:
    name = "bigclonebench"
    version = 2

    def __init__(self, cases_dir: Path, selection: int | str) -> None:
        self.cases_dir = cases_dir.expanduser().resolve()
        if selection == "known_false_positive":
            self.syntactic_type: int | None = None
            self.case_kind = "known_false_positive"
            manifest_name = "bcb_fp_manifest.json"
        elif isinstance(selection, int) and selection in (1, 2):
            self.syntactic_type = selection
            self.case_kind = "positive"
            manifest_name = f"bcb_t{selection}_manifest.json"
        else:
            raise ValueError(f"unsupported BigCloneBench selection: {selection!r}")
        manifest_path = self.cases_dir / manifest_name
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError(f"invalid generated selection manifest: {manifest_path}")
        self._validate_selection_manifest(value, manifest_path)
        self.selection_manifest = value

    def _validate_selection_manifest(
        self, value: Mapping[str, Any], manifest_path: Path
    ) -> None:
        cases = value.get("cases")
        selection = value.get("selection")
        versions = value.get("versions")
        selected_rows = (
            selection.get("ordered_selected_row_ids")
            if isinstance(selection, Mapping)
            else None
        )
        required_top_level = {
            "dataset_identity": Mapping,
            "dedupe": str,
            "text_change": str,
            "min_tokens": int,
            "row_count_before_deduplication": int,
            "distinct_raw_text_pair_count": int,
            "functionality_group_count": int,
            "selected_source_files": list,
        }
        query_parameters = (
            selection.get("query_parameters")
            if isinstance(selection, Mapping)
            else None
        )
        selection_kind_valid = (
            isinstance(query_parameters, Mapping)
            and query_parameters.get("source_table")
            == (
                "false_positives"
                if self.case_kind == "known_false_positive"
                else "clones"
            )
            and (
                self.case_kind != "known_false_positive"
                or (
                    isinstance(value.get("min_judges"), int)
                    and isinstance(value.get("min_confidence"), int)
                )
            )
        )
        valid = (
            value.get("schema_version") == 3
            and value.get("dataset") == "BigCloneBench"
            and value.get("case_kind") == self.case_kind
            and value.get("syntactic_type") == self.syntactic_type
            and value.get("clone_type")
            == (
                "known_false_positive"
                if self.case_kind == "known_false_positive"
                else f"type{self.syntactic_type}"
            )
            and isinstance(cases, list)
            and bool(cases)
            and all(isinstance(case_id, str) for case_id in cases)
            and len(cases) == len(set(cases))
            and value.get("selected_count") == len(cases)
            and all(
                isinstance(value.get(field), expected_type)
                for field, expected_type in required_top_level.items()
            )
            and isinstance(selection, Mapping)
            and all(
                field in selection
                for field in (
                    "role",
                    "method",
                    "population_claim",
                    "eligibility_query",
                    "query_parameters",
                    "pair_direction",
                    "ordered_selected_row_ids",
                )
            )
            and selection_kind_valid
            and isinstance(selected_rows, list)
            and len(selected_rows) == len(cases)
            and all(
                isinstance(row, list)
                and len(row) == 2
                and all(isinstance(identifier, int) for identifier in row)
                for row in selected_rows
            )
            and isinstance(versions, Mapping)
            and all(
                isinstance(versions.get(field), str)
                for field in (
                    "generator_sha256",
                    "scoring_oracle_sha256",
                    "semantic_oracle_sha256",
                )
            )
        )
        if not valid:
            raise ValueError(f"invalid generated selection manifest: {manifest_path}")

    def input_pairs(self) -> Sequence[InputPair]:
        cases: list[InputPair] = []
        selected_rows = self.selection_manifest["selection"][
            "ordered_selected_row_ids"
        ]
        for case_id, selected_row in zip(
            self.selection_manifest["cases"], selected_rows, strict=True
        ):
            if not isinstance(case_id, str):
                raise ValueError("selection manifest case ids must be strings")
            directory = self.cases_dir / case_id
            metadata = json.loads(
                (directory / "metadata.json").read_text(encoding="utf-8")
            )
            if not isinstance(metadata, dict):
                raise ValueError(f"invalid case metadata: {directory / 'metadata.json'}")
            if metadata.get("case_kind") != self.case_kind:
                raise ValueError(
                    f"case kind does not match selection manifest: {case_id}"
                )
            if self.syntactic_type is not None and metadata.get(
                "syntactic_type"
            ) != self.syntactic_type:
                raise ValueError(
                    f"case syntactic_type does not match selection manifest: {case_id}"
                )
            if self.case_kind == "known_false_positive":
                expected = metadata.get("expected")
                if not isinstance(metadata.get("syntactic_type"), int):
                    raise ValueError(
                        f"case syntactic_type is missing or invalid: {case_id}"
                    )
                if not isinstance(expected, Mapping) or expected.get("move_count") != 0:
                    raise ValueError(
                        f"case negative oracle does not match selection manifest: {case_id}"
                    )
            if [
                metadata.get("function_id_one"),
                metadata.get("function_id_two"),
            ] != selected_row:
                raise ValueError(
                    f"case row identity does not match selection manifest: {case_id}"
                )
            cases.append(
                InputPair(
                    case_id=case_id,
                    original=directory / "original.java",
                    modified=directory / "modified.java",
                    metadata=metadata,
                )
            )
        return cases

    @staticmethod
    def validate_semantics(
        case: InputPair, srcdiff_xml: Path
    ) -> SemanticResult:
        return validate_srcdiff_semantics(case, srcdiff_xml)

    def source_manifest(self) -> dict[str, Any]:
        """Return selection facts copied into the immutable input snapshot."""

        return {
            "dataset": "BigCloneBench",
            "selection": self.selection_manifest,
        }
