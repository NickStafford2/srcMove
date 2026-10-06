"""Canonical discovery and shape validation for accepted fixtures."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from pathlib import Path


TESTS_ROOT = Path(__file__).resolve().parents[1]
TEST_RESULTS_ROOT = TESTS_ROOT.parent / "build" / "test-results"
XML_CASES_ROOT = TESTS_ROOT / "fixtures" / "xml" / "cases"
SOURCE_CASES_ROOT = TESTS_ROOT / "fixtures" / "source"
POLICY_CASES_ROOT = TESTS_ROOT / "fixtures" / "policy"
FIXTURE_SUITES = ("xml", "source", "policy")
POLICY_CATALOGS = (
    ("false_positive.json", False, False),
    ("real_move.json", True, False),
    ("contextual_false_positive.json", False, True),
    ("contextual_real_move.json", True, True),
)
POLICY_CASE_ID = re.compile(r"^[a-z0-9][a-z0-9_]*$")


class CaseDefinitionError(ValueError):
    """A regression case directory does not follow its suite's fixture layout."""


@dataclass(frozen=True)
class XmlCaseSpec:
    name: str
    case_dir: Path
    input_xml: Path
    expected_json: Path
    expected_xml: Path


@dataclass(frozen=True)
class SourceCaseSpec:
    name: str
    case_dir: Path
    original: Path
    modified: Path
    oracle_json: Path
    is_archive: bool


@dataclass(frozen=True)
class PolicyCaseSpec:
    name: str
    catalog_path: Path
    language: str
    extension: str
    rationale: str
    scenario: str
    definition: dict[str, Any]
    expect_move: bool
    contextual: bool


def _case_directories(root: Path) -> list[Path]:
    if not root.is_dir():
        raise CaseDefinitionError(f"cases directory not found: {root}")

    return sorted(
        path
        for path in root.iterdir()
        if path.is_dir() and path.name != "__pycache__" and not path.name.startswith(".")
    )


def discover_xml_cases(root: Path = XML_CASES_ROOT) -> list[XmlCaseSpec]:
    cases: list[XmlCaseSpec] = []
    errors: list[str] = []

    for case_dir in _case_directories(root):
        required = {
            "input.xml": case_dir / "input.xml",
            "expected.json": case_dir / "expected.json",
            "expected.xml": case_dir / "expected.xml",
        }
        missing = [name for name, path in required.items() if not path.is_file()]
        if missing:
            errors.append(f"{case_dir.name}: missing {', '.join(missing)}")
            continue

        cases.append(
            XmlCaseSpec(
                name=case_dir.name,
                case_dir=case_dir,
                input_xml=required["input.xml"],
                expected_json=required["expected.json"],
                expected_xml=required["expected.xml"],
            )
        )

    if errors:
        raise CaseDefinitionError("invalid XML regression case(s):\n  " + "\n  ".join(errors))
    if not cases:
        raise CaseDefinitionError(f"no XML accepted fixtures found under {root}")
    return cases


def _single_file_pair(case_dir: Path) -> tuple[Path, Path]:
    originals = sorted(
        path for path in case_dir.iterdir() if path.is_file() and path.stem == "original"
    )
    modifieds = sorted(
        path for path in case_dir.iterdir() if path.is_file() and path.stem == "modified"
    )
    if len(originals) != 1 or len(modifieds) != 1:
        raise CaseDefinitionError(
            f"{case_dir.name}: expected exactly one original.* and one modified.* file, "
            "or original/ and modified/ directories"
        )
    return originals[0], modifieds[0]


def _source_case(case_dir: Path) -> SourceCaseSpec:
    original_dir = case_dir / "original"
    modified_dir = case_dir / "modified"
    has_original_dir = original_dir.is_dir()
    has_modified_dir = modified_dir.is_dir()

    if has_original_dir != has_modified_dir:
        raise CaseDefinitionError(
            f"{case_dir.name}: original/ and modified/ directories must both exist"
        )

    if has_original_dir:
        original = original_dir
        modified = modified_dir
        is_archive = True
    else:
        original, modified = _single_file_pair(case_dir)
        is_archive = False

    oracle_json = case_dir / "oracle.json"
    if not oracle_json.is_file():
        raise CaseDefinitionError(f"{case_dir.name}: missing oracle.json")

    return SourceCaseSpec(
        name=case_dir.name,
        case_dir=case_dir,
        original=original,
        modified=modified,
        oracle_json=oracle_json,
        is_archive=is_archive,
    )


