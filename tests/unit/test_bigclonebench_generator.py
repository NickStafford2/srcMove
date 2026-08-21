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
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATOR_PATH = REPO_ROOT / "benchmarks" / "bigclonebench" / "generate.py"


def load_generator_module():
    spec = importlib.util.spec_from_file_location(
        "bigclonebench_generate", GENERATOR_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {GENERATOR_PATH}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class BigCloneBenchGeneratorTests(unittest.TestCase):
    def test_known_false_positive_query_uses_function_metadata_and_judgments(self) -> None:
        generator = load_generator_module()

        query = generator.selection_query(
            25,
            None,
            known_false_positives=True,
            min_judges=2,
            min_confidence=3,
        )

        self.assertIn("FROM false_positives fp", query)
        self.assertNotIn("f1.tokens >=", query)
        self.assertNotIn("f2.tokens >=", query)
        self.assertIn("f1.internal = FALSE", query)
        self.assertIn("f2.internal = FALSE", query)
        self.assertIn("fp.min_judges >= 2", query)
        self.assertIn("fp.min_confidence >= 3", query)
        self.assertIn("AS min_tokens", query)
        self.assertNotIn("fp.min_tokens", query)
        self.assertNotIn("fp.internal", query)

    def test_positive_query_has_no_token_threshold(self) -> None:
        generator = load_generator_module()

        query = generator.selection_query(25, 1)

        self.assertIn("c.syntactic_type = 1", query)
        self.assertIn("c.internal = FALSE", query)
        self.assertNotIn("c.min_tokens >=", query)

    def test_preflight_reports_manual_prerequisites_without_downloading(self) -> None:
        generator = load_generator_module()

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            generator, "BCE_DIR", Path(tmp) / "missing-BigCloneEval"
        ), mock.patch.object(generator.shutil, "which", return_value=None):
            failures = generator.preflight()

        self.assertTrue(any("database" in failure for failure in failures))
        self.assertTrue(any("H2 driver" in failure for failure in failures))
        self.assertTrue(any("IJaDataset" in failure for failure in failures))
        self.assertIn("Java executable not found on PATH", failures)

    def test_preflight_rejects_an_empty_ijadataset_directory(self) -> None:
        generator = load_generator_module()

        with tempfile.TemporaryDirectory() as tmp:
            bce_dir = Path(tmp) / "BigCloneEval"
            (bce_dir / "bigclonebenchdb").mkdir(parents=True)
            (bce_dir / "bigclonebenchdb" / "bcb.h2.db").touch()
            (bce_dir / "libs").mkdir()
            (bce_dir / "libs" / "h2-1.3.176.jar").touch()
            (bce_dir / "ijadataset").mkdir()
            with mock.patch.object(generator, "BCE_DIR", bce_dir), mock.patch.object(
                generator.shutil, "which", return_value="/usr/bin/java"
            ):
                failures = generator.preflight()

        self.assertEqual(len(failures), 1)
        self.assertIn("IJaDataset Java corpus not found", failures[0])

    def test_preflight_accepts_reduced_ijadataset_layout(self) -> None:
        generator = load_generator_module()

        with tempfile.TemporaryDirectory() as tmp:
            bce_dir = Path(tmp) / "BigCloneEval"
            (bce_dir / "bigclonebenchdb").mkdir(parents=True)
            (bce_dir / "bigclonebenchdb" / "bcb.h2.db").touch()
            (bce_dir / "libs").mkdir()
            (bce_dir / "libs" / "h2-1.3.176.jar").touch()
            source_dir = bce_dir / "ijadataset" / "bcb_reduced" / "2" / "default"
            source_dir.mkdir(parents=True)
            (source_dir / "131818.java").touch()
            with mock.patch.object(generator, "BCE_DIR", bce_dir), mock.patch.object(
                generator.shutil, "which", return_value="/usr/bin/java"
            ):
                failures = generator.preflight()

        self.assertEqual(failures, [])

    def test_source_path_supports_flat_and_reduced_layouts(self) -> None:
        generator = load_generator_module()

        with tempfile.TemporaryDirectory() as tmp:
            bce_dir = Path(tmp) / "BigCloneEval"
            reduced = (
                bce_dir
                / "ijadataset"
                / "bcb_reduced"
                / "2"
                / "default"
                / "131818.java"
            )
            reduced.parent.mkdir(parents=True)
            reduced.touch()
            with mock.patch.object(generator, "BCE_DIR", bce_dir):
                self.assertEqual(
                    generator.source_path("default", "131818.java", 2), reduced
                )

                flat = bce_dir / "ijadataset" / "default" / "131818.java"
                flat.parent.mkdir(parents=True)
                flat.touch()
                self.assertEqual(
                    generator.source_path("default", "131818.java", 2), flat
                )

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

    def test_synthetic_sources_do_not_emit_method_anchors(self) -> None:
        generator = load_generator_module()

        top_level_fragment = generator.dedent_fragment(
            "      void movedTo() {\n"
            "          call();\n"
            "      }\n"
        )
        original, modified, original_range, modified_range = (
            generator.build_synthetic_move_sources(
                "BCBMove1_2",
                "      void movedFrom() {\n      }\n",
                top_level_fragment,
            )
        )

        for source in (original, modified):
            self.assertNotIn("beforeAnchor", source)
            self.assertNotIn("middleAnchor", source)
            self.assertNotIn("targetAnchor", source)
            self.assertNotIn("afterAnchor", source)
            self.assertIn("public class BCBMove1_2", source)
            self.assertIn("SOURCE_CONTEXT = 100", source)

        self.assertIn("void movedFrom()", original)
        self.assertIn("}\nvoid movedTo()", modified)
        self.assertNotIn("}\n      void movedTo()", modified)
        self.assertNotIn("void movedTo()", original)
        self.assertNotIn("void movedFrom()", modified)

        original_lines = original.splitlines()
        modified_lines = modified.splitlines()
        self.assertEqual(
            "\n".join(original_lines[original_range[0] - 1 : original_range[1]]),
            "      void movedFrom() {\n      }",
        )
        self.assertEqual(
            "\n".join(modified_lines[modified_range[0] - 1 : modified_range[1]]),
            "void movedTo() {\n    call();\n}",
        )


if __name__ == "__main__":
    unittest.main()
