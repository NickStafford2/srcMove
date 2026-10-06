from __future__ import annotations

import io
import unittest
import sys
import json
import tempfile
from unittest.mock import patch
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

TESTS_ROOT = Path(__file__).resolve().parents[1]
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

import run
from support.cases import regression_case_names


class TestInventoryTests(unittest.TestCase):
    def test_expected_regression_cases_are_discoverable(self) -> None:
        self.assertIn("1x1_basic", regression_case_names("xml"))
        self.assertIn("blocks_swapped", regression_case_names("source"))
        self.assertIn(
            "direct_numeric_literal", regression_case_names("policy")
        )

    def test_case_selection_routes_to_owning_suite(self) -> None:
        selected = run.select_regression_cases(
            ["xml", "source", "policy"],
            ["1x1_basic", "blocks_swapped", "direct_numeric_literal"],
        )

        self.assertEqual(selected["xml"], ["1x1_basic"])
        self.assertEqual(selected["source"], ["blocks_swapped"])
        self.assertEqual(selected["policy"], ["direct_numeric_literal"])

    def test_unknown_case_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "case not found"):
            run.select_regression_cases(["xml", "source"], ["does-not-exist"])

    def test_inventory_lists_focused_non_regression_suite(self) -> None:
        output = io.StringIO()

        with redirect_stdout(output):
            run.print_inventory()

        self.assertIn(
            "srcmove-history: focused srcmove-history unit tests",
            output.getvalue(),
        )

    def test_srcmove_history_suite_uses_nested_test_directory(self) -> None:
        steps = run.test_steps(
            SimpleNamespace(cases=None),
            ["srcmove-history"],
            {},
            None,
            None,
        )

        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0].name, "srcmove-history unit")
        self.assertEqual(
            steps[0].command[-6:],
            [
                "-s",
                "tests/unit/srcmove_history",
                "-t",
                ".",
                "-p",
                "test_*.py",
            ],
        )


class ToolProvenanceTests(unittest.TestCase):
    def test_component_paths_and_diagnostics_use_their_explicit_sources(self) -> None:
        alternate = Path("/alternate/srcMove")
        component_dir = Path("/other/component-build")
        steps = run.test_steps(SimpleNamespace(cases=None, component_build_dir=component_dir),
                               ["unit"], {}, alternate, Path("/alternate/srcdiff"))
        components = [step for step in steps if step.name.endswith("component")
                      and step.name != "shadow diagnostics component"]
        self.assertIn("canonical forms component", [step.name for step in components])
        self.assertTrue(all(Path(step.command[0]).parent == component_dir for step in components))
        diagnostic = next(step for step in steps if step.name == "shadow diagnostics component")
        self.assertEqual(diagnostic.command[2], str(alternate))

    def test_resolved_tools_reach_real_subprocess_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            scratch = Path(directory)
            log = scratch / "invocations.jsonl"
            spies = []
            for name in ("srcMove", "srcdiff"):
                tool = scratch / name
                tool.write_text("#!" + sys.executable + "\nimport json, os, sys\n"
                                "with open(os.environ['PROVENANCE_LOG'], 'a') as out:\n"
                                "    out.write(json.dumps(sys.argv) + '\\n')\n")
                tool.chmod(0o755)
                spies.append(tool)
            env = run.resolved_tool_environment(*spies)
            env["PROVENANCE_LOG"] = str(log)
            script = ("from pathlib import Path; from benchmarking.tooling import "
                      "find_srcmove, find_srcdiff, run_command; "
                      "root=Path('.'); "
                      "run_command([str(find_srcmove(root)), 'move-spy']); "
                      "run_command([str(find_srcdiff(root)), 'diff-spy'])")
            with redirect_stdout(io.StringIO()):
                self.assertTrue(run.run_step(run.TestStep("provenance spy", [sys.executable, "-c", script]), env))
            calls = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertEqual(calls, [[str(spies[0]), "move-spy"], [str(spies[1]), "diff-spy"]])

    def test_unit_only_main_resolves_overrides_and_propagates_environment(self) -> None:
        args = SimpleNamespace(list=False, suite=["unit"], cases=None,
                               srcmove=Path("/chosen/srcMove"), srcdiff=Path("/chosen/srcdiff"),
                               component_build_dir=Path("/components"))
        with patch.object(run, "parse_args", return_value=args), \
             patch.object(run, "find_srcmove", return_value=args.srcmove) as move_lookup, \
             patch.object(run, "find_srcdiff", return_value=args.srcdiff) as diff_lookup, \
             patch.object(run, "run_step", return_value=True) as execute, \
             redirect_stdout(io.StringIO()):
            self.assertEqual(run.main(), 0)
        move_lookup.assert_called_once_with(run.REPO_ROOT, args.srcmove)
        diff_lookup.assert_called_once_with(run.REPO_ROOT, args.srcdiff)
        for call in execute.call_args_list:
            self.assertEqual(call.args[1]["SRCMOVE_BIN"], str(args.srcmove))
            self.assertEqual(call.args[1]["SRCDIFF_BIN"], str(args.srcdiff))


if __name__ == "__main__":
    unittest.main()
