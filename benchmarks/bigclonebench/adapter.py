"""BigCloneBench adapter for the shared input snapshot and corpus pipeline."""

from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Mapping, Sequence

from benchmarks.bigclonebench.compiled import load_compiled_dataset
from benchmarks.bigclonebench.generate import (
    build_synthetic_move_sources,
    dedent_fragment,
    indent_fragment,
)
from benchmarks.bigclonebench.selection import (
    GENERATED_INPUT_IDENTITY_VERSION,
    load_selection,
)
from benchmarks.contracts import (
    InputPair,
    MaterializedInputPair,
    SemanticResult,
    SemanticStatus,
    content_identifier,
)
from benchmarks.provenance import sha256_file


SEMANTIC_ORACLE_VERSION = 1
SYNTHETIC_WRAPPER_VERSION = 1
SRCDIFF_NAMESPACES = {
    "http://www.srcML.org/srcDiff",
    "http://www.srcML.org/srcDiff/diff",
}


def _fragment_relation(fragment_one: str, fragment_two: str) -> dict[str, bool]:
    return {
        "raw_text_identical": fragment_one == fragment_two,
        "trimmed_text_identical": fragment_one.strip() == fragment_two.strip(),
    }


def _file_identity(path: Path, contents: bytes) -> dict[str, Any]:
    return {
        "kind": "directory",
        "files": [
            {
                "path": path.name,
                "size_bytes": len(contents),
                "sha256": hashlib.sha256(contents).hexdigest(),
            }
        ],
        "excluded": [],
    }


def _safe_fragment_sha256(value: Any) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError("selection frame contains an invalid fragment SHA-256")
    return value


def compiled_selection_source_manifest(
    selection_manifest: Mapping[str, Any], selection_directory: Path
) -> dict[str, Any]:
    """Build the snapshot dependency declaration without opening the catalog."""

    request = selection_manifest["request"]
    counts = selection_manifest["counts"]
    pair_set = request["pair_set"]
    case_kind = (
        "known_false_positive"
        if pair_set == "known-false-positive"
        else "positive"
    )
    return {
        "dataset": "BigCloneBench",
        "compiled_dataset_id": request["compiled_dataset_id"],
        "compiled_manifest_sha256": selection_manifest["compiled_dataset"][
            "manifest_sha256"
        ],
        "selection_id": selection_manifest["selection_id"],
        "selection_manifest_sha256": sha256_file(
            selection_directory / "manifest.json"
        ),
        "pair_set": pair_set,
        "synthetic_wrapper_version": SYNTHETIC_WRAPPER_VERSION,
        "selection": {
            "clone_type": (
                "known_false_positive"
                if case_kind == "known_false_positive"
                else pair_set
            ),
            "case_kind": case_kind,
            "dedupe": request["dedupe"],
            "text_change": "any",
            "min_tokens": None,
            "min_judges": None,
            "min_confidence": None,
            "row_count_before_deduplication": counts["eligible_source_rows"],
            "distinct_raw_text_pair_count": counts["eligible_frames"],
            "functionality_group_count": None,
            "selection": {
                "id": selection_manifest["selection_id"],
                "role": request["role"],
                "method": request["mode"],
                "seed": (
                    request["sample"]["seed"]
                    if isinstance(request.get("sample"), Mapping)
                    else None
                ),
            },
        },
    }


