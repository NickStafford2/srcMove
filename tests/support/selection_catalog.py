"""Reviewed selection catalog validation and semantic expectations."""
from __future__ import annotations
import json
import re
from pathlib import Path
from typing import Any, Mapping

CATALOG_SCHEMA_VERSION = 3
RUN_SCHEMA_VERSION = 2
SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9_]*$")
ALLOWED_CONTENT_RELATIONSHIPS = {"type1", "type2c", "type3"}
ALLOWED_INPUT_SHAPES = {"single_file", "archive"}
ALLOWED_CASE_STATUSES = {"contract", "hypothesis"}


class CatalogError(ValueError):
    """The benchmark catalog cannot be interpreted safely."""


def normalize_text(value: str) -> str:
    """Compare raw source text while ignoring formatting-only whitespace."""

    return " ".join(value.split())


def _validate_expectation(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CatalogError(f"{context}: expectation must be an object")
    result = dict(value)
    for field in ("from", "to"):
        text = result.get(field)
        if not isinstance(text, str) or not normalize_text(text):
            raise CatalogError(f"{context}: {field} must be non-empty text")
    kinds = result.get("content_relationships")
    if kinds is not None:
        if (
            not isinstance(kinds, list)
            or not kinds
            or not all(isinstance(kind, str) and kind in ALLOWED_CONTENT_RELATIONSHIPS for kind in kinds)
        ):
            raise CatalogError(
                f"{context}: content_relationships must contain type1, type2c, or type3"
            )
    return result


def load_catalog(path: Path) -> list[dict[str, Any]]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CatalogError(f"cannot read catalog {path}: {error}") from error
    if not isinstance(document, dict) or document.get("schema_version") != CATALOG_SCHEMA_VERSION:
        raise CatalogError("catalog schema_version must be 3")
    raw_cases = document.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise CatalogError("catalog cases must be a non-empty array")

    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ordinal, value in enumerate(raw_cases, start=1):
        context = f"case {ordinal}"
        if not isinstance(value, dict):
            raise CatalogError(f"{context}: case must be an object")
        case_id = value.get("id")
        if not isinstance(case_id, str) or SAFE_ID.fullmatch(case_id) is None:
            raise CatalogError(f"{context}: id must use lowercase letters, digits, and underscores")
        if case_id in seen:
            raise CatalogError(f"duplicate case id: {case_id}")
        seen.add(case_id)
        status = value.get("status")
        if status not in ALLOWED_CASE_STATUSES:
            raise CatalogError(
                f"{case_id}: status must be contract or hypothesis"
            )
        raw_input = value.get("input")
        if not isinstance(raw_input, str) or not raw_input:
            raise CatalogError(f"{case_id}: input must be a relative path")
        relative_input = Path(raw_input)
        if relative_input.is_absolute() or ".." in relative_input.parts:
            raise CatalogError(f"{case_id}: input path is unsafe: {raw_input!r}")
        input_path = (path.parent / relative_input).resolve()
        try:
            input_path.relative_to(path.parent.resolve())
        except ValueError as error:
            raise CatalogError(f"{case_id}: resolved input escapes the catalog directory") from error
        if not input_path.is_file():
            raise CatalogError(f"{case_id}: input does not exist: {input_path}")
        required = value.get("required", [])
        forbidden = value.get("forbidden", [])
        if not isinstance(required, list) or not isinstance(forbidden, list):
            raise CatalogError(f"{case_id}: required and forbidden must be arrays")
        input_shape = value.get("input_shape", "single_file")
        if input_shape not in ALLOWED_INPUT_SHAPES:
            raise CatalogError(
                f"{case_id}: input_shape must be single_file or archive"
            )
        verify_results_only = value.get("verify_results_only_equivalence", False)
        if not isinstance(verify_results_only, bool):
            raise CatalogError(
                f"{case_id}: verify_results_only_equivalence must be boolean"
            )
        cases.append(
            {
                **value,
                "status": status,
                "input_path": input_path,
                "input_shape": input_shape,
                "verify_results_only_equivalence": verify_results_only,
                "required": [
                    _validate_expectation(item, f"{case_id}.required[{index}]")
                    for index, item in enumerate(required)
                ],
                "forbidden": [
                    _validate_expectation(item, f"{case_id}.forbidden[{index}]")
                    for index, item in enumerate(forbidden)
                ],
            }
        )
    return cases


def _result_moves(results: Mapping[str, Any]) -> list[dict[str, Any]]:
    moves = results.get("moves")
    if not isinstance(moves, list):
        raise ValueError("results.moves must be an array")
    parsed = []
    for ordinal, move in enumerate(moves, start=1):
        if not isinstance(move, dict):
            raise ValueError(f"results move {ordinal} must be an object")
        from_texts = move.get("from_raw_texts")
        to_texts = move.get("to_raw_texts")
        kind = move.get("content_relationship")
        if (
            not isinstance(from_texts, list)
            or not all(isinstance(text, str) for text in from_texts)
            or not isinstance(to_texts, list)
            or not all(isinstance(text, str) for text in to_texts)
            or kind not in ALLOWED_CONTENT_RELATIONSHIPS
        ):
            raise ValueError(f"results move {ordinal} has an invalid shape")
        parsed.append(move)
    return parsed


def expectation_matches(expectation: Mapping[str, Any], move: Mapping[str, Any]) -> bool:
    allowed = expectation.get("content_relationships")
    if allowed is not None and move.get("content_relationship") not in allowed:
        return False
    wanted_from = normalize_text(str(expectation["from"]))
    wanted_to = normalize_text(str(expectation["to"]))
    actual_from = {normalize_text(text) for text in move["from_raw_texts"]}
    actual_to = {normalize_text(text) for text in move["to_raw_texts"]}
    return wanted_from in actual_from and wanted_to in actual_to


def evaluate_results(case: Mapping[str, Any], results: Mapping[str, Any]) -> dict[str, Any]:
    moves = _result_moves(results)
    required = list(case.get("required", []))
    forbidden = list(case.get("forbidden", []))
    required_hits = [any(expectation_matches(item, move) for move in moves) for item in required]
    forbidden_hits = [any(expectation_matches(item, move) for move in moves) for item in forbidden]
    missing = [index for index, hit in enumerate(required_hits) if not hit]
    violations = [index for index, hit in enumerate(forbidden_hits) if hit]
    status = "pass" if not missing and not violations else "semantic_miss"
    return {
        "status": status,
        "required_total": len(required),
        "required_found": sum(required_hits),
        "forbidden_total": len(forbidden),
        "forbidden_found": sum(forbidden_hits),
        "missing_required_indexes": missing,
        "forbidden_violation_indexes": violations,
        "move_count": results.get("move_count"),
        "candidate_count": results.get("candidates_total"),
        "group_count": results.get("groups_total"),
    }



# The same callback is loaded by correctness and every comparison variant.
import unittest
from benchmarking.results import validate_results_schema
from benchmarking.srcdiff_validation import validate_srcdiff_xml
from tests.support.execution import execute_xml


class SelectionCatalogTest(unittest.TestCase):
    def __init__(self, case):
        super().__init__('runTest')
        self.case = case

    def id(self):
        return 'fixtures.selection.' + self.case['id']

    def __str__(self):
        return self.id()

    def runTest(self):
        case = self.case
        modes = ('ordinary', 'results_only') if case['verify_results_only_equivalence'] else ('ordinary',)
        observation = execute_xml(case['input_path'].read_bytes(), case_id=self.id(), min_granularity='statement', modes=modes)
        payloads = []
        for mode in observation.modes:
            if mode.completed.returncode != 0:
                raise RuntimeError(f'srcMove execution failed; artifacts: {observation.directory}\n{mode.completed.stderr}')
            payload = mode.payload()
            failures = validate_results_schema(payload, require_xpaths=True)
            if failures:
                raise ValueError('; '.join(failures))
            if mode.output_xml is not None:
                check = validate_srcdiff_xml(mode.output_xml, case['input_shape'])
                if check['status'] != 'valid':
                    raise ValueError(str(check))
            payloads.append(payload)
        evaluation = evaluate_results(case, payloads[0])
        self.assertEqual(evaluation['status'], 'pass', f'{evaluation}\nartifacts: {observation.directory}')
        if len(payloads) > 1:
            ordinary = dict(payloads[1])
            ordinary.pop('diagnostics', None)
            self.assertEqual(payloads[0], ordinary)


def load_selection_tests():
    from tests.support.cases import TESTS_ROOT
    catalog = TESTS_ROOT / 'fixtures/selection/catalog.json'
    cases = load_catalog(catalog)
    if any(case['status'] != 'contract' for case in cases):
        raise ValueError('accepted fixture catalog contains an exploratory hypothesis')
    return unittest.TestSuite(SelectionCatalogTest(case) for case in cases)
