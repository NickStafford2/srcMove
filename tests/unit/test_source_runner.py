from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = REPO_ROOT / "tests" / "regression" / "source" / "run.py"
SPEC = importlib.util.spec_from_file_location("source_regression_runner", RUNNER_PATH)
assert SPEC is not None and SPEC.loader is not None
source_runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = source_runner
SPEC.loader.exec_module(source_runner)


class SourceRunnerInputTests(unittest.TestCase):
    def test_single_file_revisions_use_same_logical_relative_filename(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            case_dir = root / "case"
            case_dir.mkdir()
            original = case_dir / "original.cpp"
            modified = case_dir / "modified.cpp"
            original.write_text("int before;\n", encoding="utf-8")
            modified.write_text("int after;\n", encoding="utf-8")
            case = source_runner.SourceCaseSpec(
                name="case",
                case_dir=case_dir,
                original=original,
                modified=modified,
                oracle_json=case_dir / "oracle.json",
                is_archive=False,
            )

            before_arg, after_arg, cwd = source_runner.prepare_srcdiff_inputs(
                case, root / "results" / "case"
            )

            before_root = Path(before_arg)
            after_root = Path(after_arg)
            before_files = [
                path.relative_to(before_root)
                for path in before_root.rglob("*")
                if path.is_file()
            ]
            after_files = [
                path.relative_to(after_root)
                for path in after_root.rglob("*")
                if path.is_file()
            ]
            self.assertIsNone(cwd)
            self.assertNotEqual(before_root, after_root)
            self.assertEqual(before_files, [Path("source.cpp")])
            self.assertEqual(after_files, before_files)
            self.assertEqual(
                (before_root / "source.cpp").read_text(encoding="utf-8"),
                "int before;\n",
            )
            self.assertEqual(
                (after_root / "source.cpp").read_text(encoding="utf-8"),
                "int after;\n",
            )


if __name__ == "__main__":
    unittest.main()