class CompiledBigCloneBenchAdapter:
    """Materialize Phase 2 selections directly from the compiled fragment store."""

    name = "bigclonebench"
    version = 4

    def __init__(
        self,
        *,
        data_root: Path,
        selection: str | Path,
    ) -> None:
        self.data_root = data_root.expanduser().resolve()
        supplied = Path(selection)
        if supplied.is_absolute() or supplied.exists():
            selection_directory = supplied.expanduser().resolve()
        else:
            selection_directory = (
                self.data_root / "bigclonebench" / "selections" / str(selection)
            )
        self.selection_manifest = load_selection(
            selection_directory, verification="identity"
        )
        self.selection_directory = selection_directory

        request = self.selection_manifest["request"]
        pair_set = request.get("pair_set")
        if pair_set not in {"type1", "type2", "known-false-positive"}:
            raise ValueError(
                "compiled snapshot materialization supports only Type 1, "
                "Type 2, and known-false-positive selections"
            )
        self.pair_set = str(pair_set)
        self.case_kind = (
            "known_false_positive"
            if pair_set == "known-false-positive"
            else "positive"
        )
        self.syntactic_type = (
            None
            if self.case_kind == "known_false_positive"
            else int(str(pair_set).removeprefix("type"))
        )
        self.compiled = load_compiled_dataset(
            request["compiled_dataset_id"],
            data_root=self.data_root,
            verification="identity",
        )
        compiled_declaration = self.selection_manifest.get("compiled_dataset", {})
        if (
            compiled_declaration.get("manifest_sha256")
            != self.compiled.manifest_sha256
            or compiled_declaration.get("catalog_sha256")
            != self.compiled.manifest["artifacts"]["catalog"]["sha256"]
        ):
            raise ValueError("selection compiled-dataset checksums do not match")

    def _fragment(self, fragment_sha256: str) -> str:
        fragment_sha256 = _safe_fragment_sha256(fragment_sha256)
        path = (
            self.compiled.directory
            / "fragments"
            / fragment_sha256[:2]
            / f"{fragment_sha256}.java"
        )
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"compiled fragment is unavailable: {fragment_sha256}")
        contents = path.read_bytes()
        if hashlib.sha256(contents).hexdigest() != fragment_sha256:
            raise ValueError(f"compiled fragment checksum mismatch: {fragment_sha256}")
        return contents.decode("utf-8")

    def _frames(self) -> list[Mapping[str, Any]]:
        artifact = self.selection_manifest["artifacts"]["frames"]
        path = self.selection_directory / artifact["path"]
        frames: list[Mapping[str, Any]] = []
        with path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                try:
                    frame = json.loads(line)
                except json.JSONDecodeError as error:
                    raise ValueError(
                        f"invalid selection frame at line {line_number}: {error}"
                    ) from error
                if not isinstance(frame, dict):
                    raise ValueError(
                        f"invalid selection frame at line {line_number}: expected object"
                    )
                frames.append(frame)
        expected_count = self.selection_manifest["counts"]["selected_frames"]
        if len(frames) != expected_count:
            raise ValueError(
                "selection frame count does not match manifest: "
                f"{len(frames)} observed, {expected_count} declared"
            )
        return frames

    @staticmethod
    def _case_id(frame: Mapping[str, Any]) -> str:
        generated_input_id = frame.get("generated_input_id")
        if not isinstance(generated_input_id, str):
            raise ValueError("selection frame is missing generated_input_id")
        return generated_input_id

    def _materialize_frame(
        self, frame: Mapping[str, Any], case_root: Path
    ) -> MaterializedInputPair:
        direction = frame.get("direction")
        if not isinstance(direction, Mapping):
            raise ValueError("selection frame is missing direction metadata")
        original_sha = _safe_fragment_sha256(
            direction.get("original_fragment_sha256")
        )
        modified_sha = _safe_fragment_sha256(
            direction.get("modified_fragment_sha256")
        )
        expected_generated_id = content_identifier(
            "bcb-generated-input",
            {
                "version": GENERATED_INPUT_IDENTITY_VERSION,
                "original_fragment_sha256": original_sha,
                "modified_fragment_sha256": modified_sha,
            },
        )
        if frame.get("generated_input_id") != expected_generated_id:
            raise ValueError("selection frame generated-input identity does not match")

        original_fragment = self._fragment(original_sha)
        modified_fragment = self._fragment(modified_sha)
        generated_original = indent_fragment(original_fragment)
        generated_modified = dedent_fragment(modified_fragment)
        digest = expected_generated_id.rsplit("-", 1)[-1]
        original_source, modified_source, original_range, modified_range = (
            build_synthetic_move_sources(
                f"BCBMove{digest}", generated_original, generated_modified
            )
        )
        original_bytes = original_source.encode("utf-8")
        modified_bytes = modified_source.encode("utf-8")
        original_directory = case_root / "original"
        modified_directory = case_root / "modified"
        original_directory.mkdir(parents=True, exist_ok=False)
        modified_directory.mkdir(parents=True, exist_ok=False)
        original_path = original_directory / "original.java"
        modified_path = modified_directory / "modified.java"
        original_path.write_bytes(original_bytes)
        modified_path.write_bytes(modified_bytes)
        original_path.chmod(0o444)
        modified_path.chmod(0o444)

        rows = frame.get("rows")
        if not isinstance(rows, list) or not rows:
            raise ValueError("selection frame contains no contributing rows")
        expected_pair_kind = (
            "known_false_positive"
            if self.case_kind == "known_false_positive"
            else "positive"
        )
        if any(
            not isinstance(row, Mapping)
            or row.get("pair_kind") != expected_pair_kind
            or (
                self.syntactic_type is not None
                and row.get("syntactic_type") != self.syntactic_type
            )
            for row in rows
        ):
            raise ValueError("selection frame rows do not match the selected pair set")
        syntactic_types = sorted(
            {
                int(row["syntactic_type"])
                for row in rows
                if isinstance(row.get("syntactic_type"), int)
            }
        )
        representative_type = (
            self.syntactic_type
            if self.syntactic_type is not None
            else syntactic_types[0] if syntactic_types else None
        )
        min_tokens = [
            row.get("tokens", {}).get("min")
            for row in rows
            if isinstance(row.get("tokens"), Mapping)
            and isinstance(row.get("tokens", {}).get("min"), int)
        ]
        functionality_ids = frame.get("functionality_ids", [])
        function_ids = frame.get("function_ids", [])
        metadata = {
            "source": "BigCloneBench compiled selection",
            "case_kind": self.case_kind,
            "clone_type": (
                "known_false_positive"
                if self.case_kind == "known_false_positive"
                else f"type{self.syntactic_type}"
            ),
            "syntactic_type": representative_type,
            "syntactic_types": syntactic_types,
            "min_tokens": min(min_tokens) if min_tokens else None,
            "functionality_id": (
                functionality_ids[0]
                if isinstance(functionality_ids, list)
                and len(functionality_ids) == 1
                else None
            ),
            "function_id_one": (
                function_ids[0]
                if isinstance(function_ids, list) and function_ids
                else None
            ),
            "function_id_two": (
                function_ids[1]
                if isinstance(function_ids, list) and len(function_ids) > 1
                else None
            ),
            "compiled_dataset_id": self.compiled.dataset_id,
            "selection_id": self.selection_manifest["selection_id"],
            "frame_id": frame.get("frame_id"),
            "generated_input_id": expected_generated_id,
            "synthetic_wrapper_version": SYNTHETIC_WRAPPER_VERSION,
            "fragment_one": {
                "sha256": original_sha,
                "text": original_fragment,
            },
            "fragment_two": {
                "sha256": modified_sha,
                "text": modified_fragment,
            },
            "fragment_relation": _fragment_relation(
                original_fragment, modified_fragment
            ),
            "expected": {
                "move_count": (
                    0 if self.case_kind == "known_false_positive" else 1
                ),
                "from_raw_text": original_fragment,
                "to_raw_text": modified_fragment,
                "from_generated_text": generated_original,
                "to_generated_text": generated_modified,
                "from_start_line": original_range[0],
                "from_end_line": original_range[1],
                "to_start_line": modified_range[0],
                "to_end_line": modified_range[1],
            },
            "selection_frame": dict(frame),
        }
        return MaterializedInputPair(
            case_id=expected_generated_id,
            original=_file_identity(original_path, original_bytes),
            modified=_file_identity(modified_path, modified_bytes),
            metadata=metadata,
        )

    def materialize_input_pairs(
        self, sources_root: Path, excluded_suffixes: Sequence[str]
    ) -> Sequence[MaterializedInputPair]:
        if ".java" in excluded_suffixes:
            raise ValueError("BigCloneBench Java inputs cannot be excluded")
        materialized: list[MaterializedInputPair] = []
        seen_case_ids: set[str] = set()
        for frame in self._frames():
            case_id = self._case_id(frame)
            if case_id in seen_case_ids:
                raise ValueError(f"duplicate generated input in selection: {case_id}")
            seen_case_ids.add(case_id)
            materialized.append(
                self._materialize_frame(frame, sources_root / case_id)
            )
        return materialized

    @staticmethod
    def validate_semantics(
        case: InputPair, srcdiff_xml: Path
    ) -> SemanticResult:
        return validate_srcdiff_semantics(case, srcdiff_xml)

    def source_manifest(self) -> dict[str, Any]:
        return compiled_selection_source_manifest(
            self.selection_manifest, self.selection_directory
        )


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
            value.get("schema_version") == 4
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