def discover_source_cases(root: Path = SOURCE_CASES_ROOT) -> list[SourceCaseSpec]:
    cases: list[SourceCaseSpec] = []
    errors: list[str] = []

    for case_dir in _case_directories(root):
        try:
            cases.append(_source_case(case_dir))
        except CaseDefinitionError as error:
            errors.append(str(error))

    if errors:
        raise CaseDefinitionError(
            "invalid source regression case(s):\n  " + "\n  ".join(errors)
        )
    if not cases:
        raise CaseDefinitionError(f"no source accepted fixtures found under {root}")
    return cases


def _require_string(value: dict[str, Any], field: str, context: str) -> str:
    item = value.get(field)
    if not isinstance(item, str) or not item.strip():
        raise CaseDefinitionError(f"{context}: {field} must be a non-empty string")
    return item


def _validate_lines(value: Any, field: str, context: str) -> None:
    if not isinstance(value, list) or not value or not all(
        isinstance(line, str) for line in value
    ):
        raise CaseDefinitionError(
            f"{context}: {field} must be a non-empty array of strings"
        )


def _validate_file_map(value: Any, field: str, context: str) -> None:
    if not isinstance(value, dict) or not value:
        raise CaseDefinitionError(f"{context}: {field} must be a non-empty object")
    for relative_name, lines in value.items():
        if (
            not isinstance(relative_name, str)
            or not relative_name
            or Path(relative_name).is_absolute()
            or ".." in Path(relative_name).parts
        ):
            raise CaseDefinitionError(
                f"{context}: {field} contains unsafe path {relative_name!r}"
            )
        _validate_lines(lines, f"{field}.{relative_name}", context)


def _readable_policy_definition(catalog: Path, reference: dict, expect_move: bool) -> dict:
    """Read the source files and explicit expectation belonging to one case."""
    relative = reference.get("case")
    if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise CaseDefinitionError(f"{catalog.name}: unsafe case reference {relative!r}")
    path = (catalog.parent / relative).resolve()
    if not path.is_relative_to(catalog.parent.resolve()):
        raise CaseDefinitionError(f"{catalog.name}: case reference escapes the catalog")
    try:
        case = json.loads(path.read_text())
        if not isinstance(case, dict) or case.get("id") != reference.get("id"):
            raise CaseDefinitionError(f"{path}: case id disagrees with its catalog")
        expectation = case["expect"]
        if type(expectation["move_count"]) is not int or expectation["move_count"] != int(expect_move):
            raise CaseDefinitionError(f"{path}: move count disagrees with the case family")

        def source_files(side):
            directory = path.parent / side
            if not directory.resolve().is_relative_to(path.parent):
                raise CaseDefinitionError(f"{path}: source directory escapes its case")
            files = {}
            for file in sorted(directory.rglob('*')):
                if not file.resolve().is_relative_to(directory.resolve()):
                    raise CaseDefinitionError(f"{path}: source file escapes its revision directory")
                if file.is_file():
                    files[str(file.relative_to(directory))] = file.read_text().splitlines()
            _validate_file_map(files, side, str(path))
            return files

        before, after = source_files("before"), source_files("after")
        definition = {"id": case["id"], "language": case["language"],
                      "extension": case["extension"], "scenario": case["scenario"],
                      "rationale": case["purpose"], "case_path": str(path)}
        if case["scenario"] == "transfer":
            if len(before) != 1 or len(after) != 1:
                raise CaseDefinitionError(f"{path}: a transfer needs one source file per side")
            definition.update(from_lines=next(iter(before.values())), to_lines=next(iter(after.values())))
        else:
            definition.update(original_files=before, modified_files=after)
        if expect_move:
            definition["expected_content_relationship"] = expectation["content_relationship"]
            for side in ("from", "to"):
                expected = expectation[side]
                if Path(expected).is_absolute() or ".." in Path(expected).parts:
                    raise CaseDefinitionError(f"{path}: unsafe expected source path")
                expected_path = (path.parent / expected).resolve()
                if not expected_path.is_relative_to(path.parent):
                    raise CaseDefinitionError(f"{path}: expected source file escapes its case")
                definition["expected_" + side + "_lines"] = expected_path.read_text().splitlines()
        return definition
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise CaseDefinitionError(f"invalid readable policy case {path}: {error}") from error


