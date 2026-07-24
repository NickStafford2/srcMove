#!/usr/bin/env python3
"""Regression tests for BigCloneBench case generation helpers.

These tests exist because IJaDataset files can contain standalone carriage
returns inside comments, while BigCloneBench source ranges are LF-based. The
generator must not let Python's universal newline splitting shift those ranges.


  This test checks one very specific bug.

  It creates a temporary file that looks roughly like this:

  class Example {
  /** first comment line\rsecond display line\rthird display line */
    void target() {
      call();
    }
  }

  The important part is the \r characters inside the comment. Python’s normal splitlines() treats those as real line breaks. If the generator used splitlines(), it would think the target() method starts later
  than it actually does.

  Then the test calls:

  extract_lines(source, 3, 5)

  And expects to get:

    void target() {
      call();
    }

  So the test proves: “when a BigCloneBench source file has standalone carriage returns inside comments, our generator still extracts by LF-based line numbers and does not drift.”

  It is not testing srcMove. It is testing that the benchmark input we feed into srcMove is extracted correctly.

"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
GENERATOR_PATH = REPO_ROOT / "scripts" / "generate_bigclonebench_move_cases.py"


def load_generator_module():
    spec = importlib.util.spec_from_file_location(
        "generate_bigclonebench_move_cases", GENERATOR_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {GENERATOR_PATH}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class BigCloneBenchGeneratorTests(unittest.TestCase):
    def test_extract_lines_uses_lf_ranges_when_comments_contain_cr(self) -> None:
        generator = load_generator_module()

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "sample.java"
            source.write_text(
                "class Example {\n"
                "/** first comment line\rsecond display line\rthird display line */\n"
                "  void target() {\n"
                "    call();\n"
                "  }\n"
                "}\n",
                encoding="utf-8",
                newline="",
            )

            self.assertEqual(
                generator.extract_lines(source, 3, 5),
                "  void target() {\n    call();\n  }\n",
            )


if __name__ == "__main__":
    unittest.main()
