from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = REPO_ROOT / "tests" / "regression" / "xml" / "run.py"
SPEC = importlib.util.spec_from_file_location("srcmove_xml_runner", RUNNER_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"could not load XML regression runner: {RUNNER_PATH}")
XML_RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(XML_RUNNER)


class XmlFixtureValidationTests(unittest.TestCase):
    def test_complete_case_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            case_dir = Path(temp_name) / "complete"
            case_dir.mkdir()
            for filename in XML_RUNNER.REQUIRED_CASE_FILES:
                (case_dir / filename).touch()

            self.assertEqual(XML_RUNNER.find_invalid_cases([case_dir]), [])

    def test_missing_files_make_case_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            case_dir = Path(temp_name) / "incomplete"
            case_dir.mkdir()
            (case_dir / "input.xml").touch()

            self.assertEqual(
                XML_RUNNER.find_invalid_cases([case_dir]),
                [(case_dir, ["expected.json", "expected.xml"])],
            )


if __name__ == "__main__":
    unittest.main()