def _load_policy_catalog(
    path: Path, expect_move: bool, contextual: bool
) -> list[PolicyCaseSpec]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CaseDefinitionError(f"unreadable policy catalog {path}: {error}") from error

    if not isinstance(value, dict) or value.get("schema_version") not in (1, 2):
        raise CaseDefinitionError(f"{path.name}: schema_version must be 1 or 2")
    raw_cases = value.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise CaseDefinitionError(f"{path.name}: cases must be a non-empty array")

    cases: list[PolicyCaseSpec] = []
    for ordinal, raw_case in enumerate(raw_cases, start=1):
        context = f"{path.name} case {ordinal}"
        if not isinstance(raw_case, dict):
            raise CaseDefinitionError(f"{context}: case must be an object")
        if value["schema_version"] == 2:
            raw_case = _readable_policy_definition(path, raw_case, expect_move)
        name = _require_string(raw_case, "id", context)
        if POLICY_CASE_ID.fullmatch(name) is None:
            raise CaseDefinitionError(
                f"{context}: id must contain lowercase letters, digits, and underscores"
            )
        language = _require_string(raw_case, "language", context)
        extension = _require_string(raw_case, "extension", context)
        if not extension.startswith(".") or "/" in extension or "\\" in extension:
            raise CaseDefinitionError(f"{context}: invalid extension {extension!r}")
        rationale = _require_string(raw_case, "rationale", context)
        scenario = _require_string(raw_case, "scenario", context)

        if scenario == "transfer":
            _validate_lines(raw_case.get("from_lines"), "from_lines", context)
            _validate_lines(raw_case.get("to_lines"), "to_lines", context)
        elif scenario == "archive":
            _validate_file_map(raw_case.get("original_files"), "original_files", context)
            _validate_file_map(raw_case.get("modified_files"), "modified_files", context)
        else:
            raise CaseDefinitionError(
                f"{context}: scenario must be 'transfer' or 'archive'"
            )

        if expect_move:
            content_relationship = raw_case.get("expected_content_relationship")
            allowed_content_relationships = ("type1", "type2c", "type3")
            if content_relationship not in allowed_content_relationships:
                raise CaseDefinitionError(
                    f"{context}: expected_content_relationship must be one of "
                    + ", ".join(repr(kind) for kind in allowed_content_relationships)
                )
            _validate_lines(
                raw_case.get("expected_from_lines"), "expected_from_lines", context
            )
            _validate_lines(
                raw_case.get("expected_to_lines"), "expected_to_lines", context
            )

        cases.append(
            PolicyCaseSpec(
                name=name,
                catalog_path=path,
                language=language,
                extension=extension,
                rationale=rationale,
                scenario=scenario,
                definition=raw_case,
                expect_move=expect_move,
                contextual=contextual,
            )
        )
    return cases


def discover_policy_cases(root: Path = POLICY_CASES_ROOT) -> list[PolicyCaseSpec]:
    cases: list[PolicyCaseSpec] = []
    missing = [name for name, _, _ in POLICY_CATALOGS if not (root / name).is_file()]
    if missing:
        raise CaseDefinitionError(
            f"policy catalog directory missing {', '.join(missing)}: {root}"
        )
    for filename, expect_move, contextual in POLICY_CATALOGS:
        cases.extend(_load_policy_catalog(root / filename, expect_move, contextual))

    names: set[str] = set()
    duplicates: list[str] = []
    for case in cases:
        if case.name in names:
            duplicates.append(case.name)
        names.add(case.name)
    if duplicates:
        raise CaseDefinitionError(
            "duplicate policy case id(s): " + ", ".join(sorted(set(duplicates)))
        )
    return cases


def fixture_case_names(suite: str) -> list[str]:
    if suite == "xml":
        return [case.name for case in discover_xml_cases()]
    if suite == "source":
        return [case.name for case in discover_source_cases()]
    if suite == "policy":
        return [case.name for case in discover_policy_cases()]
    raise ValueError(f"unknown regression suite: {suite}")
