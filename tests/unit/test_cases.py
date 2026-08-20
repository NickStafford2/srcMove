from __future__ import annotations

import sys
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


if __name__ == "__main__":
    unittest.main()
