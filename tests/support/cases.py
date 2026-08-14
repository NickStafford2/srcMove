"""Canonical discovery and shape validation for regression cases."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


TESTS_ROOT = Path(__file__).resolve().parents[1]
XML_CASES_ROOT = TESTS_ROOT / "regression" / "xml" / "cases"
SOURCE_CASES_ROOT = TESTS_ROOT / "regression" / "source"
REGRESSION_SUITES = ("xml", "source")


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
        raise CaseDefinitionError(f"no XML regression cases found under {root}")
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
        raise CaseDefinitionError(f"no source regression cases found under {root}")
    return cases


def regression_case_names(suite: str) -> list[str]:
    if suite == "xml":
        return [case.name for case in discover_xml_cases()]
    if suite == "source":
        return [case.name for case in discover_source_cases()]
    raise ValueError(f"unknown regression suite: {suite}")
