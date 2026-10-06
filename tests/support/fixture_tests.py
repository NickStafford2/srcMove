"""Accepted fixtures as individual correctness cases with explicit input adapters.

The source and policy oracles are independent of detector output. XML fixtures
also retain their exact annotated serialization snapshots. Selection comparisons
load this same suite instead of translating these expectations into another DSL.
"""
from __future__ import annotations

import json
import os
import shutil
import unittest
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from benchmarking.provenance import observe_file
from benchmarking.results import validate_results_schema
from benchmarking.tooling import find_srcdiff, find_srcmove, format_process_failure
from tests.support.execution import run_logged
from tests.support.cases import (
    TESTS_ROOT, TEST_RESULTS_ROOT, XmlCaseSpec, SourceCaseSpec, PolicyCaseSpec,
    discover_xml_cases, discover_source_cases, discover_policy_cases,
)
from tests.support.validation import (
    assert_no_inline_xmlns, compare_xml_files_exact, load_json, validate_results,
)

REPO_ROOT = TESTS_ROOT.parent
Fixture = XmlCaseSpec | SourceCaseSpec | PolicyCaseSpec


class FixtureExecutionError(RuntimeError):
    """A required tool or output failed before the independent oracle ran."""


@dataclass(frozen=True)
class FixtureObservation:
    input_xml: Path
    output_xml: Path
    results: dict[str, Any]
    results_only: dict[str, Any] | None
    artifacts: Path


def prepare_srcdiff_inputs(
    case: SourceCaseSpec, case_out_dir: Path
) -> tuple[str, str, Path | None]:
    if case.is_archive:
        return str(case.original), str(case.modified), None

    input_root = case_out_dir / "srcdiff-input"
    original_root = input_root / "original"
    modified_root = input_root / "modified"
    original_root.mkdir(parents=True)
    modified_root.mkdir(parents=True)

    logical_name = f"source{case.original.suffix}"
    shutil.copyfile(case.original, original_root / logical_name)
    shutil.copyfile(case.modified, modified_root / logical_name)
    return str(original_root), str(modified_root), None


def _text(lines: list[str]) -> str:
    return "\n".join(lines).strip()


