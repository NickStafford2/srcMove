from __future__ import annotations
from tests.support.execution import require_success, require_tool

import json
import sys
from tests.support.execution import artifact_directory, run_logged
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarking.tooling import find_srcdiff, find_srcmove
from tests.support.shadow_contracts import (
    ShadowContractError,
    assert_shadow_expectation,
    evaluate_shadow_diagnostics,
    load_shadow_contracts,
    validate_srcdiff_precondition,
)


CATALOG = REPO_ROOT / "tests" / "fixtures" / "selection" / "shadow_contracts.json"
ADOPTED_OUTPUT_DISAGREEMENTS: dict[str, tuple[str, str]] = {}


class ShadowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = load_shadow_contracts(CATALOG)

    def test_catalog_owns_the_reviewed_phase_zero_matrix(self) -> None:
        indexed = {case["id"]: case for case in self.cases}
        self.assertEqual(len(indexed), 12)
        self.assertEqual(
            {case["expected_shadow"]["change_kind"] for case in self.cases},
            {"stationary", "relocated", "restructured", "ambiguous"},
        )
        self.assertEqual(
            {case["srcdiff_precondition"]["correspondence_kind"] for case in self.cases},
            {"type1"},
        )
        self.assertEqual(
            {case["expected_type1_output"] for case in self.cases},
            {"move", "not_move", "unchanged_group_policy"},
        )
        self.assertTrue(
            indexed["relocated_parent_carries_child"]["expected_shadow"]["carried_by_parent"]
        )
        self.assertEqual(
            indexed["incompatible_paths_without_reliable_wrapper_interpretation"]
            ["expected_shadow"],
            {"change_kind": "ambiguous", "classification_reason": "incompatible_context"},
        )

    def test_checked_in_srcdiff_fixtures_satisfy_their_preconditions(self) -> None:
        for case in self.cases:
            fixture = case["fixture"]
            if "srcdiff" not in fixture:
                continue
            with self.subTest(case=case["id"]):
                validate_srcdiff_precondition(case, fixture["srcdiff"])

    def test_source_generated_nodiscard_regression_satisfies_its_precondition(self) -> None:
        case = next(case for case in self.cases if "source_pair" in case["fixture"])
        srcdiff = find_srcdiff(REPO_ROOT, None)
        require_tool(srcdiff)
        pair = case["fixture"]["source_pair"]
        with artifact_directory(case_id=self.id()) as temporary_directory:
            output = Path(temporary_directory) / "srcdiff.xml"
            completed = run_logged(
                [
                    str(srcdiff),
                    str(pair["original"].parent),
                    str(pair["modified"].parent),
                    "-o",
                    str(output),
                ],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            require_success(completed)
            validate_srcdiff_precondition(case, output)

    def test_precondition_validation_rejects_an_upstream_alignment_change(self) -> None:
        case = next(case for case in self.cases if case["id"] == "missing_anchor_ambiguity")
        with artifact_directory(case_id=self.id()) as temporary_directory:
            fixture = Path(temporary_directory) / "common.xml"
            fixture.write_text(
                '<?xml version="1.0"?><unit xmlns="http://www.srcML.org/srcML/src" '
                'xmlns:diff="http://www.srcML.org/srcDiff">'
                '<expr_stmt>unanchored_work();</expr_stmt></unit>',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ShadowContractError, "precondition counts"):
                validate_srcdiff_precondition(case, fixture)

    def test_generated_shadow_diagnostics_match_supported_contracts(self) -> None:
        srcmove = find_srcmove(REPO_ROOT, None)
        srcdiff = find_srcdiff(REPO_ROOT, None)
        require_tool(srcmove)
        require_tool(srcdiff)
        known_gaps: dict[str, tuple[object, object, object]] = {}
        observed_gaps: dict[str, tuple[object, object, object]] = {}
        output_disagreements: dict[str, tuple[str, object]] = {}

        with artifact_directory(case_id=self.id()) as temporary_directory:
            temporary = Path(temporary_directory)
            for case in self.cases:
                with self.subTest(case=case["id"]):
                    fixture = case["fixture"]
                    if "srcdiff" in fixture:
                        srcdiff_input = fixture["srcdiff"]
                    else:
                        pair = fixture["source_pair"]
                        srcdiff_input = temporary / f"{case['id']}.xml"
                        generated = run_logged(
                            [
                                str(srcdiff),
                                str(pair["original"].parent),
                                str(pair["modified"].parent),
                                "-o",
                                str(srcdiff_input),
                            ],
                            cwd=REPO_ROOT,
                            text=True,
                            capture_output=True,
                            check=False,
                        )
                        require_success(generated)

                    output = temporary / f"{case['id']}.json"
                    completed = run_logged(
                        [
                            str(srcmove),
                            str(srcdiff_input),
                            "--results-only",
                            "--results",
                            str(output),
                            "--diagnostics",
                            "--min-granularity",
                            "fragment",
                        ],
                        cwd=REPO_ROOT,
                        text=True,
                        capture_output=True,
                        check=False,
                    )
                    require_success(completed)
                    actual = evaluate_shadow_diagnostics(
                        case, json.loads(output.read_text(encoding="utf-8"))
                    )
                    if case["id"] in known_gaps:
                        observed_gaps[case["id"]] = (
                            actual["change_kind"],
                            actual["classification_reason"],
                            actual["carried_by_parent"],
                        )
                    else:
                        assert_shadow_expectation(case, actual)

                    expected_output = case["expected_type1_output"]
                    if (
                        expected_output != "unchanged_group_policy"
                        and actual["current_result"] != expected_output
                    ):
                        output_disagreements[case["id"]] = (
                            expected_output,
                            actual["current_result"],
                        )

        self.assertEqual(observed_gaps, known_gaps)
        self.assertEqual(output_disagreements, ADOPTED_OUTPUT_DISAGREEMENTS)


if __name__ == "__main__":
    unittest.main()
