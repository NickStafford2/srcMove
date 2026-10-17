from __future__ import annotations

from tests.tooling.results_fixtures import schema3_fixture

import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bigMoveBench.evaluate import (
    _score_completed_case,
    diagnostic_stage,
    validate_results_output,
)


class BigMoveBenchEvaluationTests(unittest.TestCase):
    def test_diagnostic_stage_stays_within_observable_evidence(self) -> None:
        self.assertEqual(diagnostic_stage("oracle_pass", {}), "selected")
        self.assertEqual(
            diagnostic_stage("wrong_classification", {}), "classification"
        )
        self.assertEqual(
            diagnostic_stage("srcmove_false_positive", {}), "false_acceptance"
        )
        self.assertEqual(
            diagnostic_stage("srcmove_miss", schema3_fixture({"candidates_total": 1})),
            "candidate_generation",
        )
        self.assertEqual(
            diagnostic_stage(
                "srcmove_miss", schema3_fixture({"candidates_total": 2, "moves": []})
            ),
            "retrieval_or_verification",
        )
        self.assertEqual(
            diagnostic_stage(
                "srcmove_miss",
                schema3_fixture({"candidates_total": 2, "moves": [{"move_id": "m1", "from_raw_texts": ["x"], "to_raw_texts": ["x"]}]}),
            ),
            "selection_or_granularity",
        )

    def test_results_output_validation_rejects_bad_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "results.json"
            self.assertEqual(validate_results_output(path)["status"], "missing")
            for contents, status in (
                ("", "empty"),
                ("not json", "malformed"),
                ("[]", "malformed"),
                ("{}", "invalid_structure"),
                (
                    json.dumps(
                        schema3_fixture({"results_schema_version": 2, "move_count": 0, "content_relationships": {}, "moves": []})
                    ),
                    "valid",
                ),
            ):
                with self.subTest(status=status):
                    path.write_text(contents, encoding="utf-8")
                    self.assertEqual(
                        validate_results_output(path)["status"], status
                    )

    def test_results_only_scoring_resolves_positions_from_srcdiff(self) -> None:
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
        results = schema3_fixture({
            "results_schema_version": 2, "move_count": 1,
            "content_relationships": {"type1": 1},
            "moves": [
                {
                    "move_id": "m1",
                    "content_relationship": "type1",
                    "from_xpaths": [
                        "/src:unit[@filename='source/input.java']"
                        "/src:class[1]/src:block[1]/diff:delete[1]"
                        "/src:function[src:name='moved']"
                    ],
                    "to_xpaths": [
                        "/src:unit[@filename='destination/input.java']"
                        "/src:class[1]/src:block[1]/diff:insert[1]"
                        "/src:function[src:name='moved']"
                    ],
                    "from_raw_texts": ["void moved() {}"],
                    "to_raw_texts": ["void moved() {}"],
                }
            ],
        })
        srcdiff = (
            "<unit xmlns='http://www.srcML.org/srcML/src' "
            "xmlns:diff='http://www.srcML.org/srcDiff' "
            "xmlns:pos='http://www.srcML.org/srcML/position' url='old|new'>"
            "<unit filename='source/input.java'><class><block><diff:delete>"
            "<function pos:start='3:1' pos:end='3:20'><name>moved</name>"
            "</function></diff:delete></block></class></unit>"
            "<unit filename='destination/input.java'><class><block><diff:insert>"
            "<function pos:start='7:1' pos:end='7:20'><name>moved</name>"
            "</function></diff:insert></block></class></unit>"
            "</unit>"
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            results_path = root / "results.json"
            results_path.write_text(json.dumps(results), encoding="utf-8")
            srcdiff_path = root / "srcdiff.xml"
            srcdiff_path.write_text(srcdiff, encoding="utf-8")

            self.assertEqual(validate_results_output(results_path)["status"], "valid")
            outcome, failures, _, _ = _score_completed_case(
                metadata=metadata,
                results_path=results_path,
                srcdiff_xml=srcdiff_path,
            )
            self.assertEqual(outcome, "oracle_pass")
            self.assertEqual(failures, [])

            results["atomic_move_groups"][0]["original"][0]["xpath"] = "/src:unit[@filename='missing']"
            results_path.write_text(json.dumps(results), encoding="utf-8")
            outcome, failures, _, _ = _score_completed_case(
                metadata=metadata,
                results_path=results_path,
                srcdiff_xml=srcdiff_path,
            )
            self.assertEqual(outcome, "oracle_failure")
            self.assertTrue(any("resolve exactly once" in failure for failure in failures))

            srcdiff_path.write_text('<unit>', encoding='utf-8')
            outcome, failures, _, _ = _score_completed_case(
                metadata=metadata, results_path=results_path, srcdiff_xml=srcdiff_path)
            self.assertEqual(outcome, 'oracle_failure')
            self.assertTrue(any('srcdiff.xml position error' in failure for failure in failures))

    def test_sequence_reporting_keeps_atomic_scoring_and_detected_group_identity(self):
        value = schema3_fixture({'moves': [
            {'move_id': name, 'from_raw_texts': [text], 'to_raw_texts': [text],
             'from_xpaths': [f'/src:unit[1]/diff:delete[1]/src:expr_stmt[{ordinal}]'],
             'to_xpaths': [f'/src:unit[1]/diff:insert[1]/src:expr_stmt[{ordinal}]']}
            for ordinal, name, text in [(1, 'a', 'first();'), (2, 'b', 'second();')]]})
        for group in value['atomic_move_groups']:
            group['original'][0]['revision_file'] = 'old.cpp'
            group['modified'][0]['revision_file'] = 'new.cpp'
        value['output_items'] = [{'id': 'sequence:a', 'kind': 'sequence_move_group',
                                  'member_group_ids': ['a', 'b'],
                                  'sequence': {'policy': 'ordered_adjacent_v1', **{
                                      side: {'revision_file': file, 'parent_id': f'old.cpp|new.cpp:{side}:unit:0',
                                             'first_child_ordinal': 1, 'last_child_ordinal': 2}
                                      for side, file in [('original', 'old.cpp'), ('modified', 'new.cpp')]}}}]
        value['summary'].update(output_item_count=1, sequence_move_group_count=1,
                                output_content_relationships={'type1': 1, 'type2c': 0, 'type3': 0})
        xml = ('<unit xmlns="http://www.srcML.org/srcML/src" xmlns:diff="http://www.srcML.org/srcDiff" '
               'xmlns:pos="http://www.srcML.org/srcML/position" filename="old.cpp|new.cpp">'
               '<diff:delete><expr_stmt pos:start="2:1" pos:end="2:8">first();</expr_stmt>'
               '<expr_stmt pos:start="3:1" pos:end="3:9">second();</expr_stmt></diff:delete>'
               '<diff:insert><expr_stmt pos:start="5:1" pos:end="5:8">first();</expr_stmt>'
               '<expr_stmt pos:start="6:1" pos:end="6:9">second();</expr_stmt></diff:insert></unit>')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            results_path, input_path = root / 'results.json', root / 'srcdiff.xml'
            results_path.write_text(json.dumps(value))
            input_path.write_text(xml)
            self.assertEqual(validate_results_output(results_path)['status'], 'valid')
            for expected, outcome in [('first();second();', 'srcmove_miss'), ('first();', 'oracle_pass')]:
                metadata = {'syntactic_type': 1, 'expected': {
                    'from_generated_text': expected, 'to_generated_text': expected,
                    'from_start_line': 2, 'from_end_line': 3,
                    'to_start_line': 5, 'to_end_line': 6}}
                actual, _, _, receipt = _score_completed_case(metadata=metadata,
                    results_path=results_path, srcdiff_xml=input_path)
                self.assertEqual(actual, outcome)
                if actual == 'oracle_pass':
                    self.assertEqual(receipt['_oracle_detected_move_id'], 'a')

    def test_type_two_scoring_requires_type2_content_relationship(self) -> None:
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
            for content_relationship, expected_outcome in (
                ("type1", "wrong_classification"),
                ("type2c", "oracle_pass"),
            ):
                results_path.write_text(
                    json.dumps(
                        schema3_fixture({
                            "results_schema_version": 2, "move_count": 1,
                            "content_relationships": {content_relationship: 1},
                            "moves": [
                                {
                                    "move_id": "m1",
                                    "content_relationship": content_relationship,
                                    "from_raw_texts": ["void moved() {}\n"],
                                    "to_raw_texts": ["void moved() {}\n"],
                                }
                            ],
                        })
                    )
                )
                with self.subTest(content_relationship=content_relationship):
                    outcome, _, _, _ = _score_completed_case(
                        metadata=metadata,
                        results_path=results_path,
                        srcmove_xml=srcmove_xml,
                    )
                    self.assertEqual(outcome, expected_outcome)

    def test_type_three_scoring_requires_type3_content_relationship(self) -> None:
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
            for content_relationship, expected_outcome in (
                ("type2c", "wrong_classification"),
                ("type3", "oracle_pass"),
            ):
                results_path.write_text(
                    json.dumps(
                        schema3_fixture({
                            "results_schema_version": 2, "move_count": 1,
                            "content_relationships": {content_relationship: 1},
                            "moves": [
                                {
                                    "move_id": "m1",
                                    "content_relationship": content_relationship,
                                    "from_raw_texts": ["void before() {}\n"],
                                    "to_raw_texts": ["void after() {}\n"],
                                }
                            ],
                        })
                    )
                )
                with self.subTest(content_relationship=content_relationship):
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
                "content_relationship": kind,
                "from_raw_texts": [from_text],
                "to_raw_texts": [to_text],
            }

        intended = move(
            "intended", "type3", "void before() {}\n", "void after() {}\n"
        )
        incidental = move("incidental", "type1", "child();", "child();")
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
                    kind = str(observed["content_relationship"])
                    counts[kind] = counts.get(kind, 0) + 1
                results_path.write_text(
                    json.dumps(
                        schema3_fixture({
                            "results_schema_version": 2, "move_count": len(moves),
                            "content_relationships": counts,
                            "moves": moves,
                        })
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
                    schema3_fixture({
                        "results_schema_version": 2, "move_count": 1,
                        "content_relationships": {"type1": 1},
                        "moves": [
                            {
                                "move_id": None,
                                "content_relationship": "type1",
                                "from_raw_texts": ["void moved() {}"],
                                "to_raw_texts": ["void moved() {}"],
                            }
                        ],
                    })
                )
            )
            outcome, failures, _, _ = _score_completed_case(
                metadata=metadata,
                results_path=results_path,
                srcmove_xml=srcmove_xml,
            )
            self.assertEqual(outcome, "oracle_failure")
            self.assertTrue(failures, "invalid group identity must be rejected at admission")

            results_path.write_text(
                json.dumps(schema3_fixture({"results_schema_version": 2, "move_count": 0, "content_relationships": {}, "moves": []}))
            )
            srcmove_xml.write_text("<unit>")
            outcome, _, _, _ = _score_completed_case(
                metadata=metadata,
                results_path=results_path,
                srcmove_xml=srcmove_xml,
            )
            self.assertEqual(outcome, "oracle_failure")

    def test_malformed_nested_summary_is_an_admission_failure_for_both_oracles(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'results.json'
            for summary in (None, [], 'invalid', True, 1):
                malformed = {'results_schema_version': 3, 'summary': summary}
                path.write_text(json.dumps(malformed))
                for kind in ('positive', 'known_false_positive'):
                    with self.subTest(summary=summary, kind=kind):
                        metadata = {'case_kind': kind, 'syntactic_type': 1}
                        actual, failures, _, receipt = _score_completed_case(metadata=metadata, results_path=path)
                        self.assertEqual(actual, 'oracle_failure')
                        self.assertTrue(failures)
                        self.assertEqual({key: receipt[key] for key in malformed}, malformed)
                        if kind == 'positive':
                            self.assertFalse(receipt['_oracle_complete_detection'])

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
                schema3_fixture({"results_schema_version": 2, "move_count": 0, "content_relationships": {}, "moves": []}),
                "oracle_pass",
            ),
            (
                schema3_fixture({
                    "results_schema_version": 2, "move_count": 1,
                    "content_relationships": {"type1": 1},
                    "moves": [
                        {
                            "move_id": "child",
                            "content_relationship": "type1",
                            "from_raw_texts": ["child();"],
                            "to_raw_texts": ["child();"],
                        }
                    ],
                }),
                "oracle_pass",
            ),
            (
                schema3_fixture({
                    "results_schema_version": 2, "move_count": 2,
                    "content_relationships": {"type1": 1, "type3": 1},
                    "moves": [
                        {
                            "move_id": "whole",
                            "content_relationship": "type3",
                            "from_raw_texts": ["void fromWhole() {\n  child();\n}\n"],
                            "to_raw_texts": ["void toWhole() {\n  child();\n}\n"],
                        },
                        {
                            "move_id": "child",
                            "content_relationship": "type1",
                            "from_raw_texts": ["child();"],
                            "to_raw_texts": ["child();"],
                        },
                    ],
                }),
                "srcmove_false_positive",
            ),
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            results_path = root / "results.json"
            srcmove_xml = root / "srcmove.xml"
            for results, expected_outcome in cases:
                results_path.write_text(json.dumps(results))
                if results["summary"]["atomic_move_group_count"] == 0:
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
