"""Opt-in producer migration differential suite with frozen schema-2 evidence.

Enable through make test-results-schema after capturing the frozen v2 baseline.
Each case replays retained input bytes; no new semantic oracle is inferred from
schema-3 output. Frozen-binary baseline failures remain in its separate report.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest

from tests.support.results_v3 import (
    CONTRACT, REPO_ROOT, diagnostic_projection, load_module,
    ordinary_projection, sha256, validate_native_xml,
)

UNCLASSIFIED_WRAPPER_CASES = {
    "0fa49644acea563b-fragment",
    "c4b31a34a5fd4125-fragment",
    "d1fd9d32a6f5904b-fragment",
}


class ResultsSchemaV3Replay(unittest.TestCase):
    def __init__(self, case, baseline=None):
        super().__init__("runTest")
        self.case, self.baseline = case, baseline

    def id(self):
        return "tests.behavior.test_results_schema_v3.replay." + self.case["id"]

    def __str__(self):
        return self.id()

    @classmethod
    def setUpClass(cls):
        cls.checker = load_module("producer_schema3_check", CONTRACT / "check_examples.py")
        from jsonschema import Draft202012Validator
        cls.schema = Draft202012Validator(json.loads((CONTRACT / "schema.json").read_text()))
        cls.binary = Path(os.environ.get("SRCMOVE_BIN", REPO_ROOT / "build/srcMove")).resolve()
        if not cls.binary.is_file():
            raise RuntimeError("Current srcMove binary is required")
        cls.binary_hash = sha256(cls.binary)

    def runTest(self):
        case, baseline = self.case, self.baseline
        paths = {name: baseline / case[name] for name in ("input", "results", "xml")}
        for name, path in paths.items():
            self.assertEqual(sha256(path), case["sha256"][name], f"Frozen {name} hash changed")
        expected = json.loads(paths["results"].read_text())
        output_root = Path(os.environ.get("SRCMOVE_TEST_ARTIFACTS", REPO_ROOT / "build/schema3-phase3/replay"))
        output = output_root / "schema3-replay" / case["id"]
        output.mkdir(parents=True, exist_ok=True)
        input_path = output / "input.xml"
        shutil.copyfile(paths["input"], input_path)
        results = {}
        xml_paths = {}
        commands = []
        for mode, diagnostics, only in (
            ("ordinary", False, False), ("diagnostic", True, False),
            ("results_only", False, True), ("diagnostic_results_only", True, True),
        ):
            json_path, xml_path = output / (mode + ".json"), output / (mode + ".xml")
            argv = [str(self.binary), str(input_path)]
            if not only:
                argv.append(str(xml_path))
                xml_paths[mode] = xml_path
            argv += ["--results", str(json_path), "--min-granularity", case["granularity"]]
            if diagnostics:
                argv.append("--diagnostics")
            if only:
                argv.append("--results-only")
            completed = subprocess.run(argv, capture_output=True, text=True, timeout=120, check=False)
            (output / (mode + ".stdout.log")).write_text(completed.stdout)
            (output / (mode + ".stderr.log")).write_text(completed.stderr)
            commands.append({"argv": argv, "returncode": completed.returncode})
            (output / "execution.json").write_text(json.dumps({
                "purpose": "Schema serialization differential replay, not historical correctness evidence.",
                "baseline_case": case, "binary": str(self.binary),
                "binary_sha256": self.binary_hash, "source_binding": "unverified",
                "commands": commands,
            }, indent=2) + "\n")
            self.assertEqual(completed.returncode, 0, f"{mode} failed; see {output}\n{completed.stderr}")
            payload = json.loads(json_path.read_text())
            errors = sorted(self.schema.iter_errors(payload), key=lambda error: str(error.path))
            self.assertFalse(errors, "\n".join(f"{list(e.path)}: {e.message}" for e in errors[:6]))
            self.checker.validate(payload)
            self.assertEqual(payload["configuration"]["min_granularity"], case["granularity"])
            if case["id"] in UNCLASSIFIED_WRAPPER_CASES:
                # Existing fragment proposals trim to one wrapper per side
                # without retaining a classified pair. Report that absence;
                # serialization must not invent positive relocation evidence.
                self.assertEqual(len(payload["atomic_move_groups"]), 1)
                group = payload["atomic_move_groups"][0]
                self.assertEqual(group["correspondence"]["status"], "selected_pair")
                self.assertEqual(group["location_evidence"], {
                    "scope": "not_assessed", "reason": "no_classified_pair"})
            results[mode] = payload
            self.assertEqual(ordinary_projection(expected), ordinary_projection(payload),
                             f"Frozen ordinary evidence changed; see {output}")
            if diagnostics and "diagnostics" in expected:
                self.assertEqual(diagnostic_projection(expected), diagnostic_projection(payload),
                                 f"Frozen diagnostic evidence changed; see {output}")
        self.assertEqual(results["ordinary"], results["results_only"])
        self.assertEqual(results["diagnostic"], results["diagnostic_results_only"])
        standard = dict(results["diagnostic"])
        standard.pop("diagnostics")
        self.assertEqual(standard, results["ordinary"])
        self.assertIn("locator_audit", case, "Run baseline indexing with --audit-locators first")
        for xml_path in xml_paths.values():
            from tests.support.validation import compare_xml_files_exact
            self.assertEqual(compare_xml_files_exact(paths["xml"], xml_path), [],
                             f"Native annotation XML differs beyond intentional locator qualifiers: {xml_path}")
            # The frozen audit records old ambiguity; current srcReader emits
            # post-predicate positions and every current locator must be unique.
            validate_native_xml(input_path, xml_path, results["diagnostic"])
        self.assertEqual(xml_paths["ordinary"].read_bytes(), xml_paths["diagnostic"].read_bytes())


def load_tests(loader, tests, pattern):
    # Baseline bytes are an explicit, ignored local artifact, not checked-in
    # fabricated goldens. Keep this migration replay opt-in during Phase 2.
    location = os.environ.get("SRCMOVE_RESULTS_V3_BASELINE")
    if not location:
        return unittest.TestSuite()
    baseline = Path(location).resolve()
    manifest_path = baseline / "replay-manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError("Capture/index the frozen baseline first: " + str(manifest_path))
    manifest = json.loads(manifest_path.read_text())
    receipt = json.loads((baseline.parent / "baseline-identity.json").read_text())
    if manifest["binary_sha256"] != receipt["binary_sha256"]:
        raise RuntimeError("Baseline manifest executable identity disagrees")
    if not manifest.get("cases"):
        raise RuntimeError("Frozen replay manifest contains no producer cases")
    if any("locator_audit" not in case for case in manifest["cases"]):
        raise RuntimeError("Index the baseline with tests/support/results_v3.py --audit-locators first")
    return unittest.TestSuite(ResultsSchemaV3Replay(case, baseline) for case in manifest["cases"])
