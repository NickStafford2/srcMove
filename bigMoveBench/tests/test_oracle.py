from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bigMoveBench.oracle import validate_case


class BigMoveBenchOracleTests(unittest.TestCase):
    def test_type_one_requires_exact_classification(self) -> None:
        self.assertEqual(self._validate_case(1, "exact"), [])

    def test_type_two_rejects_wrong_classification(self) -> None:
        failures = self._validate_case(2, "exact")
        self.assertTrue(any("expected 'type2'" in failure for failure in failures))

    def test_type_three_requires_type3_classification(self) -> None:
        self.assertEqual(self._validate_case(3, "type3"), [])
        failures = self._validate_case(3, "type2")
        self.assertTrue(any("expected 'type3'" in failure for failure in failures))

    def _validate_case(self, syntactic_type: int, match_kind: str) -> list[str]:
        with tempfile.TemporaryDirectory() as temporary_directory:
            case_dir = Path(temporary_directory)
            metadata = {
                "syntactic_type": syntactic_type,
                "expected": {
                    "from_raw_text": "void moved() {}",
                    "to_raw_text": "void moved() {}",
                    "from_generated_text": "void moved() {}",
                    "to_generated_text": "void moved() {}",
                    "from_start_line": 3,
                    "from_end_line": 3,
                    "to_start_line": 7,
                    "to_end_line": 7,
                },
            }
            results = {
                "move_count": 1,
                "match_kinds": {match_kind: 1},
                "moves": [
                    {
                        "move_id": "m1",
                        "match_kind": match_kind,
                        "from_raw_texts": ["void moved() {}"],
                        "to_raw_texts": ["void moved() {}"],
                    }
                ],
            }
            (case_dir / "metadata.json").write_text(
                json.dumps(metadata), encoding="utf-8"
            )
            results_path = case_dir / "results.json"
            results_path.write_text(json.dumps(results), encoding="utf-8")
            srcmove_path = case_dir / "srcmove.xml"
            srcmove_path.write_text(
                "<unit xmlns:diff='urn:diff' xmlns:pos='urn:pos' "
                "xmlns:mv='http://www.srcML.org/srcMove'>"
                "<delete mv:id='m1' mv:to='target' pos:start='3:1|3:1' pos:end='3:9|3:9'/>"
                "<insert mv:id='m1' mv:from='source' pos:start='7:1|7:1' pos:end='7:9|7:9'/>"
                "</unit>",
                encoding="utf-8",
            )
            failures, _ = validate_case(
                case_dir, results_path, srcmove_path, syntactic_type
            )
            return failures


if __name__ == "__main__":
    unittest.main()