def _write_lines(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def materialize_case(case: PolicyCaseSpec, case_dir: Path) -> tuple[Path, Path]:
    original = case_dir / "original"
    modified = case_dir / "modified"

    definition = case.definition
    if case.scenario == "transfer":
        _write_lines(
            original / f"source{case.extension}", definition["from_lines"]
        )
        _write_lines(
            modified / f"destination{case.extension}", definition["to_lines"]
        )
    else:
        for relative_name, lines in definition["original_files"].items():
            _write_lines(original / relative_name, lines)
        for relative_name, lines in definition["modified_files"].items():
            _write_lines(modified / relative_name, lines)
    return original, modified


def _normalized_texts(move: dict[str, Any], field: str) -> list[str]:
    values = move.get(field)
    if not isinstance(values, list):
        return []
    return [str(value).strip() for value in values]


def evaluate(case: PolicyCaseSpec, results: dict[str, Any]) -> tuple[bool, str]:
    moves = results.get("moves")
    if not isinstance(moves, list):
        return False, "results.json field 'moves' is not a list"

    if not case.expect_move:
        if moves:
            samples = []
            for move in moves[:3]:
                if isinstance(move, dict):
                    raw = _normalized_texts(move, "from_raw_texts")
                    samples.append(f"{move.get('content_relationship', '?')}:{raw!r}")
            return False, f"expected no moves; detected {len(moves)} ({', '.join(samples)})"
        return True, ""

    definition = case.definition
    expected_kind = definition["expected_content_relationship"]
    expected_from = _text(definition["expected_from_lines"])
    expected_to = _text(definition["expected_to_lines"])
    matches = []
    for move in moves:
        if not isinstance(move, dict) or move.get("content_relationship") != expected_kind:
            continue
        if expected_from not in _normalized_texts(move, "from_raw_texts"):
            continue
        if expected_to not in _normalized_texts(move, "to_raw_texts"):
            continue
        matches.append(move)

    if not matches:
        observed = [
            (
                move.get("content_relationship"),
                _normalized_texts(move, "from_raw_texts"),
                _normalized_texts(move, "to_raw_texts"),
            )
            for move in moves[:3]
            if isinstance(move, dict)
        ]
        return False, f"expected {expected_kind} target move not found; observed {observed!r}"
    if len(moves) != 1:
        return False, f"target move found, but expected exactly 1 move and detected {len(moves)}"
    return True, ""


def fixture_kind(case: Fixture) -> str:
    if isinstance(case, XmlCaseSpec):
        return "xml"
    if isinstance(case, SourceCaseSpec):
        return "source"
    return "policy"


def run_fixture(case: Fixture, srcmove: Path, artifacts: Path, srcdiff: Path | None = None) -> FixtureObservation:
    """Execute a fixture while retaining commands, logs, outputs and identities."""
    out_root = artifacts / fixture_kind(case)
    out_root.mkdir(parents=True, exist_ok=True)
    case_dir = out_root / f"{case.name}-{uuid.uuid4().hex[:12]}"
    case_dir.mkdir()
    granularity = "fragment" if isinstance(case, SourceCaseSpec) else "statement"
    commands: list[dict[str, Any]] = []
    provenance = {"srcmove": observe_file(srcmove), "granularity": granularity,
                  "modes": ["normal", "results-only"] if isinstance(case, SourceCaseSpec) else ["normal"]}
    if srcdiff is not None:
        provenance["srcdiff"] = observe_file(srcdiff)
    (case_dir / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")

    def execute(label: str, command: list[str]) -> None:
        result = run_logged(command, artifacts=case_dir, cwd=REPO_ROOT, capture_output=True, text=True, check=False)
        (case_dir / f"{label}.stdout.txt").write_text(result.stdout or "")
        (case_dir / f"{label}.stderr.txt").write_text(result.stderr or "")
        commands.append({"stage": label, "argv": command, "cwd": str(REPO_ROOT), "returncode": result.returncode})
        (case_dir / "commands.json").write_text(json.dumps(commands, indent=2) + "\n")
        if result.returncode != 0:
            raise FixtureExecutionError(format_process_failure(label, result) + f"\nartifacts: {case_dir}")

    if isinstance(case, XmlCaseSpec):
        input_xml = case_dir / "input.xml"
        shutil.copyfile(case.input_xml, input_xml)
    else:
        if srcdiff is None:
            raise FixtureExecutionError(f"srcdiff is required for {fixture_kind(case)}.{case.name}")
        if isinstance(case, SourceCaseSpec):
            if case.is_archive:
                original, modified = case_dir / "original", case_dir / "modified"
                shutil.copytree(case.original, original)
                shutil.copytree(case.modified, modified)
            else:
                original, modified, _ = prepare_srcdiff_inputs(case, case_dir)
        else:
            original, modified = materialize_case(case, case_dir)
        input_xml = case_dir / "srcdiff.xml"
        execute("srcdiff", [str(srcdiff), str(original), str(modified), "-o", str(input_xml)])
        if not input_xml.is_file():
            raise FixtureExecutionError(f"srcdiff did not create {input_xml}")

    output_xml = case_dir / "srcmove.xml"
    results_path = case_dir / "results.json"
    execute("srcmove", [str(srcmove), str(input_xml), str(output_xml), "--results", str(results_path),
                        "--min-granularity", granularity])
    if not output_xml.is_file() or not results_path.is_file():
        raise FixtureExecutionError(f"srcMove output missing; artifacts: {case_dir}")

    def read_results(path: Path) -> dict[str, Any]:
        try:
            value = load_json(path)
        except (OSError, UnicodeError, ValueError) as error:
            raise FixtureExecutionError(f"invalid results {path}: {error}") from error
        failures = validate_results_schema(value, require_xpaths=True)
        if failures:
            raise FixtureExecutionError(f"invalid results {path}: " + "; ".join(failures))
        return value

    results = read_results(results_path)
    results_only = None
    if isinstance(case, SourceCaseSpec):
        results_only_path = case_dir / "results-only.json"
        execute("results-only", [str(srcmove), str(input_xml), "--results", str(results_only_path),
                                 "--results-only", "--min-granularity", granularity])
        results_only = read_results(results_only_path)
    return FixtureObservation(input_xml, output_xml, results, results_only, case_dir)


def fixture_failures(case: Fixture, observation: FixtureObservation) -> list[str]:
    """Apply the unchanged independent oracle appropriate to this representation."""
    results = observation.results
    if isinstance(case, PolicyCaseSpec):
        failures: list[str] = []
        ok, message = evaluate(case, results)
        if not ok:
            failures.append(message)
        return failures

    expected = load_json(case.expected_json if isinstance(case, XmlCaseSpec) else case.oracle_json)
    failures = validate_results(expected, results)
    failures.extend(assert_no_inline_xmlns(observation.output_xml))
    if isinstance(case, XmlCaseSpec):
        failures.extend(compare_xml_files_exact(case.expected_xml, observation.output_xml))
    else:
        ordinary = dict(results)
        ordinary.pop("diagnostics", None)
        ordinary_only = dict(observation.results_only or {})
        ordinary_only.pop("diagnostics", None)
        if ordinary != ordinary_only:
            failures.append("normal and --results-only ordinary JSON fields differ")
    return failures


class AcceptedFixtureTest(unittest.TestCase):
    def __init__(self, case: Fixture):
        super().__init__("runTest")
        self.case = case

    def id(self) -> str:
        return f"fixtures.{fixture_kind(self.case)}.{self.case.name}"

    def __str__(self) -> str:
        return self.id()

    def runTest(self) -> None:
        srcmove = find_srcmove(REPO_ROOT)
        if srcmove is None:
            raise FixtureExecutionError("srcMove executable is required")
        srcdiff = None if isinstance(self.case, XmlCaseSpec) else find_srcdiff(REPO_ROOT)
        root = Path(os.environ.get("SRCMOVE_TEST_ARTIFACTS", str(TEST_RESULTS_ROOT))) / "fixtures"
        observation = run_fixture(self.case, srcmove, root, srcdiff)
        failures = fixture_failures(self.case, observation)
        self.assertFalse(failures, "\n".join(failures) + f"\nartifacts: {observation.artifacts}")


def load_fixture_tests() -> unittest.TestSuite:
    cases = [*discover_xml_cases(), *discover_source_cases(), *discover_policy_cases()]
    return unittest.TestSuite(AcceptedFixtureTest(case) for case in cases)
