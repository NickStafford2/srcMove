from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "benchmark"
BIGCLONEBENCH_RUNNER = REPO_ROOT / "benchmarks" / "bigclonebench" / "run.py"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.contracts import (
    CONTRACT_VERSION,
    ProvenanceStatus,
    RunMode,
    SemanticStatus,
    TerminationStatus,
    XmlStatus,
    canonical_json,
    content_identifier,
)


def load_bigclonebench_runner():
    spec = importlib.util.spec_from_file_location(
        "bigclonebench_oracle", BIGCLONEBENCH_RUNNER
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {BIGCLONEBENCH_RUNNER}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class BenchmarkContractTests(unittest.TestCase):
    def test_status_vocabulary_is_frozen_at_version_two(self) -> None:
        self.assertEqual(CONTRACT_VERSION, 2)
        self.assertEqual(
            [mode.value for mode in RunMode], ["development", "publication"]
        )
        self.assertEqual(
            [status.value for status in ProvenanceStatus],
            ["verified", "stale", "unverified", "unavailable"],
        )
        self.assertEqual(
            [status.value for status in TerminationStatus],
            [
                "exited",
                "signaled",
                "timed_out",
                "spawn_failed",
                "orchestration_interrupted",
            ],
        )
        self.assertEqual(
            [status.value for status in XmlStatus],
            [
                "valid",
                "missing",
                "empty",
                "malformed",
                "invalid_structure",
                "not_checked",
            ],
        )
        self.assertEqual(
            [status.value for status in SemanticStatus],
            ["eligible", "ineligible", "not_applicable", "not_checked"],
        )

    def test_canonical_identity_ignores_object_key_order(self) -> None:
        left = {"schema_version": 1, "cases": ["a", "b"], "scope": None}
        right = {"scope": None, "cases": ["a", "b"], "schema_version": 1}

        self.assertEqual(canonical_json(left), canonical_json(right))
        self.assertEqual(
            content_identifier("input-snapshot", left),
            content_identifier("input-snapshot", right),
        )

    def test_canonical_identity_preserves_array_order_and_content(self) -> None:
        baseline = {"schema_version": 1, "checksums": ["one", "two"]}
        reordered = {"schema_version": 1, "checksums": ["two", "one"]}
        changed = {"schema_version": 1, "checksums": ["one", "three"]}

        self.assertNotEqual(
            content_identifier("corpus", baseline),
            content_identifier("corpus", reordered),
        )
        self.assertNotEqual(
            content_identifier("corpus", baseline),
            content_identifier("corpus", changed),
        )

    def test_tiny_source_and_srcdiff_fixtures_are_checked_in(self) -> None:
        self.assertIn("int moved()", (FIXTURE_ROOT / "original.cpp").read_text())
        self.assertIn("int moved()", (FIXTURE_ROOT / "modified.cpp").read_text())
        self.assertIn("diff:delete", (FIXTURE_ROOT / "input.srcdiff.xml").read_text())

    def test_fake_tool_covers_success_nonzero_and_missing_output(self) -> None:
        fake_tool = FIXTURE_ROOT / "fake_tool.py"
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "output.xml"
            success = subprocess.run(
                [sys.executable, str(fake_tool), "success", "--output", str(output)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(success.returncode, 0)
            self.assertTrue(output.is_file())

            nonzero = subprocess.run(
                [sys.executable, str(fake_tool), "nonzero"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(nonzero.returncode, 23)

            missing_output = subprocess.run(
                [
                    sys.executable,
                    str(fake_tool),
                    "missing-output",
                    "--output",
                    str(Path(temporary_directory) / "missing.xml"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(missing_output.returncode, 0)
            self.assertFalse((Path(temporary_directory) / "missing.xml").exists())

    def test_bigclonebench_type_one_requires_exact_classification(self) -> None:
        runner = load_bigclonebench_runner()
        failures = self._validate_bigclonebench_case(runner, 1, "exact")
        self.assertEqual(failures, [])

    def test_bigclonebench_type_two_rejects_wrong_classification(self) -> None:
        runner = load_bigclonebench_runner()
        failures = self._validate_bigclonebench_case(runner, 2, "exact")
        self.assertTrue(any("expected 'type2'" in failure for failure in failures))

    def _validate_bigclonebench_case(
        self, runner, syntactic_type: int, match_kind: str
    ) -> list[str]:
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
                "<unit xmlns:diff='urn:diff' xmlns:pos='urn:pos'>"
                "<delete diff:id='1' diff:to='2' pos:start='3:1|3:1' pos:end='3:9|3:9'/>"
                "<insert diff:id='2' diff:from='1' pos:start='7:1|7:1' pos:end='7:9|7:9'/>"
                "</unit>",
                encoding="utf-8",
            )

            failures, _ = runner.validate_case(
                case_dir, results_path, srcmove_path, syntactic_type
            )
            return failures


if __name__ == "__main__":
    unittest.main()
