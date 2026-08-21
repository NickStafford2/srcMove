from __future__ import annotations

import sys
import json
import tempfile
import unittest
from pathlib import Path


TESTS_ROOT = Path(__file__).resolve().parents[1]
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from support.cases import (
    CaseDefinitionError,
    discover_source_cases,
    discover_xml_cases,
    discover_policy_cases,
)


def touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    return path


class XmlCaseDiscoveryTests(unittest.TestCase):
    def test_complete_case_is_discovered(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            case_dir = root / "complete"
            touch(case_dir / "input.xml")
            touch(case_dir / "expected.json")
            touch(case_dir / "expected.xml")

            cases = discover_xml_cases(root)

            self.assertEqual([case.name for case in cases], ["complete"])
            self.assertEqual(cases[0].input_xml, case_dir / "input.xml")

    def test_incomplete_case_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            case_dir = root / "incomplete"
            touch(case_dir / "input.xml")

            with self.assertRaisesRegex(
                CaseDefinitionError, "missing expected.json, expected.xml"
            ):
                discover_xml_cases(root)


class SourceCaseDiscoveryTests(unittest.TestCase):
    def test_single_file_case_is_discovered(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            case_dir = root / "single"
            original = touch(case_dir / "original.cpp")
            modified = touch(case_dir / "modified.cpp")
            touch(case_dir / "oracle.json")

            cases = discover_source_cases(root)

            self.assertEqual(cases[0].original, original)
            self.assertEqual(cases[0].modified, modified)
            self.assertFalse(cases[0].is_archive)

    def test_archive_case_is_discovered(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            case_dir = root / "archive"
            (case_dir / "original").mkdir(parents=True)
            (case_dir / "modified").mkdir()
            touch(case_dir / "oracle.json")

            cases = discover_source_cases(root)

            self.assertTrue(cases[0].is_archive)
            self.assertEqual(cases[0].original, case_dir / "original")

    def test_malformed_case_is_rejected_instead_of_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            case_dir = root / "malformed"
            touch(case_dir / "original.cpp")
            touch(case_dir / "oracle.json")

            with self.assertRaisesRegex(
                CaseDefinitionError, "exactly one original.* and one modified.*"
            ):
                discover_source_cases(root)


class PolicyCaseDiscoveryTests(unittest.TestCase):
    def _write_contextual_catalogs(self, root: Path) -> None:
        negative = {
            "schema_version": 1,
            "cases": [
                {
                    "id": "context_negative",
                    "language": "C",
                    "extension": ".c",
                    "rationale": "context fixture",
                    "scenario": "transfer",
                    "from_lines": ["37"],
                    "to_lines": ["37"],
                }
            ],
        }
        positive_case = dict(negative["cases"][0])
        positive_case["id"] = "context_positive"
        positive_case.update(
            {
                "expected_match_kind": "exact",
                "expected_from_lines": ["37"],
                "expected_to_lines": ["37"],
            }
        )
        (root / "contextual_false_positive.json").write_text(json.dumps(negative))
        (root / "contextual_real_move.json").write_text(
            json.dumps({"schema_version": 1, "cases": [positive_case]})
        )

    def test_catalog_cases_are_discovered_and_classified(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            negative = {
                "schema_version": 1,
                "cases": [
                    {
                        "id": "literal_fragment",
                        "language": "C",
                        "extension": ".c",
                        "rationale": "not a complete statement",
                        "scenario": "transfer",
                        "from_lines": ["37"],
                        "to_lines": ["37"],
                    }
                ],
            }
            positive = {
                "schema_version": 1,
                "cases": [
                    {
                        "id": "function_move",
                        "language": "C",
                        "extension": ".c",
                        "rationale": "complete function",
                        "scenario": "transfer",
                        "from_lines": ["void moved(void) {}"],
                        "to_lines": ["void moved(void) {}"],
                        "expected_match_kind": "exact",
                        "expected_from_lines": ["void moved(void) {}"],
                        "expected_to_lines": ["void moved(void) {}"],
                    }
                ],
            }
            (root / "false_positive.json").write_text(json.dumps(negative))
            (root / "real_move.json").write_text(json.dumps(positive))
            self._write_contextual_catalogs(root)

            cases = discover_policy_cases(root)

            self.assertEqual(
                [case.name for case in cases],
                [
                    "literal_fragment",
                    "function_move",
                    "context_negative",
                    "context_positive",
                ],
            )
            self.assertFalse(cases[0].expect_move)
            self.assertTrue(cases[1].expect_move)

    def test_duplicate_ids_across_catalogs_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            shared = {
                "id": "duplicate",
                "language": "C",
                "extension": ".c",
                "rationale": "duplicate fixture",
                "scenario": "transfer",
                "from_lines": ["void moved(void) {}"],
                "to_lines": ["void moved(void) {}"],
            }
            (root / "false_positive.json").write_text(
                json.dumps({"schema_version": 1, "cases": [shared]})
            )
            positive = dict(shared)
            positive.update(
                {
                    "expected_match_kind": "exact",
                    "expected_from_lines": ["void moved(void) {}"],
                    "expected_to_lines": ["void moved(void) {}"],
                }
            )
            (root / "real_move.json").write_text(
                json.dumps({"schema_version": 1, "cases": [positive]})
            )
            self._write_contextual_catalogs(root)

            with self.assertRaisesRegex(CaseDefinitionError, "duplicate policy"):
                discover_policy_cases(root)


if __name__ == "__main__":
    unittest.main()
