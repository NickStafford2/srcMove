from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bigMoveBench.evaluate import (
    _score_completed_case,
    _summarize_type3_strength,
)


class BigMoveBenchEvaluationTests(unittest.TestCase):
    def test_type_three_strength_summary_separates_detection_and_classification(self) -> None:
        rows = [
            {
                "clone_type": "type3",
                "type3_strength_stratum": "very_strong",
                "outcome": "oracle_pass",
            },
            {
                "clone_type": "type3",
                "type3_strength_stratum": "very_strong",
                "outcome": "wrong_classification",
            },
            {
                "clone_type": "type3",
                "type3_strength_stratum": "weak",
                "outcome": "srcmove_miss",
            },
        ]

        strata = _summarize_type3_strength(rows)

        self.assertEqual(list(strata), ["very_strong", "weak"])
        self.assertEqual(strata["very_strong"]["selected"], 2)
        self.assertEqual(strata["very_strong"]["detected"], 2)
        self.assertEqual(strata["very_strong"]["strictly_classified"], 1)
        self.assertEqual(strata["very_strong"]["detection_rate"], 1.0)
        self.assertEqual(
            strata["very_strong"]["strict_classification_rate"], 0.5
        )
        self.assertEqual(
            strata["very_strong"]["outcomes"]["wrong_classification"], 1
        )
        self.assertEqual(strata["weak"]["detection_rate"], 0.0)


    def test_type_two_scoring_requires_type2_match_kind(self) -> None:
        metadata = {
            "syntactic_type": 2,
            "expected": {
                "from_raw_text": "void moved() {}\n",
                "to_raw_text": "void moved() {}\n",
                "from_generated_text": "void moved() {}\n",
                "to_generated_text": "void moved() {}\n",
                "from_start_line": 3,
                "from_end_line": 3,
                "to_start_line": 5,
                "to_end_line": 5,
            },
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            srcmove_xml = root / "srcmove.xml"
            srcmove_xml.write_text(
                "<unit xmlns='http://www.srcML.org/srcML/src' "
                "xmlns:diff='http://www.srcML.org/srcDiff/diff' "
                "xmlns:mv='http://www.srcML.org/srcMove' "
                "xmlns:pos='http://www.srcML.org/srcML/position'>"
                "<diff:delete mv:id='m1' mv:to='target' "
                "pos:start='3:1|3:1' pos:end='3:10|3:10'/>"
                "<diff:insert mv:id='m1' mv:from='source' "
                "pos:start='5:1|5:1' pos:end='5:10|5:10'/>"
                "</unit>"
            )
            results_path = root / "results.json"
            for match_kind, expected_outcome in (
                ("exact", "wrong_classification"),
                ("type2", "oracle_pass"),
            ):
                results_path.write_text(
                    json.dumps(
                        {
                            "move_count": 1,
                            "match_kinds": {match_kind: 1},
                            "moves": [
                                {
                                    "move_id": "m1",
                                    "match_kind": match_kind,
                                    "from_raw_texts": ["void moved() {}\n"],
                                    "to_raw_texts": ["void moved() {}\n"],
                                }
                            ],
                        }
                    )
                )
                with self.subTest(match_kind=match_kind):
                    outcome, _, _, _ = _score_completed_case(
                        metadata=metadata,
                        results_path=results_path,
                        srcmove_xml=srcmove_xml,
                    )
                    self.assertEqual(outcome, expected_outcome)

    def test_type_three_scoring_requires_type3_match_kind(self) -> None:
        metadata = {
            "syntactic_type": 3,
            "expected": {
                "from_raw_text": "void before() {}\n",
                "to_raw_text": "void after() {}\n",
                "from_generated_text": "void before() {}\n",
                "to_generated_text": "void after() {}\n",
                "from_start_line": 3,
                "from_end_line": 3,
                "to_start_line": 5,
                "to_end_line": 5,
            },
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            srcmove_xml = root / "srcmove.xml"
            srcmove_xml.write_text(
                "<unit xmlns='http://www.srcML.org/srcML/src' "
                "xmlns:diff='http://www.srcML.org/srcDiff/diff' "
                "xmlns:mv='http://www.srcML.org/srcMove' "
                "xmlns:pos='http://www.srcML.org/srcML/position'>"
                "<diff:delete mv:id='m1' mv:to='target' "
                "pos:start='3:1|3:1' pos:end='3:10|3:10'/>"
                "<diff:insert mv:id='m1' mv:from='source' "
                "pos:start='5:1|5:1' pos:end='5:10|5:10'/>"
                "</unit>"
            )
            results_path = root / "results.json"
            for match_kind, expected_outcome in (
                ("type2", "wrong_classification"),
                ("type3", "oracle_pass"),
            ):
                results_path.write_text(
                    json.dumps(
                        {
                            "move_count": 1,
                            "match_kinds": {match_kind: 1},
                            "moves": [
                                {
                                    "move_id": "m1",
                                    "match_kind": match_kind,
                                    "from_raw_texts": ["void before() {}\n"],
                                    "to_raw_texts": ["void after() {}\n"],
                                }
                            ],
                        }
                    )
                )
                with self.subTest(match_kind=match_kind):
                    outcome, _, _, _ = _score_completed_case(
                        metadata=metadata,
                        results_path=results_path,
                        srcmove_xml=srcmove_xml,
                    )
                    self.assertEqual(outcome, expected_outcome)

    def test_type_three_dual_oracle_correlates_text_and_positions_per_move(self) -> None:
        metadata = {
            "syntactic_type": 3,
            "expected": {
                "from_generated_text": "void before() {}\n",
                "to_generated_text": "void after() {}\n",
                "from_start_line": 3,
                "from_end_line": 3,
                "to_start_line": 7,
                "to_end_line": 7,
            },
        }

        def move(
            move_id: str,
            kind: str,
            from_text: str,
            to_text: str,
        ) -> dict[str, object]:
            return {
                "move_id": move_id,
                "match_kind": kind,
                "from_raw_texts": [from_text],
                "to_raw_texts": [to_text],
            }

        intended = move(
            "intended", "type3", "void before() {}\n", "void after() {}\n"
        )
        incidental = move("incidental", "exact", "child();", "child();")
        wrong_text = move("intended", "type3", "void wrong() {}", "void after() {}")
        xml = (
            "<unit xmlns:diff='urn:diff' xmlns:mv='http://www.srcML.org/srcMove' "
            "xmlns:pos='http://www.srcML.org/srcML/position'>"
            "<diff:delete mv:id='intended' mv:to='target' "
            "pos:start='{from_line}:1|{from_line}:1' pos:end='{from_line}:20|{from_line}:20'/>"
            "<diff:insert mv:id='intended' mv:from='source' "
            "pos:start='{to_line}:1|{to_line}:1' pos:end='{to_line}:20|{to_line}:20'/>"
            "<diff:delete mv:id='incidental' mv:to='target' "
            "pos:start='{other_from}:1|{other_from}:1' pos:end='{other_from}:20|{other_from}:20'/>"
            "<diff:insert mv:id='incidental' mv:from='source' "
            "pos:start='{other_to}:1|{other_to}:1' pos:end='{other_to}:20|{other_to}:20'/>"
            "</unit>"
        )
        cases = (
            (
                "intended plus incidental",
                [intended, incidental],
                xml.format(from_line=3, to_line=7, other_from=20, other_to=21),
                "oracle_pass",
            ),
            (
                "wrong text",
                [wrong_text],
                xml.format(from_line=3, to_line=7, other_from=20, other_to=21),
                "srcmove_miss",
            ),
            (
                "wrong position",
                [intended],
                xml.format(from_line=30, to_line=40, other_from=20, other_to=21),
                "srcmove_miss",
            ),
            (
                "other move owns expected position",
                [intended, incidental],
                xml.format(from_line=30, to_line=40, other_from=3, other_to=7),
                "srcmove_miss",
            ),
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            results_path = root / "results.json"
            srcmove_xml = root / "srcmove.xml"
            for label, moves, xml_text, expected_outcome in cases:
                counts: dict[str, int] = {}
                for observed in moves:
                    kind = str(observed["match_kind"])
                    counts[kind] = counts.get(kind, 0) + 1
                results_path.write_text(
                    json.dumps(
                        {
                            "move_count": len(moves),
                            "match_kinds": counts,
                            "moves": moves,
                        }
                    )
                )
                srcmove_xml.write_text(xml_text)
                with self.subTest(label=label):
                    outcome, _, _, _ = _score_completed_case(
                        metadata=metadata,
                        results_path=results_path,
                        srcmove_xml=srcmove_xml,
                    )
                    self.assertEqual(outcome, expected_outcome)

    def test_malformed_result_and_xml_are_oracle_failures(self) -> None:
        metadata = {
            "syntactic_type": 1,
            "expected": {
                "from_generated_text": "void moved() {}",
                "to_generated_text": "void moved() {}",
                "from_start_line": 3,
                "from_end_line": 3,
                "to_start_line": 7,
                "to_end_line": 7,
            },
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            results_path = root / "results.json"
            srcmove_xml = root / "srcmove.xml"
            srcmove_xml.write_text("<unit/>")
            results_path.write_text("not json")
            outcome, _, _, _ = _score_completed_case(
                metadata=metadata,
                results_path=results_path,
                srcmove_xml=srcmove_xml,
            )
            self.assertEqual(outcome, "oracle_failure")

            results_path.write_text(
                json.dumps(
                    {
                        "move_count": 1,
                        "match_kinds": {"exact": 1},
                        "moves": [
                            {
                                "match_kind": "exact",
                                "from_raw_texts": ["void moved() {}"],
                                "to_raw_texts": ["void moved() {}"],
                            }
                        ],
                    }
                )
            )
            outcome, failures, _, _ = _score_completed_case(
                metadata=metadata,
                results_path=results_path,
                srcmove_xml=srcmove_xml,
            )
            self.assertEqual(outcome, "oracle_failure")
            self.assertTrue(any("move_id" in failure for failure in failures))

            results_path.write_text(
                json.dumps({"move_count": 0, "match_kinds": {}, "moves": []})
            )
            srcmove_xml.write_text("<unit>")
            outcome, _, _, _ = _score_completed_case(
                metadata=metadata,
                results_path=results_path,
                srcmove_xml=srcmove_xml,
            )
            self.assertEqual(outcome, "oracle_failure")

    def test_known_false_positive_scoring_rejects_only_whole_fragment_move(self) -> None:
        metadata = {
            "case_kind": "known_false_positive",
            # Descriptive dataset taxonomy only; it is not a positive oracle.
            "syntactic_type": 2,
            "expected": {
                "from_generated_text": "void fromWhole() {\n  child();\n}\n",
                "to_generated_text": "void toWhole() {\n  child();\n}\n",
            },
        }
        cases = (
            (
                {"move_count": 0, "match_kinds": {}, "moves": []},
                "oracle_pass",
            ),
            (
                {
                    "move_count": 1,
                    "match_kinds": {"exact": 1},
                    "moves": [
                        {
                            "move_id": "child",
                            "match_kind": "exact",
                            "from_raw_texts": ["child();"],
                            "to_raw_texts": ["child();"],
                        }
                    ],
                },
                "oracle_pass",
            ),
            (
                {
                    "move_count": 2,
                    "match_kinds": {"exact": 1, "type3": 1},
                    "moves": [
                        {
                            "move_id": "whole",
                            "match_kind": "type3",
                            "from_raw_texts": ["void fromWhole() {\n  child();\n}\n"],
                            "to_raw_texts": ["void toWhole() {\n  child();\n}\n"],
                        },
                        {
                            "move_id": "child",
                            "match_kind": "exact",
                            "from_raw_texts": ["child();"],
                            "to_raw_texts": ["child();"],
                        },
                    ],
                },
                "srcmove_false_positive",
            ),
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            results_path = root / "results.json"
            srcmove_xml = root / "srcmove.xml"
            for results, expected_outcome in cases:
                results_path.write_text(json.dumps(results))
                if results["move_count"] == 0:
                    srcmove_xml.unlink(missing_ok=True)
                else:
                    srcmove_xml.write_text("<unit/>")
                with self.subTest(expected_outcome=expected_outcome, results=results):
                    outcome, _, _, _ = _score_completed_case(
                        metadata=metadata,
                        results_path=results_path,
                        srcmove_xml=srcmove_xml,
                    )
                    self.assertEqual(outcome, expected_outcome)


if __name__ == "__main__":
    unittest.main()
